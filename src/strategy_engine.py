"""Strategy engine for managing multi-coin dual-strategy paper trading."""
import asyncio
import time
import random
import logging
from typing import Dict, List, Optional, Set

from .config import get_config, CoinType
from .models import (
    StrategyType, Outcome, OrderStatus, TradeResult,
    MarketWindow, PaperOrder, Trade, StrategyMetrics, AggregateMetrics
)
from .market_tracker import get_market_tracker
from .clob_client import get_clob_client

logger = logging.getLogger(__name__)


class CoinEngine:
    """Engine for a single coin's trading."""
    
    def __init__(self, coin_type: CoinType):
        self.coin_type = coin_type
        self._config = get_config()
        self._orders: Dict[str, PaperOrder] = {}
        self._trades: List[Trade] = []
        self._processed_markets: Set[str] = set()
        self._running: bool = False
        self._loop_task: Optional[asyncio.Task] = None
        self._start_time: Optional[float] = None
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    async def start(self) -> None:
        """Start the engine for this coin."""
        if self._running:
            return
        
        self._running = True
        self._start_time = time.time()
        self._config.set_coin_running(self.coin_type, True)
        self._loop_task = asyncio.create_task(self._run_loop())
        logger.info(f"[{self.coin_type.value}] Engine started")
    
    async def stop(self) -> None:
        """Stop the engine."""
        self._running = False
        self._config.set_coin_running(self.coin_type, False)
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info(f"[{self.coin_type.value}] Engine stopped")
    
    async def _run_loop(self) -> None:
        """Main trading loop."""
        tracker = get_market_tracker()
        clob = get_clob_client()
        
        while self._running:
            try:
                await tracker.refresh(self.coin_type)
                
                t1 = tracker.get_t1_market(self.coin_type)
                if not t1:
                    await asyncio.sleep(5)
                    continue
                
                countdown = t1.countdown_to_active()
                
                logger.debug(f"[{self.coin_type.value}] t1={t1.slug}, countdown={countdown}s")
                
                if (t1.slug not in self._processed_markets and 
                    countdown <= self._config.entry_countdown and
                    countdown > 0):
                    await self._check_entry_conditions(t1, clob)
                
                await self._check_resolutions(tracker)
                await self._simulate_fills(clob)
                
                await asyncio.sleep(2)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.coin_type.value}] Error: {e}")
                await asyncio.sleep(5)
    
    async def _check_entry_conditions(self, market: MarketWindow, clob) -> None:
        """Check entry conditions for strategies."""
        up_price, down_price = await clob.get_prices(
            market.up_token_id, 
            market.down_token_id
        )
        
        if up_price is None or down_price is None:
            logger.warning(f"[{self.coin_type.value}] No prices for {market.slug}")
            return
        
        logger.info(f"[{self.coin_type.value}] {market.slug} UP=${up_price:.2f}, DOWN=${down_price:.2f}")
        
        # Undervalued strategy
        if up_price <= self._config.undervalued_threshold:
            await self._place_order(StrategyType.UNDERVALUED, market, Outcome.UP, up_price)
        elif down_price <= self._config.undervalued_threshold:
            await self._place_order(StrategyType.UNDERVALUED, market, Outcome.DOWN, down_price)
        
        # Momentum strategy
        if up_price >= self._config.momentum_threshold:
            await self._place_order(StrategyType.MOMENTUM, market, Outcome.UP, up_price)
        elif down_price >= self._config.momentum_threshold:
            await self._place_order(StrategyType.MOMENTUM, market, Outcome.DOWN, down_price)
        
        self._processed_markets.add(market.slug)
    
    async def _place_order(self, strategy: StrategyType, market: MarketWindow,
                          outcome: Outcome, price: float) -> None:
        """Place a paper order."""
        order = PaperOrder.create(
            strategy=strategy,
            coin_type=self.coin_type,
            market_slug=market.slug,
            outcome=outcome,
            price=price,
            size=self._config.order_size,
        )
        order.status = OrderStatus.OPEN
        self._orders[order.id] = order
        
        logger.info(f"📝 [{self.coin_type.value}] PLACED [{strategy.value}] {outcome.value} @ ${price:.2f}")
    
    async def _check_resolutions(self, tracker) -> None:
        """Check for resolved markets."""
        now = int(time.time())
        
        if not hasattr(self, '_resolution_check_times'):
            self._resolution_check_times = {}
        
        for trade in self._trades:
            if trade.result != TradeResult.PENDING:
                continue
            
            market = tracker.get_market_by_slug(trade.market_slug)
            
            if market:
                end_time = market.end_time
            else:
                try:
                    parts = trade.market_slug.split("-")
                    start_time = int(parts[-1])
                    end_time = start_time + 900
                except (ValueError, IndexError):
                    continue
            
            if now > end_time:
                last_check = self._resolution_check_times.get(trade.market_slug, 0)
                if now - last_check < 15:
                    continue
                
                self._resolution_check_times[trade.market_slug] = now
                winning_outcome = await tracker.fetch_market_resolution(trade.market_slug)
                
                if winning_outcome:
                    trade.resolve(winning_outcome)
                    emoji = "✅" if trade.result == TradeResult.WIN else "❌"
                    logger.info(f"{emoji} [{self.coin_type.value}] {trade.strategy.value} P&L=${trade.pnl:.2f}")
    
    async def _simulate_fills(self, clob) -> None:
        """Simulate order fills."""
        for order in list(self._orders.values()):
            if order.status != OrderStatus.OPEN:
                continue
            if order.filled_size > 0:
                continue
            
            if random.random() < self._config.sim_fill_probability:
                order.fill(order.size)
                trade = Trade.from_order(order)
                self._trades.append(trade)
                logger.info(f"💰 [{self.coin_type.value}] FILLED {order.strategy.value} {order.outcome.value}")
    
    def get_orders(self, limit: Optional[int] = None, offset: int = 0) -> List[PaperOrder]:
        """Get orders sorted by created_at descending."""
        sorted_orders = sorted(self._orders.values(), key=lambda o: o.created_at, reverse=True)
        if limit:
            return sorted_orders[offset:offset + limit]
        return sorted_orders[offset:]
    
    def get_all_orders(self) -> List[PaperOrder]:
        """Get all orders sorted by created_at descending."""
        return sorted(self._orders.values(), key=lambda o: o.created_at, reverse=True)
    
    def get_trades(self, strategy: Optional[StrategyType] = None, 
                   limit: Optional[int] = None, offset: int = 0) -> List[Trade]:
        """Get trades sorted by entry_time descending."""
        trades = self._trades
        if strategy:
            trades = [t for t in trades if t.strategy == strategy]
        
        sorted_trades = sorted(trades, key=lambda t: t.entry_time, reverse=True)
        if limit:
            return sorted_trades[offset:offset + limit]
        return sorted_trades[offset:]
    
    def get_all_trades(self) -> List[Trade]:
        """Get all trades sorted by entry_time descending."""
        return sorted(self._trades, key=lambda t: t.entry_time, reverse=True)
    
    def get_metrics(self, strategy: StrategyType) -> StrategyMetrics:
        """Calculate metrics for a strategy."""
        trades = [t for t in self._trades if t.strategy == strategy]
        
        metrics = StrategyMetrics(strategy=strategy, coin_type=self.coin_type)
        for trade in trades:
            metrics.total_trades += 1
            metrics.total_invested += trade.size * trade.entry_price
            
            if trade.result == TradeResult.WIN:
                metrics.wins += 1
                metrics.total_pnl += trade.pnl
            elif trade.result == TradeResult.LOSS:
                metrics.losses += 1
                metrics.total_pnl += trade.pnl
            else:
                metrics.pending += 1
        
        return metrics
    
    def get_status(self) -> dict:
        """Get engine status."""
        return {
            "coin_type": self.coin_type.value,
            "is_running": self._running,
            "start_time": self._start_time,
            "orders_count": len(self._orders),
            "trades_count": len(self._trades),
            "processed_markets": len(self._processed_markets),
            "pnl": sum(t.pnl for t in self._trades),
        }


