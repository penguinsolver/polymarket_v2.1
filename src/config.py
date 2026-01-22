"""Configuration management for multi-coin strategy tester."""
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv


class CoinType(Enum):
    """Supported cryptocurrency types."""
    BTC = "btc"
    ETH = "eth"
    SOL = "sol"
    XRP = "xrp"


# Slug patterns for each coin's 15-minute markets
COIN_SLUG_PATTERNS = {
    CoinType.BTC: "btc-updown-15m-{timestamp}",
    CoinType.ETH: "eth-updown-15m-{timestamp}",
    CoinType.SOL: "sol-updown-15m-{timestamp}",
    CoinType.XRP: "xrp-updown-15m-{timestamp}",
}

# Display names for coins
COIN_DISPLAY_NAMES = {
    CoinType.BTC: "Bitcoin",
    CoinType.ETH: "Ethereum",
    CoinType.SOL: "Solana",
    CoinType.XRP: "XRP",
}


@dataclass
class CoinConfig:
    """Configuration for a single coin."""
    coin_type: CoinType
    enabled: bool = True
    running: bool = False


# Strategy variant thresholds for undervalued strategy
UNDERVALUED_THRESHOLDS = [0.49, 0.48, 0.47, 0.46]

# Strategy variant thresholds for momentum strategy
MOMENTUM_THRESHOLDS = [0.51, 0.52, 0.53, 0.54]


@dataclass
class Config:
    """Application configuration."""
    
    # Strategy thresholds
    momentum_threshold: float = 0.52
    order_size: float = 10.0
    
    # Entry window timing (in seconds relative to market start countdown)
    # Orders allowed when countdown is between entry_window_start and entry_window_end
    entry_window_start: int = 1230   # 20 minutes 30 seconds = 20:30
    entry_window_end: int = 930      # 15 minutes 30 seconds = 15:30
    
    # Paper trading
    paper_mode: bool = True
    sim_fill_probability: float = 0.7
    
    # Per-coin settings
    coin_configs: Dict[CoinType, CoinConfig] = field(default_factory=dict)
    
    # Logging
    log_level: str = "INFO"
    
    # API URLs
    gamma_api_url: str = "https://gamma-api.polymarket.com"
    clob_api_url: str = "https://clob.polymarket.com"
    
    def __post_init__(self):
        """Initialize coin configs if not provided."""
        if not self.coin_configs:
            for coin in CoinType:
                self.coin_configs[coin] = CoinConfig(coin_type=coin, enabled=True)
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load config from environment variables."""
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        
        config = cls(
            momentum_threshold=float(os.getenv("MOMENTUM_THRESHOLD", "0.52")),
            order_size=float(os.getenv("ORDER_SIZE_SHARES", "10")),
            entry_window_start=int(os.getenv("ENTRY_WINDOW_START", "1230")),
            entry_window_end=int(os.getenv("ENTRY_WINDOW_END", "930")),
            paper_mode=os.getenv("PAPER_MODE", "true").lower() == "true",
            sim_fill_probability=float(os.getenv("SIM_FILL_PROBABILITY", "0.7")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
        
        # Set coin enables from environment
        for coin in CoinType:
            env_key = f"ENABLE_{coin.value.upper()}"
            enabled = os.getenv(env_key, "true").lower() == "true"
            config.coin_configs[coin] = CoinConfig(coin_type=coin, enabled=enabled)
        
        return config
    
    def is_coin_enabled(self, coin: CoinType) -> bool:
        """Check if a coin is enabled."""
        return self.coin_configs.get(coin, CoinConfig(coin_type=coin)).enabled
    
    def is_coin_running(self, coin: CoinType) -> bool:
        """Check if a coin's bot is running."""
        return self.coin_configs.get(coin, CoinConfig(coin_type=coin)).running
    
    def set_coin_running(self, coin: CoinType, running: bool) -> None:
        """Set a coin's running state."""
        if coin in self.coin_configs:
            self.coin_configs[coin].running = running


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config
