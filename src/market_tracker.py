"""Market tracker for discovering and monitoring 15-minute crypto markets."""
import httpx
import asyncio
import time
import logging
import json
from typing import Optional, List, Dict

from .config import get_config, CoinType, COIN_SLUG_PATTERNS
from .models import MarketWindow, Outcome

logger = logging.getLogger(__name__)

BUCKET_SIZE_SECONDS = 900  # 15 minutes


def get_bucket_start(now_epoch: int) -> int:
    """Get the start timestamp of the current 15-minute bucket."""
    return (now_epoch // BUCKET_SIZE_SECONDS) * BUCKET_SIZE_SECONDS


def generate_slug(coin_type: CoinType, bucket_start: int) -> str:
    """Generate the market slug for a given coin and bucket start time."""
    pattern = COIN_SLUG_PATTERNS[coin_type]
    return pattern.format(timestamp=bucket_start)


def get_expanded_slugs(coin_type: CoinType, now_epoch: int, back: int = 2, forward: int = 6) -> List[str]:
    """Get all slug candidates for expanded bucket range."""
    bucket_start = get_bucket_start(now_epoch)
    slugs = []
    for k in range(-back, forward + 1):
        bucket = bucket_start + BUCKET_SIZE_SECONDS * k
        slugs.append(generate_slug(coin_type, bucket))
    return slugs


def coin_type_from_slug(slug: str) -> Optional[CoinType]:
    """Determine coin type from a market slug."""
    slug_lower = slug.lower()
    if slug_lower.startswith("btc"):
        return CoinType.BTC
    elif slug_lower.startswith("eth"):
        return CoinType.ETH
    elif slug_lower.startswith("sol"):
        return CoinType.SOL
    elif slug_lower.startswith("xrp"):
        return CoinType.XRP
    return None


class MarketTracker:
    """Tracks Polymarket 15-minute crypto markets for all coins."""
    
    def __init__(self):
        self._config = get_config()
        self._client = httpx.AsyncClient(timeout=15.0)
        self._markets: Dict[CoinType, List[MarketWindow]] = {coin: [] for coin in CoinType}
        self._last_refresh: Dict[CoinType, float] = {coin: 0 for coin in CoinType}
        self._refresh_interval: float = 30.0
    
    async def refresh(self, coin_type: Optional[CoinType] = None) -> None:
        """Refresh market data for specified coin or all coins."""
        coins = [coin_type] if coin_type else list(CoinType)
        
        for coin in coins:
            await self._refresh_coin(coin)
    
    async def _refresh_coin(self, coin_type: CoinType) -> None:
        """Refresh markets for a specific coin."""
        now = time.time()
        if now - self._last_refresh[coin_type] < self._refresh_interval:
            return
        
        now_int = int(now)
        slugs = get_expanded_slugs(coin_type, now_int, back=2, forward=6)
        
        logger.info(f"[{coin_type.value}] Checking {len(slugs)} market slugs...")
        
        markets = []
        for slug in slugs:
            market = await self._fetch_market_by_slug(slug, coin_type)
            if market:
                markets.append(market)
        
        markets.sort(key=lambda m: m.start_time)
        self._markets[coin_type] = markets
        self._last_refresh[coin_type] = now
        logger.info(f"[{coin_type.value}] Refreshed: {len(markets)} markets found")
    
    async def _fetch_market_by_slug(self, slug: str, coin_type: CoinType) -> Optional[MarketWindow]:
        """Fetch a single market by its slug."""
        try:
            # Try events endpoint first
            url = f"{self._config.gamma_api_url}/events"
            params = {"slug": slug}
            response = await self._client.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    event = data[0]
                    event_markets = event.get("markets", [])
                    if event_markets:
                        market = event_markets[0]
                        return self._parse_market(market, slug, coin_type)
            
            # Fallback to markets endpoint
            url = f"{self._config.gamma_api_url}/markets"
            params = {"slug": slug}
            response = await self._client.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    return self._parse_market(data[0], slug, coin_type)
                    
        except Exception as e:
            logger.debug(f"Failed to fetch {slug}: {e}")
        
        return None
    
    def _parse_market(self, market: dict, slug: str, coin_type: CoinType) -> Optional[MarketWindow]:
        """Parse market data into MarketWindow."""
        try:
            tokens = market.get("tokens", [])
            clob_token_ids = market.get("clobTokenIds", [])
            outcomes = market.get("outcomes", [])
            outcome_prices = market.get("outcomePrices", [])
            
            # Handle JSON string format
            if isinstance(outcomes, str):
                try:
                    outcomes = json.loads(outcomes)
                except:
                    outcomes = []
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except:
                    clob_token_ids = []
            if isinstance(outcome_prices, str):
                try:
                    outcome_prices = json.loads(outcome_prices)
                except:
                    outcome_prices = []
            
            up_token_id = None
            down_token_id = None
            winner = None
            
            if tokens:
                up_token = next((t for t in tokens if t.get("outcome") == "Up"), None)
                down_token = next((t for t in tokens if t.get("outcome") == "Down"), None)
                if up_token:
                    up_token_id = up_token.get("token_id", "")
                if down_token:
                    down_token_id = down_token.get("token_id", "")
            elif clob_token_ids and outcomes:
                for i, outcome in enumerate(outcomes):
                    if i < len(clob_token_ids):
                        if outcome == "Up":
                            up_token_id = clob_token_ids[i]
                        elif outcome == "Down":
                            down_token_id = clob_token_ids[i]
            
            # Determine winner
            if outcome_prices and len(outcome_prices) >= 2 and outcomes and len(outcomes) >= 2:
                if str(outcome_prices[0]) == "1":
                    winner = Outcome.UP if outcomes[0] == "Up" else Outcome.DOWN
                elif str(outcome_prices[1]) == "1":
                    winner = Outcome.DOWN if outcomes[1] == "Down" else Outcome.UP
            
            if not up_token_id or not down_token_id:
                logger.debug(f"Missing tokens for {slug}")
                return None
            
            # Extract start_time from slug
            parts = slug.split("-")
            start_time = int(parts[-1])
            end_time = start_time + 900
            
            return MarketWindow(
                slug=slug,
                coin_type=coin_type,
                condition_id=market.get("conditionId", market.get("condition_id", "")),
                up_token_id=up_token_id,
                down_token_id=down_token_id,
                start_time=start_time,
                end_time=end_time,
                winner=winner
            )
        except Exception as e:
            logger.error(f"Error parsing market {slug}: {e}")
            return None
    
    def get_active_market(self, coin_type: CoinType) -> Optional[MarketWindow]:
        """Get the currently active market for a coin."""
        now = int(time.time())
        for market in self._markets.get(coin_type, []):
            if market.start_time <= now < market.end_time:
                return market
        return None
    
    def get_t1_market(self, coin_type: CoinType) -> Optional[MarketWindow]:
        """Get the t+1 market (next market to become active).
        
        IMPORTANT: Once countdown drops below 900 seconds (15:00), we skip that
        market and return the next one. This ensures we always track a market
        where the entry window (20:30 to 15:30) is still relevant.
        
        The switching logic:
        - countdown > 15:00 (900s): This is a valid T+1 to track
        - countdown <= 15:00 (900s): Entry window closed, skip to next market
        """
        now = int(time.time())
        for market in self._markets.get(coin_type, []):
            if market.start_time > now:
                countdown = market.start_time - now
                # Skip markets where countdown is below 15 minutes (entry window fully closed)
                # This ensures we switch to the next market for the next entry opportunity
                if countdown > 900:  # > 15:00
                    return market
        return None
    
    def get_t2_market(self, coin_type: CoinType) -> Optional[MarketWindow]:
        """Get the t+2 market."""
        t1 = self.get_t1_market(coin_type)
        if not t1:
            return None
        
        for market in self._markets.get(coin_type, []):
            if market.start_time > t1.start_time:
                return market
        return None
    
    def get_market_by_slug(self, slug: str) -> Optional[MarketWindow]:
        """Get a market by its slug."""
        for coin_markets in self._markets.values():
            for market in coin_markets:
                if market.slug == slug:
                    return market
        return None
    
    def get_status(self, coin_type: Optional[CoinType] = None) -> dict:
        """Get current market tracker status."""
        if coin_type:
            active = self.get_active_market(coin_type)
            t1 = self.get_t1_market(coin_type)
            t2 = self.get_t2_market(coin_type)
            
            return {
                "coin_type": coin_type.value,
                "active_market": active.to_dict() if active else None,
                "t1_market": t1.to_dict() if t1 else None,
                "t2_market": t2.to_dict() if t2 else None,
                "total_markets": len(self._markets.get(coin_type, [])),
                "last_refresh": self._last_refresh.get(coin_type, 0),
            }
        
        # Aggregate status for all coins
        return {
            coin.value: self.get_status(coin) for coin in CoinType
        }
    
    async def fetch_market_resolution(self, slug: str) -> Optional[Outcome]:
        """Fetch resolution for a specific market."""
        market = self.get_market_by_slug(slug)
        if market and market.winner:
            return market.winner
        
        coin_type = coin_type_from_slug(slug)
        if coin_type:
            fetched = await self._fetch_market_by_slug(slug, coin_type)
            if fetched:
                return fetched.winner
        return None
    
    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()


# Global instance
_tracker: Optional[MarketTracker] = None


def get_market_tracker() -> MarketTracker:
    """Get the global market tracker."""
    global _tracker
    if _tracker is None:
        _tracker = MarketTracker()
    return _tracker