class StrategyEngine:
    """Main engine managing all coin engines."""
    
    def __init__(self):
        self._config = get_config()
        self._coin_engines: Dict[CoinType, CoinEngine] = {
            coin: CoinEngine(coin) for coin in CoinType
        }
        self._global_start_time: Optional[float] = None
    
    async def start_coin(self, coin_type: CoinType) -> None:
        """Start a specific coin's engine."""
        await self._coin_engines[coin_type].start()
        if self._global_start_time is None:
            self._global_start_time = time.time()
    
    async def stop_coin(self, coin_type: CoinType) -> None:
        """Stop a specific coin's engine."""
        await self._coin_engines[coin_type].stop()
    
    async def start_all(self) -> None:
        """Start all enabled coin engines."""
        self._global_start_time = time.time()
        for coin in CoinType:
            if self._config.is_coin_enabled(coin):
                await self._coin_engines[coin].start()
    
    async def stop_all(self) -> None:
        """Stop all coin engines."""
        for engine in self._coin_engines.values():
            await engine.stop()
    
    def get_coin_engine(self, coin_type: CoinType) -> CoinEngine:
        """Get a specific coin engine."""
        return self._coin_engines[coin_type]
    
    def get_all_orders(self, coin_type: Optional[CoinType] = None,
                       limit: Optional[int] = None, offset: int = 0) -> List[PaperOrder]:
        """Get orders across coins."""
        if coin_type:
            return self._coin_engines[coin_type].get_orders(limit, offset)
        
        all_orders = []
        for engine in self._coin_engines.values():
            all_orders.extend(engine.get_all_orders())
        
        sorted_orders = sorted(all_orders, key=lambda o: o.created_at, reverse=True)
        if limit:
            return sorted_orders[offset:offset + limit]
        return sorted_orders[offset:]
    
    def get_all_trades(self, coin_type: Optional[CoinType] = None,
                       strategy: Optional[StrategyType] = None,
                       limit: Optional[int] = None, offset: int = 0) -> List[Trade]:
        """Get trades across coins."""
        if coin_type:
            return self._coin_engines[coin_type].get_trades(strategy, limit, offset)
        
        all_trades = []
        for engine in self._coin_engines.values():
            trades = engine.get_all_trades()
            if strategy:
                trades = [t for t in trades if t.strategy == strategy]
            all_trades.extend(trades)
        
        sorted_trades = sorted(all_trades, key=lambda t: t.entry_time, reverse=True)
        if limit:
            return sorted_trades[offset:offset + limit]
        return sorted_trades[offset:]
    
    def get_metrics(self, coin_type: CoinType, strategy: StrategyType) -> StrategyMetrics:
        """Get metrics for a specific coin and strategy."""
        return self._coin_engines[coin_type].get_metrics(strategy)
    
    def get_aggregate_metrics(self) -> AggregateMetrics:
        """Get aggregate metrics across all coins."""
        metrics = AggregateMetrics()
        
        for coin, engine in self._coin_engines.items():
            for strategy in StrategyType:
                strat_metrics = engine.get_metrics(strategy)
                metrics.total_trades += strat_metrics.total_trades
                metrics.total_pnl += strat_metrics.total_pnl
                metrics.total_invested += strat_metrics.total_invested
            
            if engine.is_running:
                metrics.coins_running += 1
            if self._config.is_coin_enabled(coin):
                metrics.coins_enabled += 1
        
        return metrics
    
    def get_status(self) -> dict:
        """Get full engine status."""
        return {
            "global_start_time": self._global_start_time,
            "coins": {
                coin.value: engine.get_status() 
                for coin, engine in self._coin_engines.items()
            },
            "config": {
                "undervalued_threshold": self._config.undervalued_threshold,
                "momentum_threshold": self._config.momentum_threshold,
                "order_size": self._config.order_size,
            },
            "aggregate": self.get_aggregate_metrics().to_dict(),
        }


# Global instance
_engine: Optional[StrategyEngine] = None


def get_strategy_engine() -> StrategyEngine:
    """Get the global strategy engine."""
    global _engine
    if _engine is None:
        _engine = StrategyEngine()
    return _engine
