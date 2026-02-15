from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import socket
import time
from typing import AsyncIterator, Optional

import httpx

from src.config import (
    CLOB_API_BASE,
    CLOB_RATE_LIMIT,
    DATA_API_BASE,
    DATA_API_PAGE_SIZE,
    GAMMA_API_BASE,
    GAMMA_PAGE_SIZE,
    GAMMA_RATE_LIMIT,
    DATA_API_RATE_LIMIT,
    MAX_RETRIES,
    RETRY_BACKOFF_BASE,
    DATA_API_TRADES_ORDER,
    SSL_VERIFY,
)
from src.data.dns_resolver import resolve_with_google_dns

logger = logging.getLogger(__name__)

# Pre-resolve Polymarket domains using Google DNS at module load time
_dns_cache: dict[str, str] = {}
_polymarket_domains = ['gamma-api.polymarket.com', 'clob.polymarket.com', 'data-api.polymarket.com']

# Pre-populate DNS cache
for domain in _polymarket_domains:
    ip = resolve_with_google_dns(domain, use_cache=False)
    if ip:
        _dns_cache[domain] = ip
        logger.info(f"Pre-resolved {domain} -> {ip}")

# Monkey-patch socket.getaddrinfo to use our pre-resolved IPs
_original_getaddrinfo = socket.getaddrinfo

def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """Custom getaddrinfo that uses pre-resolved IPs for Polymarket domains."""
    # Handle both bytes and str hostnames
    if isinstance(host, bytes):
        host_str = host.decode('utf-8')
    else:
        host_str = host

    logger.debug(f"getaddrinfo called for: {host_str}:{port}")

    if host_str in _dns_cache:
        ip = _dns_cache[host_str]
        logger.info(f"✓ Using cached IP {ip} for {host_str}")
        # Return properly formatted getaddrinfo result
        # Format: [(family, type, proto, canonname, sockaddr)]
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (ip, port))
        ]

    # For non-Polymarket domains, use original resolver
    logger.debug(f"Using system DNS for {host_str}")
    return _original_getaddrinfo(host, port, family, type, proto, flags)

# Apply the monkey patch
socket.getaddrinfo = custom_getaddrinfo
logger.info("Applied custom DNS resolver for Polymarket domains")


