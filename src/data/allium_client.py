from __future__ import annotations

import httpx

from src.config import ALLIUM_API_BASE, ALLIUM_API_KEY


class AlliumClient:
    """Allium API client for wallet funding source analysis.

    Returns empty results when ALLIUM_API_KEY is not set.
    """

    def __init__(self):
        self._api_key = ALLIUM_API_KEY
        self._enabled = bool(self._api_key)
        self._http = httpx.AsyncClient(
            base_url=ALLIUM_API_BASE,
            headers={"X-API-Key": self._api_key} if self._enabled else {},
            timeout=30.0,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def get_wallet_transactions(
        self, address: str, chain: str = "polygon"
    ) -> list[dict]:
        """Fetch wallet transactions from Allium.
        
        Args:
            address: Wallet address
            chain: Blockchain (lowercase: ethereum, polygon, solana, arbitrum, base, hyperevm)
            
        Returns:
            List of transaction dicts or empty list if disabled
        """
        if not self._enabled:
            return []
        
        try:
            response = await self._http.post(
                "/api/v1/developer/wallet/transactions",
                json={"address": address, "chain": chain.lower()},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("transactions", [])
        except httpx.HTTPError as e:
            print(f"Allium wallet transactions error: {e}")
            return []

    async def get_wallet_balances(self, address: str, chain: str = "ethereum") -> list[dict]:
        """Fetch wallet token balances from Allium.
        
        Args:
            address: Wallet address
            chain: Blockchain (lowercase)
            
        Returns:
            List of balance dicts or empty list if disabled
        """
        if not self._enabled:
            return []
        
        try:
            response = await self._http.post(
                "/api/v1/developer/wallet/balances",
                json={"address": address, "chain": chain.lower()},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("balances", [])
        except httpx.HTTPError as e:
            print(f"Allium wallet balances error: {e}")
            return []

    async def get_wallet_pnl(self, address: str, chain: str = "ethereum") -> dict | None:
        """Fetch wallet PnL (profit/loss) from Allium.
        
        Args:
            address: Wallet address
            chain: Blockchain (lowercase)
            
        Returns:
            PnL dict with realized/unrealized profit or None
        """
        if not self._enabled:
            return None
        
        try:
            response = await self._http.post(
                "/api/v1/developer/wallet/pnl",
                json={"address": address, "chain": chain.lower()},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            print(f"Allium wallet PnL error: {e}")
            return None

    async def find_funding_source(self, address: str) -> str | None:
        """Infer funding source by examining wallet history.
        
        Checks if wallet received funds from known exchanges/services.
        This requires custom SQL against Allium's schema.
        """
        if not self._enabled:
            return None
        
        # For now, return None - requires SQL query setup
        # TODO: Implement via custom SQL endpoint
        return None

    async def check_shared_funding(self, addresses: list[str]) -> dict[str, str]:
        """Check if multiple wallets share a funding source.
        
        Returns dict mapping address → funding source if found.
        """
        if not self._enabled:
            return {}
        
        result = {}
        for address in addresses:
            source = await self.find_funding_source(address)
            if source:
                result[address] = source
        return result

    async def close(self) -> None:
        await self._http.aclose()
