"""Strategy engine for managing multi-coin paper trading with strategy variants (v2.1)."""
import asyncio
import time
import random
import logging
from typing import Dict, List, Optional, Set

from .config import get_config, CoinType, UNDERVALUED_THRESHOLDS, MOMENTUM_THRESHOLDS
from .models import (
    StrategyType, Outcome, OrderStatus, TradeResult,
    MarketWindow, PaperOrder, Trade, StrategyMetrics, AggregateMetrics, VariantMetrics
)
from .market_tracker import get_market_tracker
from .clob_client import get_clob_client

logger = logging.getLogger(__name__)


def get_variant_name(strategy: StrategyType, threshold: float) -> str:
    """Generate variant name from strategy and threshold.
    
    Examples:
        - (UNDERVALUED, 0.48) -> 'undervalued_48'
        - (MOMENTUM, 0.51) -> 'momentum_51'
    """
    prefix = "undervalued" if strategy == StrategyType.UNDERVALUED else "momentum"
    return f"{prefix}_{int(threshold * 100)}"


def is_in_entry_window(countdown: int) -> bool:
    """Check if countdown is within valid entry window (20:30 to 15:30).
    
    Entry window is: 1230 seconds (20:30) down to 930 seconds (15:30).
    Returns True if countdown is within this range.
    """
    config = get_config()
    return config.entry_window_end <= countdown <= config.entry_window_start


def should_cancel_orders(countdown: int) -> bool:
    """Check if we should cancel unfilled orders (countdown <= 15:30)."""
    config = get_config()
    return countdown <= config.entry_window_end


