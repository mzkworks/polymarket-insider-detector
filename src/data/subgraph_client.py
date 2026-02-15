import logging

import httpx

from src.config import SUBGRAPH_URL

logger = logging.getLogger(__name__)

TRADES_QUERY = """
query GetTrades($conditionId: String!, $first: Int!, $skip: Int!) {
    trades(
        where: { condition: $conditionId }
        first: $first
        skip: $skip
        orderBy: timestamp
        orderDirection: desc
    ) {
        id
        trader
        condition { id }
        outcomeIndex
        amount
        price
        timestamp
        transactionHash
    }
}
"""

POSITIONS_QUERY = """
query GetPositions($trader: String!) {
    userPositions(where: { user: $trader }) {
        id
        condition { id }
        outcomeIndex
        balance
    }
}
"""


class SubgraphClient:
    """Client for Polymarket's Polygon subgraph on The Graph.

    Requires THEGRAPH_API_KEY. Returns empty results when unconfigured.
    """

    def __init__(self):
        self._enabled = bool(SUBGRAPH_URL)
        self._http = httpx.AsyncClient(timeout=30.0) if self._enabled else None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _query(self, query: str, variables: dict) -> dict:
        if not self._enabled or not self._http:
            return {}
        resp = await self._http.post(
            SUBGRAPH_URL,
            json={"query": query, "variables": variables},
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def fetch_trades_for_condition(
        self, condition_id: str, first: int = 1000, skip: int = 0
    ) -> list[dict]:
        if not self._enabled:
            return []
        data = await self._query(
            TRADES_QUERY,
            {"conditionId": condition_id, "first": first, "skip": skip},
        )
        return data.get("trades", [])

    async def fetch_positions_for_wallet(self, wallet: str) -> list[dict]:
        if not self._enabled:
            return []
        data = await self._query(POSITIONS_QUERY, {"trader": wallet.lower()})
        return data.get("userPositions", [])

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
