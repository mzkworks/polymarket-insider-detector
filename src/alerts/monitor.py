from __future__ import annotations

import asyncio
import logging
import time

from src.alerts.discord import DiscordAlerter
from src.data.database import Database
from src.data.polymarket_client import PolymarketClient

logger = logging.getLogger(__name__)

# Poll interval for checking new trades from flagged wallets
POLL_INTERVAL_SECONDS = 30
# Minimum insider score to monitor a wallet
MIN_SCORE_TO_MONITOR = 25.0


class InsiderMonitor:
    """Real-time monitor that watches flagged wallets and sends Discord alerts.

    Polls the Data API for recent trades and cross-references against
    the flagged wallet list from wallet_scores.

    The WebSocket doesn't include wallet addresses in trade events,
    so we poll the Data API instead for wallet-level monitoring.
    """

    def __init__(
        self,
        db: Database,
        discord: DiscordAlerter,
        min_score: float = MIN_SCORE_TO_MONITOR,
        poll_interval: int = POLL_INTERVAL_SECONDS,
    ):
        self.db = db
        self.discord = discord
        self.min_score = min_score
        self.poll_interval = poll_interval
        self._running = False
        self._flagged_wallets: dict[str, dict] = {}  # wallet -> score record
        self._seen_trade_ids: set[str] = set()
        self._last_poll_ts: int = 0

    def load_flagged_wallets(self) -> int:
        """Load wallets with insider_score >= min_score from the database."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM wallet_scores
                   WHERE insider_score >= ?
                   ORDER BY insider_score DESC""",
                (self.min_score,),
            ).fetchall()

        self._flagged_wallets = {r["wallet_address"]: dict(r) for r in rows}
        logger.info(
            "Loaded %d flagged wallets (score >= %.0f)",
            len(self._flagged_wallets),
            self.min_score,
        )
        return len(self._flagged_wallets)

    async def poll_recent_trades(self, client: PolymarketClient) -> list[dict]:
        """Poll Data API for recent trades and filter for flagged wallets."""
        # Get the most recent trades (global, not per-market)
        try:
            trades = await client.fetch_trades_page(offset=0, limit=100)
        except Exception:
            logger.exception("Failed to poll trades")
            return []

        flagged_trades = []
        for trade in trades:
            wallet = trade.get("proxyWallet", "")
            if wallet not in self._flagged_wallets:
                continue

            # Generate trade ID for dedup
            trade_id = PolymarketClient.make_trade_id(trade)
            if trade_id in self._seen_trade_ids:
                continue

            self._seen_trade_ids.add(trade_id)
            flagged_trades.append(trade)

        # Keep seen set from growing unbounded
        if len(self._seen_trade_ids) > 10000:
            self._seen_trade_ids = set(list(self._seen_trade_ids)[-5000:])

        return flagged_trades

    async def alert_on_trade(self, trade: dict) -> None:
        """Send a Discord alert for a flagged wallet trade."""
        wallet = trade.get("proxyWallet", "")
        score_data = self._flagged_wallets.get(wallet, {})

        # Look up cluster info
        cluster_id = score_data.get("cluster_id")
        cluster_size = None
        if cluster_id:
            with self.db.get_connection() as conn:
                row = conn.execute(
                    "SELECT wallet_count FROM clusters WHERE cluster_id = ?",
                    (cluster_id,),
                ).fetchone()
                if row:
                    cluster_size = row["wallet_count"]

        market_question = trade.get("title", "Unknown Market")
        side = trade.get("outcome", trade.get("side", "?"))
        price = float(trade.get("price", 0))
        size = float(trade.get("size", 0))

        await self.discord.send_insider_alert(
            wallet=wallet,
            market_question=market_question,
            side=side,
            price=price,
            size=size,
            insider_score=score_data.get("insider_score", 0),
            win_rate=score_data.get("win_rate", 0),
            total_trades=score_data.get("total_trades", 0),
            p_value=score_data.get("p_value", 1.0),
            cluster_id=cluster_id,
            cluster_size=cluster_size,
        )

    async def run(self) -> None:
        """Main monitoring loop. Polls for trades and sends alerts."""
        self._running = True
        self.load_flagged_wallets()

        if not self._flagged_wallets:
            logger.warning("No flagged wallets to monitor. Run scoring first.")
            return

        if not self.discord.enabled:
            logger.warning(
                "Discord webhook not configured. "
                "Alerts will be logged but not sent."
            )

        logger.info(
            "Starting monitor: polling every %ds for %d flagged wallets",
            self.poll_interval,
            len(self._flagged_wallets),
        )

        async with PolymarketClient() as client:
            while self._running:
                flagged_trades = await self.poll_recent_trades(client)

                for trade in flagged_trades:
                    wallet = trade.get("proxyWallet", "")[:10]
                    logger.info(
                        "FLAGGED TRADE: %s... %s %s @ $%.2f ($%s)",
                        wallet,
                        trade.get("side"),
                        trade.get("outcome"),
                        float(trade.get("price", 0)),
                        trade.get("size"),
                    )
                    await self.alert_on_trade(trade)

                await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
        logger.info("Monitor stopping...")
