from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from src.analysis.stats import (
    binomial_p_value,
    composite_insider_score,
    compute_pnl,
    size_win_correlation,
    timing_score,
)
from src.data.database import Database

logger = logging.getLogger(__name__)


def _parse_resolution_ts(resolution_time: str | None) -> int | None:
    """Parse resolution_time string to unix timestamp."""
    if not resolution_time:
        return None
    try:
        # Format: "2020-11-02 16:31:01+00"
        for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                dt = datetime.strptime(resolution_time, fmt)
                return int(dt.timestamp())
            except ValueError:
                continue
        # Fallback: try replacing space with T
        dt = datetime.fromisoformat(resolution_time.replace(" ", "T"))
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


class WalletScorer:
    """Scores wallets based on their trading patterns.

    For each wallet, calculates:
      - Win rate
      - Timing score (avg seconds before resolution)
      - P-value (binomial test against entry prices)
      - Size-win correlation
      - PnL
      - Composite insider score (0-100)
    """

    def __init__(self, db: Database, min_trades: int = 20):
        self.db = db
        self.min_trades = min_trades
        # Cache market resolution times
        self._resolution_cache: dict[str, int | None] = {}

    def _get_resolution_ts(self, market_id: str) -> int | None:
        """Get cached resolution timestamp for a market."""
        if market_id not in self._resolution_cache:
            market = self.db.get_market(market_id)
            if market:
                self._resolution_cache[market_id] = _parse_resolution_ts(
                    market.get("resolution_time")
                )
            else:
                self._resolution_cache[market_id] = None
        return self._resolution_cache[market_id]

    def score_wallet(self, wallet_address: str, trades: list[dict] | None = None) -> dict | None:
        """Score a single wallet.

        Args:
            wallet_address: The wallet to score
            trades: Pre-loaded trades for this wallet (optional, will query if not provided)

        Returns a dict matching the wallet_scores schema, or None if
        the wallet doesn't meet the minimum trade threshold.
        """
        if trades is None:
            trades = self.db.get_trades_for_wallet(wallet_address)
        else:
            trades = trades  # Use pre-loaded trades

        # Only consider BUY trades on resolved markets (where is_winner is set)
        resolved_trades = [
            t for t in trades
            if t["is_winner"] is not None and t["side"] == "BUY"
        ]

        if len(resolved_trades) < self.min_trades:
            return None

        total = len(resolved_trades)
        wins = sum(1 for t in resolved_trades if t["is_winner"])
        win_rate = wins / total if total > 0 else 0.0

        # Average entry price (implied probability) across all trades
        avg_entry_price = sum(t["price"] for t in resolved_trades) / total

        # P-value: how unlikely is this win rate given entry prices?
        p_val = binomial_p_value(wins, total, avg_entry_price)

        # Size-win correlation
        sizes = [t["size"] for t in resolved_trades]
        win_flags = [bool(t["is_winner"]) for t in resolved_trades]
        size_corr = size_win_correlation(sizes, win_flags)

        # Timing score: avg seconds between entry and market resolution
        timing_values = []
        for t in resolved_trades:
            res_ts = self._get_resolution_ts(t["market_id"])
            if res_ts is not None:
                ts = timing_score(t["timestamp"], res_ts)
                if ts > 0:  # Only count trades made before resolution
                    timing_values.append(ts)

        avg_timing = sum(timing_values) / len(timing_values) if timing_values else float("inf")

        # PnL
        total_pnl = sum(
            compute_pnl(t["price"], t["size"], bool(t["is_winner"]), t["side"])
            for t in resolved_trades
        )

        # Composite score
        insider = composite_insider_score(
            win_rate=win_rate,
            p_value=p_val,
            timing_avg=avg_timing,
            size_corr=size_corr,
            total_pnl=total_pnl,
            total_trades=total,
        )

        # Extract EOA address from first trade (all trades for same proxy have same EOA)
        eoa_address = None
        if trades:
            eoa_address = trades[0].get("eoa_address")

        return {
            "wallet_address": wallet_address,
            "eoa_address": eoa_address,
            "total_trades": total,
            "win_rate": round(win_rate, 6),
            "avg_entry_before_resolution": round(avg_timing, 2),
            "p_value": p_val,
            "size_win_correlation": round(size_corr, 6),
            "total_pnl": round(total_pnl, 2),
            "insider_score": insider,
            "cluster_id": None,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def score_all_wallets(self, min_trades: int | None = None) -> list[dict]:
        """Score all wallets that meet the minimum trade threshold.

        Returns list of score dicts sorted by insider_score descending.
        """
        threshold = min_trades if min_trades is not None else self.min_trades
        wallets = self.db.get_all_active_wallets(min_trades=threshold)
        logger.info("Scoring %d wallets with >= %d trades", len(wallets), threshold)
        logger.info("Querying trades per wallet (using indexed queries)...")

        scores = []
        total_wallets = len(wallets)
        for idx, wallet in enumerate(wallets, 1):
            # Query per wallet - with composite index this should be fast
            result = self.score_wallet(wallet, trades=None)  # Let score_wallet query the DB
            if result:
                scores.append(result)
            # Progress output every 10 wallets for better visibility
            if idx % 10 == 0 or idx == total_wallets:
                logger.info(f"Progress: {idx}/{total_wallets} wallets processed ({100*idx/total_wallets:.1f}%)")

        scores.sort(key=lambda s: s["insider_score"], reverse=True)
        return scores

    def save_scores(self, scores: list[dict]) -> None:
        """Persist wallet scores to the database."""
        if not scores:
            return
        with self.db.get_connection() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO wallet_scores
                   (wallet_address, eoa_address, total_trades, win_rate, avg_entry_before_resolution,
                    p_value, size_win_correlation, total_pnl, insider_score,
                    cluster_id, last_updated)
                   VALUES (:wallet_address, :eoa_address, :total_trades, :win_rate, :avg_entry_before_resolution,
                           :p_value, :size_win_correlation, :total_pnl, :insider_score,
                           :cluster_id, :last_updated)""",
                scores,
            )
            conn.commit()
        logger.info("Saved %d wallet scores", len(scores))
