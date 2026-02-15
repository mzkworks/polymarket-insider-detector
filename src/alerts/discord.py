from __future__ import annotations

import logging

import httpx

from src.config import DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)


class DiscordAlerter:
    """Send alerts to Discord via webhook."""

    def __init__(self, webhook_url: str = DISCORD_WEBHOOK_URL):
        self.webhook_url = webhook_url
        self.enabled = bool(webhook_url)
        self._http = httpx.AsyncClient(timeout=10.0)

    async def send_raw(self, content: str) -> bool:
        """Send a plain text message."""
        if not self.enabled:
            logger.warning("Discord webhook not configured")
            return False
        resp = await self._http.post(self.webhook_url, json={"content": content})
        return resp.status_code == 204

    async def send_insider_alert(
        self,
        wallet: str,
        market_question: str,
        side: str,
        price: float,
        size: float,
        insider_score: float,
        win_rate: float,
        total_trades: int,
        p_value: float,
        cluster_id: str | None = None,
        cluster_size: int | None = None,
    ) -> bool:
        """Send a rich embed alert for a flagged wallet trade."""
        if not self.enabled:
            logger.warning("Discord webhook not configured")
            return False

        # Severity color
        if insider_score >= 70:
            color = 0xFF0000  # Red
            severity = "CRITICAL"
        elif insider_score >= 50:
            color = 0xFF8C00  # Orange
            severity = "HIGH"
        else:
            color = 0xFFD700  # Yellow
            severity = "MEDIUM"

        # Format p-value
        p_str = f"{p_value:.2e}" if p_value < 0.001 else f"{p_value:.4f}"

        fields = [
            {"name": "Market", "value": market_question[:100], "inline": False},
            {"name": "Position", "value": f"{side} @ ${price:.2f} - ${size:,.0f}", "inline": True},
            {"name": "Insider Score", "value": f"{insider_score:.1f}/100", "inline": True},
            {"name": "Win Rate", "value": f"{win_rate:.1%} ({total_trades} trades)", "inline": True},
            {"name": "P-Value", "value": p_str, "inline": True},
        ]

        if cluster_id and cluster_size:
            fields.append({
                "name": "Cluster",
                "value": f"Part of {cluster_size}-wallet network",
                "inline": True,
            })

        # Wallet address linked to polygonscan
        wallet_short = f"{wallet[:6]}...{wallet[-4:]}"
        wallet_link = f"[{wallet_short}](https://polygonscan.com/address/{wallet})"

        embed = {
            "title": f"INSIDER ALERT - {severity}",
            "description": f"Wallet: {wallet_link}",
            "color": color,
            "fields": fields,
            "footer": {"text": "Polymarket Insider Detector"},
        }

        resp = await self._http.post(
            self.webhook_url,
            json={"embeds": [embed]},
        )

        if resp.status_code == 204:
            logger.info("Discord alert sent for %s", wallet_short)
            return True
        else:
            logger.error("Discord alert failed: %d %s", resp.status_code, resp.text)
            return False

    async def close(self) -> None:
        await self._http.aclose()
