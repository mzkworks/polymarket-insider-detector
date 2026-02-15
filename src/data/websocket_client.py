from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Callable

import websockets

from src.config import WS_URL

logger = logging.getLogger(__name__)

RECONNECT_DELAY_BASE = 1.0
RECONNECT_MAX_DELAY = 60.0


class PolymarketWebSocket:
    """Real-time trade stream from Polymarket WebSocket.

    Subscribes to the market channel for live trade events.
    No authentication required for market data.

    Note: WebSocket trade events (last_trade_price) do NOT include
    wallet addresses. Use DataAPI polling to match trades to wallets.
    """

    def __init__(self, asset_ids: list[str] | None = None):
        self.url = f"{WS_URL}/ws/market"
        self.asset_ids = asset_ids or []
        self._ws = None
        self._running = False

    async def connect_and_stream(
        self,
        on_trade: Callable[[dict], None] | None = None,
    ) -> AsyncIterator[dict]:
        """Connect to WebSocket and yield trade events.

        Auto-reconnects on disconnection with exponential backoff.
        """
        self._running = True
        delay = RECONNECT_DELAY_BASE

        while self._running:
            try:
                async with websockets.connect(self.url, ping_interval=30) as ws:
                    self._ws = ws
                    logger.info("Connected to Polymarket WebSocket")
                    delay = RECONNECT_DELAY_BASE  # Reset on successful connect

                    # Subscribe to markets
                    subscribe_msg = {
                        "type": "market",
                        "assets_ids": self.asset_ids,
                    }
                    await ws.send(json.dumps(subscribe_msg))
                    logger.info("Subscribed to %d assets", len(self.asset_ids))

                    async for raw_msg in ws:
                        try:
                            msgs = json.loads(raw_msg)
                            # Can be a single message or array
                            if isinstance(msgs, dict):
                                msgs = [msgs]
                            for msg in msgs:
                                if msg.get("event_type") == "last_trade_price":
                                    if on_trade:
                                        on_trade(msg)
                                    yield msg
                        except json.JSONDecodeError:
                            logger.warning("Invalid JSON from WebSocket: %s", raw_msg[:100])

            except (websockets.exceptions.ConnectionClosed, ConnectionError, OSError) as e:
                if not self._running:
                    break
                logger.warning("WebSocket disconnected: %s. Reconnecting in %.0fs...", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_DELAY)

    async def subscribe(self, asset_ids: list[str]) -> None:
        """Subscribe to additional assets on an existing connection."""
        if self._ws:
            msg = {
                "assets_ids": asset_ids,
                "operation": "subscribe",
            }
            await self._ws.send(json.dumps(msg))
            self.asset_ids.extend(asset_ids)
            logger.info("Subscribed to %d more assets", len(asset_ids))

    async def unsubscribe(self, asset_ids: list[str]) -> None:
        """Unsubscribe from assets."""
        if self._ws:
            msg = {
                "assets_ids": asset_ids,
                "operation": "unsubscribe",
            }
            await self._ws.send(json.dumps(msg))

    def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._running = False