class CoinEngine:
    """Engine for a single coin's trading with strategy variants."""
    
    def __init__(self, coin_type: CoinType):
        self.coin_type = coin_type
        self._config = get_config()
        self._orders: Dict[str, PaperOrder] = {}
        self._trades: List[Trade] = []
        self._processed_markets: Dict[str, Set[str]] = {}  # market_slug -> set of processed variants
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
                
                # Check entry window for new orders
                if is_in_entry_window(countdown):
                    await self._check_entry_conditions(t1, clob, countdown)
                    # Second-chance fill: monitor open orders
                    await self._check_second_chance_fills(t1, clob)
                else:
                    if countdown < self._config.entry_window_end:
                        logger.debug(f"[{self.coin_type.value}] Outside entry window (countdown={countdown}s < 15:30)")
                    elif countdown > self._config.entry_window_start:
                        logger.debug(f"[{self.coin_type.value}] Waiting for entry window (countdown={countdown}s > 20:30)")
                
                # Cancel unfilled orders when entry window closes
                if should_cancel_orders(countdown):
                    await self._cancel_unfilled_orders(t1.slug)
                
                await self._check_resolutions(tracker)
                await self._simulate_fills(clob)
                
                await asyncio.sleep(2)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.coin_type.value}] Error: {e}")
                await asyncio.sleep(5)
    
    async def _check_entry_conditions(self, market: MarketWindow, clob, countdown: int) -> None:
        """Check entry conditions for all strategy variants."""
        up_price, down_price = await clob.get_prices(
            market.up_token_id, 
            market.down_token_id
        )
        
        if up_price is None or down_price is None:
            logger.warning(f"[{self.coin_type.value}] No prices for {market.slug}")
            return
        
        logger.info(f"[{self.coin_type.value}] {market.slug} UP=${up_price:.2f}, DOWN=${down_price:.2f} (countdown={countdown}s)")
        
        # Initialize processed variants for this market
        if market.slug not in self._processed_markets:
            self._processed_markets[market.slug] = set()
        
        # Check all undervalued threshold variants
        for threshold in UNDERVALUED_THRESHOLDS:
            variant_name = get_variant_name(StrategyType.UNDERVALUED, threshold)
            
            # Skip if already processed this variant for this market
            if variant_name in self._processed_markets[market.slug]:
                continue
            
            # Check undervalued strategy for this threshold
            if up_price <= threshold:
                await self._place_order(
                    StrategyType.UNDERVALUED, market, Outcome.UP, up_price,
                    variant_name, threshold
                )
                self._processed_markets[market.slug].add(variant_name)
            elif down_price <= threshold:
                await self._place_order(
                    StrategyType.UNDERVALUED, market, Outcome.DOWN, down_price,
                    variant_name, threshold
                )
                self._processed_markets[market.slug].add(variant_name)
        
        # Check all momentum threshold variants
        for threshold in MOMENTUM_THRESHOLDS:
            variant_name = get_variant_name(StrategyType.MOMENTUM, threshold)
            
            # Skip if already processed this variant for this market
            if variant_name in self._processed_markets[market.slug]:
                continue
            
            # Check momentum strategy for this threshold
            if up_price >= threshold:
                await self._place_order(
                    StrategyType.MOMENTUM, market, Outcome.UP, up_price,
                    variant_name, threshold
                )
                self._processed_markets[market.slug].add(variant_name)
            elif down_price >= threshold:
                await self._place_order(
                    StrategyType.MOMENTUM, market, Outcome.DOWN, down_price,
                    variant_name, threshold
                )
                self._processed_markets[market.slug].add(variant_name)
    
    async def _place_order(self, strategy: StrategyType, market: MarketWindow,
                          outcome: Outcome, price: float, 
                          variant_name: str, threshold: float) -> None:
        """Place a paper order for a specific variant."""
        order = PaperOrder.create(
            strategy=strategy,
            coin_type=self.coin_type,
            market_slug=market.slug,
            outcome=outcome,
            price=price,
            size=self._config.order_size,
            strategy_variant=variant_name,
            market_start_time=market.start_time,
        )
        order.status = OrderStatus.OPEN
        self._orders[order.id] = order
        
        logger.info(f"📝 [{self.coin_type.value}] PLACED [{variant_name}] {outcome.value} @ ${price:.2f}")
    
    async def _check_second_chance_fills(self, market: MarketWindow, clob) -> None:
        """Check if price has moved through limit price for unfilled orders (second-chance fill)."""
        up_price, down_price = await clob.get_prices(
            market.up_token_id, 
            market.down_token_id
        )
        
        if up_price is None or down_price is None:
            return
        
        for order in list(self._orders.values()):
            if order.status != OrderStatus.OPEN:
                continue
            if order.filled_size > 0:
                continue
            if order.market_slug != market.slug:
                continue
            
            # Get current price for this outcome
            current_price = up_price if order.outcome == Outcome.UP else down_price
            
            # Second-chance fill: if current price <= limit price (for buys), fill the order
            if current_price <= order.limit_price:
                order.fill(order.size)
                trade = Trade.from_order(order)
                self._trades.append(trade)
                logger.info(f"💰 [{self.coin_type.value}] SECOND-CHANCE FILL [{order.strategy_variant}] {order.outcome.value} @ ${order.limit_price:.2f} (market=${current_price:.2f})")
    
    async def _cancel_unfilled_orders(self, market_slug: str) -> None:
        """Cancel all unfilled orders for a market when entry window closes."""
        for order in list(self._orders.values()):
            if order.status != OrderStatus.OPEN:
                continue
            if order.filled_size > 0:
                continue
            if order.market_slug != market_slug:
                continue
            
            order.cancel()
            logger.info(f"❌ [{self.coin_type.value}] CANCELLED [{order.strategy_variant}] {order.outcome.value} @ ${order.price:.2f} (entry window closed)")
    
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
                    logger.info(f"{emoji} [{self.coin_type.value}] {trade.strategy_variant} P&L=${trade.pnl:.2f}")
    
    async def _simulate_fills(self, clob) -> None:
        """Simulate order fills with probability."""
        for order in list(self._orders.values()):
            if order.status != OrderStatus.OPEN:
                continue
            if order.filled_size > 0:
                continue
            
            if random.random() < self._config.sim_fill_probability:
                order.fill(order.size)
                trade = Trade.from_order(order)
                self._trades.append(trade)
                logger.info(f"💰 [{self.coin_type.value}] FILLED [{order.strategy_variant}] {order.outcome.value}")
    
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
        """Calculate metrics for a strategy (aggregated across all variants)."""
        trades = [t for t in self._trades if t.strategy == strategy]
        
        metrics = StrategyMetrics(strategy=strategy, coin_type=self.coin_type)
        for trade in trades:
            metrics.total_trades += 1
            metrics.total_invested += trade.invested
            
            if trade.result == TradeResult.WIN:
                metrics.wins += 1
                metrics.total_pnl += trade.pnl
            elif trade.result == TradeResult.LOSS:
                metrics.losses += 1
                metrics.total_pnl += trade.pnl
            else:
                metrics.pending += 1
        
        return metrics
    
    def get_variant_metrics(self, variant_name: str) -> VariantMetrics:
        """Calculate metrics for a specific strategy variant."""
        trades = [t for t in self._trades if t.strategy_variant == variant_name]
        
        # Extract threshold from variant name (e.g., "undervalued_48" -> 0.48, "momentum_51" -> 0.51)
        threshold = 0.0
        if "_" in variant_name:
            try:
                threshold = int(variant_name.split("_")[1]) / 100
            except (ValueError, IndexError):
                pass
        
        metrics = VariantMetrics(
            variant_name=variant_name,
            threshold=threshold,
            coin_type=self.coin_type
        )
        
        for trade in trades:
            metrics.total_trades += 1
            metrics.total_invested += trade.invested
            
            if trade.result == TradeResult.WIN:
                metrics.wins += 1
                metrics.total_pnl += trade.pnl
            elif trade.result == TradeResult.LOSS:
                metrics.losses += 1
                metrics.total_pnl += trade.pnl
            else:
                metrics.pending += 1
        
        return metrics
    
    def get_all_variant_metrics(self) -> Dict[str, VariantMetrics]:
        """Get metrics for all 8 variants (4 undervalued + 4 momentum)."""
        metrics = {}
        
        # Add all undervalued variants
        for threshold in UNDERVALUED_THRESHOLDS:
            variant_name = get_variant_name(StrategyType.UNDERVALUED, threshold)
            metrics[variant_name] = self.get_variant_metrics(variant_name)
        
        # Add all momentum variants
        for threshold in MOMENTUM_THRESHOLDS:
            variant_name = get_variant_name(StrategyType.MOMENTUM, threshold)
            metrics[variant_name] = self.get_variant_metrics(variant_name)
        
        return metrics
    
    def get_trading_volume(self) -> float:
        """Get total trading volume (sum of invested amounts)."""
        return sum(t.invested for t in self._trades)
    
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
            "trading_volume": self.get_trading_volume(),
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
    
    def get_last_trades(self, limit: int = 20, winning_only: bool = False) -> List[Trade]:
        """Get last N trades across all coins, optionally filtering by winning variants."""
        all_trades = []
        
        # Get metrics per variant to determine winning variants
        variant_pnl = {}
        for engine in self._coin_engines.values():
            for variant_name, metrics in engine.get_all_variant_metrics().items():
                if variant_name not in variant_pnl:
                    variant_pnl[variant_name] = 0.0
                variant_pnl[variant_name] += metrics.total_pnl
        
        winning_variants = {v for v, pnl in variant_pnl.items() if pnl > 0}
        
        for engine in self._coin_engines.values():
            trades = engine.get_all_trades()
            if winning_only:
                trades = [t for t in trades if t.strategy_variant in winning_variants]
            all_trades.extend(trades)
        
        sorted_trades = sorted(all_trades, key=lambda t: t.entry_time, reverse=True)
        return sorted_trades[:limit]
    
    def get_metrics(self, coin_type: CoinType, strategy: StrategyType) -> StrategyMetrics:
        """Get metrics for a specific coin and strategy."""
        return self._coin_engines[coin_type].get_metrics(strategy)
    
    def get_all_variant_metrics(self) -> Dict[str, VariantMetrics]:
        """Get aggregated metrics for all variants across all coins."""
        aggregated = {}
        
        for engine in self._coin_engines.values():
            for variant_name, metrics in engine.get_all_variant_metrics().items():
                if variant_name not in aggregated:
                    aggregated[variant_name] = VariantMetrics(
                        variant_name=variant_name,
                        threshold=metrics.threshold,
                    )
                
                agg = aggregated[variant_name]
                agg.total_trades += metrics.total_trades
                agg.wins += metrics.wins
                agg.losses += metrics.losses
                agg.pending += metrics.pending
                agg.total_pnl += metrics.total_pnl
                agg.total_invested += metrics.total_invested
        
        return aggregated
    
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
    
    def get_total_trading_volume(self) -> float:
        """Get total trading volume across all coins."""
        return sum(engine.get_trading_volume() for engine in self._coin_engines.values())
    
    def get_status(self) -> dict:
        """Get full engine status."""
        return {
            "global_start_time": self._global_start_time,
            "coins": {
                coin.value: engine.get_status() 
                for coin, engine in self._coin_engines.items()
            },
            "config": {
                "undervalued_thresholds": UNDERVALUED_THRESHOLDS,
                "momentum_threshold": self._config.momentum_threshold,
                "order_size": self._config.order_size,
                "entry_window_start": self._config.entry_window_start,
                "entry_window_end": self._config.entry_window_end,
            },
            "aggregate": self.get_aggregate_metrics().to_dict(),
            "variant_metrics": {k: v.to_dict() for k, v in self.get_all_variant_metrics().items()},
            "trading_volume": self.get_total_trading_volume(),
        }


# Global instance
_engine: Optional[StrategyEngine] = None


def get_strategy_engine() -> StrategyEngine:
    """Get the global strategy engine."""
    global _engine
    if _engine is None:
        _engine = StrategyEngine()
    return _engine
