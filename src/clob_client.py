"""CLOB API client for fetching orderbook prices."""
import httpx
from typing import Optional, Tuple
import logging

from .config import get_config

logger = logging.getLogger(__name__)


class CLOBClient:
    """Client for Polymarket CLOB API."""
    
    def __init__(self):
        self._config = get_config()
        self._client = httpx.AsyncClient(timeout=10.0)
    
    async def get_best_bid(self, token_id: str) -> Optional[float]:
        """Get the best bid price for a token.
        
        Returns:
            Best bid price (highest) or None if no bids.
        """
        try:
            url = f"{self._config.clob_api_url}/book"
            response = await self._client.get(url, params={"token_id": token_id})
            response.raise_for_status()
            data = response.json()
            
            bids = data.get("bids", [])
            if bids:
                # Find the highest bid price
                best_bid = max(float(b["price"]) for b in bids)
                return best_bid
            return None
            
        except Exception as e:
            logger.warning(f"Error fetching best bid for {token_id[:20]}...: {e}")
            return None
    
    async def get_best_ask(self, token_id: str) -> Optional[float]:
        """Get the best ask price for a token."""
        try:
            url = f"{self._config.clob_api_url}/book"
            response = await self._client.get(url, params={"token_id": token_id})
            response.raise_for_status()
            data = response.json()
            
            asks = data.get("asks", [])
            if asks:
                return float(asks[0]["price"])
            return None
            
        except Exception as e:
            logger.warning(f"Error fetching best ask: {e}")
            return None
    
    async def get_prices(self, up_token_id: str, down_token_id: str) -> Tuple[Optional[float], Optional[float]]:
        """Get best bid prices for both outcomes.
        
        Returns:
            Tuple of (up_price, down_price).
        """
        up_price = await self.get_best_bid(up_token_id)
        down_price = await self.get_best_bid(down_token_id)
        return up_price, down_price
    
    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()


# Global instance
_clob_client: Optional[CLOBClient] = None


def get_clob_client() -> CLOBClient:
    """Get the global CLOB client."""
    global _clob_client
    if _clob_client is None:
        _clob_client = CLOBClient()
    return _clob_client
