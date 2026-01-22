"""Data models for multi-coin strategy testing."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import time
import uuid

from .config import CoinType


class StrategyType(Enum):
    """Trading strategy types."""
    UNDERVALUED = "undervalued"
    MOMENTUM = "momentum"


class Outcome(Enum):
    """Market outcome."""
    UP = "Up"
    DOWN = "Down"


class OrderStatus(Enum):
    """Order status."""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TradeResult(Enum):
    """Trade outcome result."""
    WIN = "win"
    LOSS = "loss"
    PENDING = "pending"


@dataclass
class MarketWindow:
    """A 15-minute market window."""
    slug: str
    coin_type: CoinType
    condition_id: str
    up_token_id: str
    down_token_id: str
    start_time: int
    end_time: int
    winner: Optional[Outcome] = None
    
    def countdown_to_active(self) -> int:
        """Seconds until market becomes active."""
        return max(0, self.start_time - int(time.time()))
    
    def countdown_to_end(self) -> int:
        """Seconds until market resolves."""
        return max(0, self.end_time - int(time.time()))
    
    def is_in_entry_window(self, entry_countdown: int) -> bool:
        """Check if we're in the entry window."""
        return self.countdown_to_active() <= entry_countdown
    
    def is_past_exit_point(self, exit_countdown: int) -> bool:
        """Check if we've passed the exit point."""
        return self.countdown_to_active() <= exit_countdown
    
    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "coin_type": self.coin_type.value,
            "condition_id": self.condition_id,
            "up_token_id": self.up_token_id,
            "down_token_id": self.down_token_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "countdown_to_active": self.countdown_to_active(),
            "countdown_to_end": self.countdown_to_end(),
        }


@dataclass
class PaperOrder:
    """A paper trading order."""
    id: str
    strategy: StrategyType
    coin_type: CoinType
    market_slug: str
    outcome: Outcome
    price: float
    size: float
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # v2.1 additions
    strategy_variant: str = ""  # e.g., "undervalued_48"
    market_start_time: int = 0  # Unix timestamp of market start
    limit_price: float = 0.0    # Target fill price for second-chance fill
    
    @classmethod
    def create(cls, strategy: StrategyType, coin_type: CoinType, market_slug: str,
               outcome: Outcome, price: float, size: float, 
               strategy_variant: str = "", market_start_time: int = 0) -> "PaperOrder":
        return cls(
            id=str(uuid.uuid4()),
            strategy=strategy,
            coin_type=coin_type,
            market_slug=market_slug,
            outcome=outcome,
            price=price,
            size=size,
            strategy_variant=strategy_variant or f"{strategy.value}",
            market_start_time=market_start_time,
            limit_price=price,
        )
    
    def fill(self, size: float) -> None:
        """Fill the order."""
        self.filled_size = min(self.size, self.filled_size + size)
        if self.filled_size >= self.size:
            self.status = OrderStatus.FILLED
        self.updated_at = time.time()
    
    def cancel(self) -> None:
        """Cancel the order."""
        self.status = OrderStatus.CANCELLED
        self.updated_at = time.time()
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "strategy": self.strategy.value,
            "strategy_variant": self.strategy_variant,
            "coin_type": self.coin_type.value,
            "market_slug": self.market_slug,
            "outcome": self.outcome.value,
            "price": self.price,
            "size": self.size,
            "status": self.status.value,
            "filled_size": self.filled_size,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "market_start_time": self.market_start_time,
            "limit_price": self.limit_price,
        }


