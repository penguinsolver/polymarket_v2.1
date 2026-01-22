"""FastAPI backend for the multi-coin strategy tester v2.1."""
import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config, CoinType, COIN_DISPLAY_NAMES, UNDERVALUED_THRESHOLDS
from src.models import StrategyType
from src.market_tracker import get_market_tracker
from src.strategy_engine import get_strategy_engine
from src.clob_client import get_clob_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    tracker = get_market_tracker()
    for coin in CoinType:
        await tracker.refresh(coin)
    print("Market tracker initialized for all coins")
    yield
    engine = get_strategy_engine()
    await engine.stop_all()
    clob = get_clob_client()
    await clob.close()


app = FastAPI(title="Polymarket Strategy Tester v2.1", lifespan=lifespan)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ==================== PAGE ROUTES ====================

@app.get("/")
async def index():
    """Main dashboard."""
    return FileResponse(static_dir / "index.html")


@app.get("/btc")
async def btc_dashboard():
    """BTC dashboard."""
    return FileResponse(static_dir / "btc.html")


@app.get("/eth")
async def eth_dashboard():
    """ETH dashboard."""
    return FileResponse(static_dir / "eth.html")


@app.get("/sol")
async def sol_dashboard():
    """SOL dashboard."""
    return FileResponse(static_dir / "sol.html")


@app.get("/xrp")
async def xrp_dashboard():
    """XRP dashboard."""
    return FileResponse(static_dir / "xrp.html")


# ==================== API ENDPOINTS ====================

@app.get("/api/status")
async def get_status():
    """Get overall system status."""
    engine = get_strategy_engine()
    tracker = get_market_tracker()
    
    return {
        "engine": engine.get_status(),
        "markets": tracker.get_status(),
        "timestamp": time.time(),
    }


@app.get("/api/coins")
async def get_coins():
    """Get all coins with their status."""
    engine = get_strategy_engine()
    config = get_config()
    
    coins = []
    for coin in CoinType:
        coin_engine = engine.get_coin_engine(coin)
        coins.append({
            "type": coin.value,
            "display_name": COIN_DISPLAY_NAMES[coin],
            "enabled": config.is_coin_enabled(coin),
            "running": coin_engine.is_running,
            "orders_count": len(coin_engine.get_all_orders()),
            "trades_count": len(coin_engine.get_all_trades()),
        })
    
    return {"coins": coins}


@app.post("/api/coins/{coin}/start")
async def start_coin(coin: str):
    """Start a specific coin's bot."""
    try:
        coin_type = CoinType(coin.lower())
        engine = get_strategy_engine()
        await engine.start_coin(coin_type)
        return {"success": True, "message": f"{coin.upper()} bot started"}
    except ValueError:
        return JSONResponse({"error": f"Invalid coin: {coin}"}, status_code=400)


@app.post("/api/coins/{coin}/stop")
async def stop_coin(coin: str):
    """Stop a specific coin's bot."""
    try:
        coin_type = CoinType(coin.lower())
        engine = get_strategy_engine()
        await engine.stop_coin(coin_type)
        return {"success": True, "message": f"{coin.upper()} bot stopped"}
    except ValueError:
        return JSONResponse({"error": f"Invalid coin: {coin}"}, status_code=400)


@app.post("/api/start-all")
async def start_all():
    """Start all enabled bots."""
    engine = get_strategy_engine()
    await engine.start_all()
    return {"success": True, "message": "All bots started"}


@app.post("/api/stop-all")
async def stop_all():
    """Stop all bots."""
    engine = get_strategy_engine()
    await engine.stop_all()
    return {"success": True, "message": "All bots stopped"}