class RateLimiter:
    """Sliding-window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: float = 10.0):
        self._timestamps: list[float] = []
        self._max = max_requests
        self._window = window_seconds

    async def acquire(self) -> None:
        while True:
            now = time.monotonic()
            # Purge timestamps outside the window
            self._timestamps = [t for t in self._timestamps if now - t < self._window]
            if len(self._timestamps) < self._max:
                self._timestamps.append(now)
                return
            # Wait until the oldest timestamp expires
            sleep_for = self._window - (now - self._timestamps[0]) + 0.01
            await asyncio.sleep(sleep_for)


class PolymarketClient:
    """Async client for Polymarket Gamma, CLOB, and Data APIs."""

    def __init__(self):
        if not SSL_VERIFY:
            logger.warning("⚠️  SSL verification is DISABLED - connections are not secure!")

        logger.info("🌐 Using Google DNS (8.8.8.8) to bypass ISP DNS blocking")

        self._http = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            verify=SSL_VERIFY
        )
        self._gamma_limiter = RateLimiter(GAMMA_RATE_LIMIT, window_seconds=10.0)
        # Data API: use a 1-second window to prevent bursts (15 req/sec, smooth)
        self._data_limiter = RateLimiter(max_requests=20, window_seconds=1.0)
        self._clob_limiter = RateLimiter(CLOB_RATE_LIMIT, window_seconds=10.0)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    # --- Internal helpers ---

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        limiter: RateLimiter,
        **kwargs,
    ) -> httpx.Response:
        last_exc = None
        for attempt in range(MAX_RETRIES):
            await limiter.acquire()
            try:
                resp = await self._http.request(method, url, **kwargs)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 0))
                    wait = max(retry_after, RETRY_BACKOFF_BASE * (2**attempt))
                    logger.warning("Rate limited (429) on %s, waiting %.1fs", url, wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    wait = RETRY_BACKOFF_BASE * (2**attempt) + random.uniform(0, 1)
                    logger.warning("Server error %d on %s, retrying in %.1fs", resp.status_code, url, wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                wait = RETRY_BACKOFF_BASE * (2**attempt) + random.uniform(0, 1)
                logger.warning("Connection error on %s: %s, retrying in %.1fs", url, exc, wait)
                await asyncio.sleep(wait)

        raise last_exc or RuntimeError(f"Failed after {MAX_RETRIES} retries: {url}")

    # ==========================================
    # GAMMA API — Market metadata
    # ==========================================

    async def fetch_markets_page(
        self, offset: int = 0, limit: int = GAMMA_PAGE_SIZE, closed: bool = True
    ) -> list[dict]:
        """Fetch a page of markets from the Gamma API."""
        resp = await self._request_with_retry(
            "GET",
            f"{GAMMA_API_BASE}/markets",
            self._gamma_limiter,
            params={"limit": limit, "offset": offset, "closed": str(closed).lower()},
        )
        return resp.json()

    async def iter_all_markets(
        self, closed: bool = True, start_offset: int = 0
    ) -> AsyncIterator[tuple[list[dict], int]]:
        """Async generator yielding (page, next_offset) for all markets."""
        offset = start_offset
        while True:
            page = await self.fetch_markets_page(offset=offset, closed=closed)
            if not page:
                break
            offset += len(page)
            yield page, offset
            if len(page) < GAMMA_PAGE_SIZE:
                break

    async def fetch_market_by_id(self, market_id: str) -> dict | None:
        try:
            resp = await self._request_with_retry(
                "GET",
                f"{GAMMA_API_BASE}/markets/{market_id}",
                self._gamma_limiter,
            )
            return resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    # ==========================================
    # DATA API — Trade history (primary source)
    # ==========================================

    async def fetch_trades_page(
        self,
        condition_id: str | None = None,
        offset: int = 0,
        limit: int = DATA_API_PAGE_SIZE,
    ) -> list[dict]:
        """Fetch a page of trades from the Data API."""
        params: dict = {"limit": limit, "offset": offset}
        if condition_id:
            params["conditionId"] = condition_id
        try:
            resp = await self._request_with_retry(
                "GET",
                f"{DATA_API_BASE}/trades",
                self._data_limiter,
                params=params,
            )
            return resp.json()
        except httpx.HTTPStatusError as exc:
            # 400 errors for out-of-range offsets are expected (many markets have <4000 trades)
            # Suppress the warning and treat as end-of-data silently
            if exc.response is not None and exc.response.status_code == 400:
                return []
            raise

    async def iter_trades_for_market(
        self, condition_id: str, start_offset: int = 0, since_ts: Optional[int] = None
    ) -> AsyncIterator[list[dict]]:
        """Async generator yielding pages of trades for a specific market.

        If `since_ts` is provided (epoch seconds), the iterator will attempt to stop
        early when it detects pages older than the cutoff. Behavior depends on
        `DATA_API_TRADES_ORDER` ("desc" newest->oldest or "asc" oldest->newest).
        """
        offset = start_offset
        while True:
            page = await self.fetch_trades_page(condition_id=condition_id, offset=offset)
            if not page:
                break

            # If no cutoff, yield whole page and continue normally
            if since_ts is None:
                yield page
                if len(page) < DATA_API_PAGE_SIZE:
                    break
                offset += len(page)
                continue

            # Apply cutoff logic based on expected ordering
            try:
                timestamps = [int(t.get("timestamp", 0)) for t in page]
            except Exception:
                timestamps = []

            if DATA_API_TRADES_ORDER == "desc":
                # newest -> oldest: stop when the last trade in page is older than cutoff
                filtered = [t for t in page if int(t.get("timestamp", 0)) >= since_ts]
                if not filtered:
                    # all trades in this page are older than cutoff -> we're done
                    break
                yield filtered
                if len(page) < DATA_API_PAGE_SIZE:
                    break
                offset += len(page)
                continue

            # DATA_API_TRADES_ORDER == 'asc' (oldest -> newest)
            # Skip pages until we find trades >= since_ts, then yield from there onward.
            filtered = [t for t in page if int(t.get("timestamp", 0)) >= since_ts]
            if not filtered:
                # no recent trades yet in this page; if page is full, continue to next page
                if len(page) < DATA_API_PAGE_SIZE:
                    break
                offset += len(page)
                continue
            # There are some trades in this page newer than cutoff; yield only those
            yield filtered
            if len(page) < DATA_API_PAGE_SIZE:
                break
            offset += len(page)

    async def fetch_positions(
        self, wallet: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        resp = await self._request_with_retry(
            "GET",
            f"{DATA_API_BASE}/positions",
            self._data_limiter,
            params={"user": wallet, "limit": limit, "offset": offset},
        )
        return resp.json()

    # ==========================================
    # CLOB API — Orderbook / prices
    # ==========================================

    async def fetch_orderbook(self, token_id: str) -> dict:
        resp = await self._request_with_retry(
            "GET",
            f"{CLOB_API_BASE}/book",
            self._clob_limiter,
            params={"token_id": token_id},
        )
        return resp.json()

    async def fetch_midpoint(self, token_id: str) -> float:
        resp = await self._request_with_retry(
            "GET",
            f"{CLOB_API_BASE}/midpoint",
            self._clob_limiter,
            params={"token_id": token_id},
        )
        data = resp.json()
        return float(data.get("mid", 0))

    # ==========================================
    # Normalization helpers
    # ==========================================

    @staticmethod
    def determine_outcome(market: dict) -> str | None:
        """Determine winning outcome from a closed Gamma market.

        outcomePrices is a list like ["1", "0"] (Yes won) or ["0", "1"] (No won).
        """
        if not market.get("closed"):
            return None
        prices = market.get("outcomePrices")
        if not prices:
            return None
        # outcomePrices is a JSON-encoded list string like '["1", "0"]'
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except json.JSONDecodeError:
                prices = [p.strip() for p in prices.split(",")]
        try:
            float_prices = [float(p) for p in prices]
        except (ValueError, TypeError):
            return None
        if len(float_prices) >= 2:
            # Resolved markets have prices near 1.0/0.0 (not always exact)
            if float_prices[0] > 0.99:
                return "Yes"
            if float_prices[1] > 0.99:
                return "No"
        return None

    @staticmethod
    def normalize_market(raw: dict) -> dict:
        """Transform a Gamma API market response into our DB schema format."""
        clob_ids = raw.get("clobTokenIds")
        if isinstance(clob_ids, list):
            clob_ids = json.dumps(clob_ids)
        elif clob_ids is None:
            clob_ids = "[]"

        events = raw.get("events") or []
        event_id = events[0].get("id") if events else None

        return {
            "id": raw["id"],
            "condition_id": raw.get("conditionId"),
            "question": raw.get("question", ""),
            "slug": raw.get("slug"),
            "category": raw.get("category"),
            "event_id": event_id,
            "end_date": raw.get("endDate"),
            "resolution_time": raw.get("closedTime"),
            "outcome": PolymarketClient.determine_outcome(raw),
            "clob_token_ids": clob_ids,
            "created_at": raw.get("createdAt"),
        }

    @staticmethod
    def make_trade_id(trade: dict) -> str:
        """Generate a deterministic trade ID for dedup."""
        raw = (
            f"{trade.get('transactionHash', '')}_{trade.get('conditionId', '')}"
            f"_{trade.get('outcomeIndex', '')}_{trade.get('timestamp', '')}"
            f"_{trade.get('proxyWallet', '')}_{trade.get('size', '')}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def normalize_trade(raw: dict, market_id: str) -> dict:
        """Transform a Data API trade response into our DB schema format."""
        return {
            "id": PolymarketClient.make_trade_id(raw),
            "market_id": market_id,
            "condition_id": raw.get("conditionId"),
            "wallet_address": raw.get("proxyWallet", ""),
            "eoa_address": raw.get("makerAddress", ""),  # Polygon EOA that owns the proxy
            "side": raw.get("side", ""),
            "outcome": raw.get("outcome"),
            "outcome_index": raw.get("outcomeIndex"),
            "price": float(raw.get("price", 0)),
            "size": float(raw.get("size", 0)),
            "timestamp": int(raw.get("timestamp", 0)),
            "transaction_hash": raw.get("transactionHash"),
            "is_winner": None,
        }