@dataclass
class Trade:
    """A completed trade with resolution."""
    id: str
    strategy: StrategyType
    coin_type: CoinType
    market_slug: str
    outcome: Outcome
    entry_price: float
    size: float
    entry_time: float
    filled_size: float = 0.0
    resolution_time: Optional[float] = None
    result: TradeResult = TradeResult.PENDING
    pnl: float = 0.0
    # v2.1 additions
    strategy_variant: str = ""
    invested: float = 0.0  # size * entry_price
    market_start_time: int = 0
    
    @classmethod
    def from_order(cls, order: PaperOrder) -> "Trade":
        """Create a trade from a filled order."""
        return cls(
            id=str(uuid.uuid4()),
            strategy=order.strategy,
            coin_type=order.coin_type,
            market_slug=order.market_slug,
            outcome=order.outcome,
            entry_price=order.price,
            size=order.size,
            filled_size=order.filled_size,
            entry_time=order.updated_at,
            strategy_variant=order.strategy_variant,
            invested=order.filled_size * order.price,
            market_start_time=order.market_start_time,
        )
    
    def resolve(self, winning_outcome: Outcome) -> None:
        """Resolve the trade with the winning outcome."""
        self.resolution_time = time.time()
        if self.outcome == winning_outcome:
            self.pnl = self.size * (1.0 - self.entry_price)
            self.result = TradeResult.WIN
        else:
            self.pnl = -self.size * self.entry_price
            self.result = TradeResult.LOSS
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "strategy": self.strategy.value,
            "strategy_variant": self.strategy_variant,
            "coin_type": self.coin_type.value,
            "market_slug": self.market_slug,
            "outcome": self.outcome.value,
            "entry_price": self.entry_price,
            "size": self.size,
            "filled_size": self.filled_size,
            "entry_time": self.entry_time,
            "resolution_time": self.resolution_time,
            "result": self.result.value,
            "pnl": self.pnl,
            "invested": self.invested,
            "market_start_time": self.market_start_time,
        }


@dataclass
class StrategyMetrics:
    """Aggregated metrics for a strategy."""
    strategy: StrategyType
    coin_type: Optional[CoinType] = None  # None means aggregate across all coins
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    pending: int = 0
    total_pnl: float = 0.0
    total_invested: float = 0.0
    
    @property
    def win_rate(self) -> float:
        """Win rate as a percentage."""
        completed = self.wins + self.losses
        return (self.wins / completed * 100) if completed > 0 else 0.0
    
    @property
    def roi(self) -> float:
        """Return on investment as a percentage."""
        return (self.total_pnl / self.total_invested * 100) if self.total_invested > 0 else 0.0
    
    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy.value,
            "coin_type": self.coin_type.value if self.coin_type else None,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "pending": self.pending,
            "win_rate": round(self.win_rate, 1),
            "total_pnl": round(self.total_pnl, 2),
            "total_invested": round(self.total_invested, 2),
            "roi": round(self.roi, 1),
        }


@dataclass
class AggregateMetrics:
    """Combined metrics across all coins."""
    total_trades: int = 0
    total_pnl: float = 0.0
    total_invested: float = 0.0
    coins_running: int = 0
    coins_enabled: int = 0
    
    @property
    def roi(self) -> float:
        """Overall ROI."""
        return (self.total_pnl / self.total_invested * 100) if self.total_invested > 0 else 0.0
    
    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "total_pnl": round(self.total_pnl, 2),
            "total_invested": round(self.total_invested, 2),
            "roi": round(self.roi, 1),
            "coins_running": self.coins_running,
            "coins_enabled": self.coins_enabled,
        }


@dataclass
class VariantMetrics:
    """Metrics for a specific strategy variant (e.g., undervalued_48)."""
    variant_name: str  # e.g., "undervalued_48"
    threshold: float = 0.0  # e.g., 0.48
    coin_type: Optional[CoinType] = None
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    pending: int = 0
    total_pnl: float = 0.0
    total_invested: float = 0.0  # aka trading volume
    
    @property
    def win_rate(self) -> float:
        """Win rate as a percentage."""
        completed = self.wins + self.losses
        return (self.wins / completed * 100) if completed > 0 else 0.0
    
    @property
    def roi(self) -> float:
        """Return on investment as a percentage."""
        return (self.total_pnl / self.total_invested * 100) if self.total_invested > 0 else 0.0
    
    @property
    def trading_volume(self) -> float:
        """Alias for total_invested (trading volume = sum of invested amounts)."""
        return self.total_invested
    
    def to_dict(self) -> dict:
        return {
            "variant_name": self.variant_name,
            "threshold": self.threshold,
            "coin_type": self.coin_type.value if self.coin_type else None,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "pending": self.pending,
            "win_rate": round(self.win_rate, 1),
            "total_pnl": round(self.total_pnl, 2),
            "total_invested": round(self.total_invested, 2),
            "trading_volume": round(self.trading_volume, 2),
            "roi": round(self.roi, 1),
        }