@app.get("/api/orders")
async def get_orders(
    coin: Optional[str] = Query(None),
    limit: Optional[int] = Query(None),
    offset: int = Query(0)
):
    """Get orders with pagination."""
    engine = get_strategy_engine()
    
    coin_type = None
    if coin:
        try:
            coin_type = CoinType(coin.lower())
        except ValueError:
            return JSONResponse({"error": f"Invalid coin: {coin}"}, status_code=400)
    
    orders = engine.get_all_orders(coin_type, limit, offset)
    total = len(engine.get_all_orders(coin_type))
    
    return {
        "orders": [o.to_dict() for o in orders],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/trades")
async def get_trades(
    coin: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    limit: Optional[int] = Query(None),
    offset: int = Query(0)
):
    """Get trades with pagination."""
    engine = get_strategy_engine()
    
    coin_type = None
    if coin:
        try:
            coin_type = CoinType(coin.lower())
        except ValueError:
            return JSONResponse({"error": f"Invalid coin: {coin}"}, status_code=400)
    
    strat_type = None
    if strategy:
        try:
            strat_type = StrategyType(strategy.lower())
        except ValueError:
            pass
    
    trades = engine.get_all_trades(coin_type, strat_type, limit, offset)
    total = len(engine.get_all_trades(coin_type, strat_type))
    
    return {
        "trades": [t.to_dict() for t in trades],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/metrics")
async def get_metrics(coin: Optional[str] = Query(None)):
    """Get metrics for strategies."""
    engine = get_strategy_engine()
    
    if coin:
        try:
            coin_type = CoinType(coin.lower())
            undervalued = engine.get_metrics(coin_type, StrategyType.UNDERVALUED)
            momentum = engine.get_metrics(coin_type, StrategyType.MOMENTUM)
            coin_engine = engine.get_coin_engine(coin_type)
            return {
                "coin": coin,
                "undervalued": undervalued.to_dict(),
                "momentum": momentum.to_dict(),
                "trading_volume": coin_engine.get_trading_volume(),
            }
        except ValueError:
            return JSONResponse({"error": f"Invalid coin: {coin}"}, status_code=400)
    
    # Aggregate across all coins
    return {
        "aggregate": engine.get_aggregate_metrics().to_dict(),
        "trading_volume": engine.get_total_trading_volume(),
    }


@app.get("/api/last-trades")
async def get_last_trades(
    limit: int = Query(20, ge=1, le=100),
    winning_only: bool = Query(False)
):
    """Get last N trades across all coins, optionally filtering by winning variants.
    
    A 'winning variant' is a strategy variant with net positive P&L.
    """
    engine = get_strategy_engine()
    trades = engine.get_last_trades(limit=limit, winning_only=winning_only)
    
    return {
        "trades": [t.to_dict() for t in trades],
        "count": len(trades),
        "winning_only": winning_only,
    }


@app.get("/api/variant-metrics")
async def get_variant_metrics(coin: Optional[str] = Query(None)):
    """Get metrics per strategy variant.
    
    Returns metrics for each variant (undervalued_49, undervalued_48, etc.).
    """
    engine = get_strategy_engine()
    
    if coin:
        try:
            coin_type = CoinType(coin.lower())
            coin_engine = engine.get_coin_engine(coin_type)
            metrics = coin_engine.get_all_variant_metrics()
            return {
                "coin": coin,
                "variants": {k: v.to_dict() for k, v in metrics.items()},
            }
        except ValueError:
            return JSONResponse({"error": f"Invalid coin: {coin}"}, status_code=400)
    
    # Aggregate across all coins
    metrics = engine.get_all_variant_metrics()
    return {
        "variants": {k: v.to_dict() for k, v in metrics.items()},
    }


@app.get("/api/markets")
async def get_markets(coin: Optional[str] = Query(None)):
    """Get market data."""
    tracker = get_market_tracker()
    
    if coin:
        try:
            coin_type = CoinType(coin.lower())
            await tracker.refresh(coin_type)
            return tracker.get_status(coin_type)
        except ValueError:
            return JSONResponse({"error": f"Invalid coin: {coin}"}, status_code=400)
    
    # Refresh and return all
    for c in CoinType:
        await tracker.refresh(c)
    return tracker.get_status()


@app.get("/api/prices/{coin}")
async def get_prices(coin: str):
    """Get current prices for a coin's t+1 market."""
    try:
        coin_type = CoinType(coin.lower())
    except ValueError:
        return JSONResponse({"error": f"Invalid coin: {coin}"}, status_code=400)
    
    tracker = get_market_tracker()
    await tracker.refresh(coin_type)
    
    t1 = tracker.get_t1_market(coin_type)
    if not t1:
        return {"error": f"No t+1 market found for {coin.upper()}"}
    
    clob = get_clob_client()
    up_price, down_price = await clob.get_prices(t1.up_token_id, t1.down_token_id)
    
    config = get_config()
    
    return {
        "coin": coin,
        "market_slug": t1.slug,
        "countdown": t1.countdown_to_active(),
        "up_price": up_price,
        "down_price": down_price,
        "sum_price": (up_price + down_price) if (up_price and down_price) else None,
        "undervalued_threshold": config.undervalued_threshold,
        "momentum_threshold": config.momentum_threshold,
    }


# ==================== EXPORT ENDPOINTS ====================

def format_orders_txt(orders) -> str:
    """Format orders as tab-separated text."""
    lines = ["Strategy\tCoin\tMarket\tSide\tPrice\tFilled/Size\tStatus\tCreated At"]
    for o in orders:
        created = datetime.fromtimestamp(o.created_at).strftime("%H:%M:%S")
        pct = int((o.filled_size / o.size) * 100) if o.size > 0 else 0
        lines.append(f"{o.strategy.value}\t{o.coin_type.value.upper()}\t{o.market_slug[-10:]}\t{o.outcome.value}\t${o.price:.2f}\t{int(o.filled_size)}/{int(o.size)} ({pct}%)\t{o.status.value.upper()}\t{created}")
    return "\n".join(lines)


def format_orders_md(orders) -> str:
    """Format orders as markdown."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# Open Orders Export",
        f"Generated: {now}",
        "",
        "| Strategy | Coin | Market | Side | Price | Filled/Size | Status | Created At |",
        "|----------|------|--------|------|-------|-------------|--------|------------|",
    ]
    
    for o in orders:
        created = datetime.fromtimestamp(o.created_at).strftime("%H:%M:%S")
        pct = int((o.filled_size / o.size) * 100) if o.size > 0 else 0
        lines.append(f"| {o.strategy.value} | {o.coin_type.value.upper()} | {o.market_slug[-10:]} | {o.outcome.value} | ${o.price:.2f} | {int(o.filled_size)}/{int(o.size)} ({pct}%) | {o.status.value.upper()} | {created} |")
    
    # Summary
    filled = sum(1 for o in orders if o.status.value == "filled")
    open_count = sum(1 for o in orders if o.status.value == "open")
    lines.extend([
        "",
        "## Summary",
        f"- Total Orders: {len(orders)}",
        f"- Filled: {filled}",
        f"- Open: {open_count}",
    ])
    
    return "\n".join(lines)


def format_trades_txt(trades) -> str:
    """Format trades as tab-separated text."""
    lines = ["Strategy\tCoin\tMarket\tOutcome\tEntry\tFilled\tFilled At\tResult\tP&L"]
    for t in trades:
        filled_at = datetime.fromtimestamp(t.entry_time).strftime("%H:%M:%S")
        lines.append(f"{t.strategy.value}\t{t.coin_type.value.upper()}\t{t.market_slug[-10:]}\t{t.outcome.value}\t${t.entry_price:.2f}\t{int(t.filled_size)}/{int(t.size)}\t{filled_at}\t{t.result.value.upper()}\t${t.pnl:.2f}")
    return "\n".join(lines)


def format_trades_md(trades) -> str:
    """Format trades as markdown."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# Recent Trades Export",
        f"Generated: {now}",
        "",
        "| Strategy | Coin | Market | Outcome | Entry | Filled | Filled At | Result | P&L |",
        "|----------|------|--------|---------|-------|--------|-----------|--------|-----|",
    ]
    
    for t in trades:
        filled_at = datetime.fromtimestamp(t.entry_time).strftime("%H:%M:%S")
        pnl_str = f"${t.pnl:.2f}"
        lines.append(f"| {t.strategy.value} | {t.coin_type.value.upper()} | {t.market_slug[-10:]} | {t.outcome.value} | ${t.entry_price:.2f} | {int(t.filled_size)}/{int(t.size)} | {filled_at} | {t.result.value.upper()} | {pnl_str} |")
    
    # Summary
    wins = sum(1 for t in trades if t.result.value == "win")
    losses = sum(1 for t in trades if t.result.value == "loss")
    pending = sum(1 for t in trades if t.result.value == "pending")
    total_pnl = sum(t.pnl for t in trades)
    
    lines.extend([
        "",
        "## Summary",
        f"- Total Trades: {len(trades)}",
        f"- Wins: {wins}",
        f"- Losses: {losses}",
        f"- Pending: {pending}",
        f"- Total P&L: ${total_pnl:.2f}",
    ])
    
    return "\n".join(lines)


@app.get("/api/export/orders")
async def export_orders(
    format: str = Query("txt"),
    coin: Optional[str] = Query(None)
):
    """Export orders as TXT or Markdown."""
    engine = get_strategy_engine()
    
    coin_type = None
    if coin:
        try:
            coin_type = CoinType(coin.lower())
        except ValueError:
            return JSONResponse({"error": f"Invalid coin: {coin}"}, status_code=400)
    
    orders = engine.get_all_orders(coin_type)
    
    if format.lower() == "md":
        content = format_orders_md(orders)
        filename = f"orders_export_{coin or 'all'}.md"
        media_type = "text/markdown"
    else:
        content = format_orders_txt(orders)
        filename = f"orders_export_{coin or 'all'}.txt"
        media_type = "text/plain"
    
    return PlainTextResponse(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/api/export/trades")
async def export_trades(
    format: str = Query("txt"),
    coin: Optional[str] = Query(None)
):
    """Export trades as TXT or Markdown."""
    engine = get_strategy_engine()
    
    coin_type = None
    if coin:
        try:
            coin_type = CoinType(coin.lower())
        except ValueError:
            return JSONResponse({"error": f"Invalid coin: {coin}"}, status_code=400)
    
    trades = engine.get_all_trades(coin_type)
    
    if format.lower() == "md":
        content = format_trades_md(trades)
        filename = f"trades_export_{coin or 'all'}.md"
        media_type = "text/markdown"
    else:
        content = format_trades_txt(trades)
        filename = f"trades_export_{coin or 'all'}.txt"
        media_type = "text/plain"
    
    return PlainTextResponse(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ==================== WEBSOCKET ====================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time updates."""
    await websocket.accept()
    
    try:
        while True:
            engine = get_strategy_engine()
            tracker = get_market_tracker()
            
            # Get prices for all coins
            prices = {}
            for coin in CoinType:
                t1 = tracker.get_t1_market(coin)
                if t1:
                    clob = get_clob_client()
                    up_price, down_price = await clob.get_prices(
                        t1.up_token_id, t1.down_token_id
                    )
                    prices[coin.value] = {
                        "up": up_price,
                        "down": down_price,
                        "sum": (up_price + down_price) if (up_price and down_price) else None,
                        "countdown": t1.countdown_to_active(),
                    }
            
            # Get last trades for dashboard widget
            last_trades = engine.get_last_trades(limit=10, winning_only=False)
            
            state = {
                "timestamp": time.time(),
                "engine": engine.get_status(),
                "markets": tracker.get_status(),
                "prices": prices,
                "aggregate": engine.get_aggregate_metrics().to_dict(),
                "variant_metrics": {k: v.to_dict() for k, v in engine.get_all_variant_metrics().items()},
                "trading_volume": engine.get_total_trading_volume(),
                "last_trades": [t.to_dict() for t in last_trades],
            }
            
            await websocket.send_json(state)
            await asyncio.sleep(2)
            
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/{coin}")
async def coin_websocket_endpoint(websocket: WebSocket, coin: str):
    """WebSocket for coin-specific updates."""
    try:
        coin_type = CoinType(coin.lower())
    except ValueError:
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    
    try:
        while True:
            engine = get_strategy_engine()
            tracker = get_market_tracker()
            coin_engine = engine.get_coin_engine(coin_type)
            
            # Get prices
            t1 = tracker.get_t1_market(coin_type)
            prices = None
            if t1:
                clob = get_clob_client()
                up_price, down_price = await clob.get_prices(
                    t1.up_token_id, t1.down_token_id
                )
                prices = {
                    "up": up_price,
                    "down": down_price,
                    "sum": (up_price + down_price) if (up_price and down_price) else None,
                }
            
            state = {
                "timestamp": time.time(),
                "coin": coin_type.value,
                "engine": coin_engine.get_status(),
                "markets": tracker.get_status(coin_type),
                "prices": prices,
                "metrics": {
                    "undervalued": coin_engine.get_metrics(StrategyType.UNDERVALUED).to_dict(),
                    "momentum": coin_engine.get_metrics(StrategyType.MOMENTUM).to_dict(),
                },
                "variant_metrics": {k: v.to_dict() for k, v in coin_engine.get_all_variant_metrics().items()},
                "trading_volume": coin_engine.get_trading_volume(),
                "orders": [o.to_dict() for o in coin_engine.get_orders(limit=8)],
                "orders_total": len(coin_engine.get_all_orders()),
                "trades": [t.to_dict() for t in coin_engine.get_trades(limit=8)],
                "trades_total": len(coin_engine.get_all_trades()),
            }
            
            await websocket.send_json(state)
            await asyncio.sleep(2)
            
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    print("Starting Polymarket Strategy Tester v2.1 on port 8002...")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
