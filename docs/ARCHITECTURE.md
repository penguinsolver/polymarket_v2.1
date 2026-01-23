# Polymarket Strategy Tester v2.1 - Technical Documentation

## Overview

This is a **paper trading bot** for Polymarket's 15-minute cryptocurrency up/down prediction markets. It tracks BTC, ETH, SOL, and XRP markets, places simulated limit orders based on configurable strategies, and measures performance across multiple strategy variants.

> **Paper Trading**: No real money is used. Orders are simulated locally to test strategies before deploying real capital.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              WEB LAYER (FastAPI)                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ index.html  │  │  btc.html   │  │  eth.html   │  │  WebSocket Handler  │ │
│  │ (Dashboard) │  │ (BTC Page)  │  │ (ETH Page)  │  │  /ws, /ws/{coin}    │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│                              ▲                              │                │
│                              │ REST API                     │ Real-time      │
│                              │                              ▼                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                          API Endpoints (api.py)                         │ │
│  │  /api/status, /api/coins/{coin}/start, /api/export/orders, etc.        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CORE ENGINE LAYER                                  │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     StrategyEngine (strategy_engine.py)               │   │
│  │  - Manages 4 CoinEngines (BTC, ETH, SOL, XRP)                        │   │
│  │  - Aggregates metrics across all coins                                │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                       │                                      │
│         ┌─────────────────────────────┼─────────────────────────────┐       │
│         ▼                             ▼                             ▼       │
│  ┌─────────────┐            ┌─────────────┐              ┌─────────────┐    │
│  │ CoinEngine  │            │ CoinEngine  │              │ CoinEngine  │    │
│  │    (BTC)    │            │    (ETH)    │      ...     │    (XRP)    │    │
│  └─────────────┘            └─────────────┘              └─────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            DATA LAYER                                        │
│  ┌────────────────────────────┐     ┌────────────────────────────────────┐  │
│  │    MarketTracker           │     │         CLOBClient                 │  │
│  │   (market_tracker.py)      │     │       (clob_client.py)             │  │
│  └────────────────────────────┘     └────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL APIs (Polymarket)                            │
│  ┌────────────────────────────┐     ┌────────────────────────────────────┐  │
│  │  Gamma API                 │     │  CLOB API                          │  │
│  │  gamma-api.polymarket.com  │     │  clob.polymarket.com               │  │
│  └────────────────────────────┘     └────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Code Structure

```
polymarket_strategy_tester_v2.1/
├── src/
│   ├── config.py           # Configuration & coin types
│   ├── models.py           # Data models (Order, Trade, Market)
│   ├── market_tracker.py   # Polymarket API integration
│   ├── strategy_engine.py  # Core trading logic
│   └── clob_client.py      # Price fetching
├── web/
│   ├── api.py              # FastAPI backend
│   └── static/
│       ├── index.html      # Main dashboard
│       ├── btc.html        # BTC-specific dashboard
│       ├── eth.html        # ETH-specific dashboard
│       ├── sol.html        # SOL-specific dashboard
│       ├── xrp.html        # XRP-specific dashboard
│       └── style.css       # Styling
├── docs/
│   ├── ARCHITECTURE.md     # This file
│   ├── ASSUMPTIONS.md      # Design assumptions
│   └── DATA_MODEL.md       # Data structures
├── .env.example            # Environment template
├── pyproject.toml          # Python package config
└── README.md               # Quick start guide
```

---

## Trading Strategy

### Market Type: 15-Minute Up/Down Predictions

Polymarket offers binary prediction markets for whether a cryptocurrency's price will go UP or DOWN over 15-minute windows.

### Strategy Variants (8 Total)

| Strategy | Variant | Threshold | Description |
|----------|---------|-----------|-------------|
| Undervalued | `undervalued_49` | ≤$0.49 | Most aggressive |
| Undervalued | `undervalued_48` | ≤$0.48 | Default |
| Undervalued | `undervalued_47` | ≤$0.47 | Moderate |
| Undervalued | `undervalued_46` | ≤$0.46 | Most conservative |
| Momentum | `momentum_51` | ≥$0.51 | Light conviction |
| Momentum | `momentum_52` | ≥$0.52 | Moderate conviction |
| Momentum | `momentum_53` | ≥$0.53 | Strong conviction |
| Momentum | `momentum_54` | ≥$0.54 | Very strong conviction |

Each variant tracks independent statistics (trades, wins, P&L, ROI).

---

## Timing Logic

### Entry Window System

```
Market Timeline:
╔══════════════════════════════════════════════════════════════════════════╗
║  T-30:00  │  T-20:30  │  T-15:30  │  T-15:00  │  T-0:00   │  T+15:00   ║
║           │           │           │           │           │            ║
║  WAITING  │◄─────────►│  CANCEL   │  SWITCH   │  ACTIVE   │  RESOLVED  ║
║           │  ENTRY    │  UNFILLED │  TO NEXT  │  MARKET   │  (WIN/LOSS)║
║           │  WINDOW   │  ORDERS   │  MARKET   │           │            ║
╚══════════════════════════════════════════════════════════════════════════╝
```

| Countdown | Status | Bot Action |
|-----------|--------|------------|
| > 20:30 | Waiting | Monitor market, no orders |
| 20:30 → 15:30 | **Entry Window** | Place limit orders if price meets threshold |
| ≤ 15:30 | Window Closed | Cancel unfilled orders |
| < 15:00 | Switch Market | Move to next T+1 market |
| 0:00 | Market Active | Wait for resolution |
| After end | Resolution | Fetch result, update P&L |

**Why this window?**
- Markets become more liquid as they approach activation
- Too early = poor price discovery, spreads may be wide
- Too late = risk of not filling before market starts

---

## Order Lifecycle

```
                    ┌──────────────────┐
                    │     CREATED      │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │      OPEN        │◄─────────────────┐
                    │  (limit order)   │                  │
                    └────────┬─────────┘                  │
                             │                            │
              ┌──────────────┼──────────────┐             │
              │              │              │             │
              ▼              ▼              ▼             │
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐   │
    │   FILLED     │ │  CANCELLED   │ │  PARTIAL     │───┘
    └──────┬───────┘ └──────────────┘ └──────────────┘
           │
           ▼
    ┌──────────────┐
    │    TRADE     │
    │   (PENDING)  │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐     ┌──────────────┐
    │     WIN      │ OR  │     LOSS     │
    └──────────────┘     └──────────────┘
```

### Fill Simulation

```python
SIM_FILL_PROBABILITY = 0.7  # 70% chance of fill
```

Orders that don't fill immediately remain **OPEN** during the entry window for second-chance fill if price moves favorably.

---

## Key Components

### 1. StrategyEngine & CoinEngine (`strategy_engine.py`)

- **CoinEngine**: Manages trading for a single coin
  - Runs async loop checking entry conditions every 2 seconds
  - Handles order placement, fill simulation, trade resolution
  - Tracks per-variant metrics independently

- **StrategyEngine**: Orchestrates all CoinEngine instances
  - Provides aggregate metrics across all coins
  - Manages global start/stop operations

### 2. MarketTracker (`market_tracker.py`)

- Fetches markets from Polymarket Gamma API
- `get_t1_market()`: Returns next tradeable market
- `fetch_market_resolution()`: Gets WIN/LOSS outcome after market ends
- Handles edge cases: no markets, gaps between markets, API timeouts

### 3. CLOBClient (`clob_client.py`)

- Fetches live prices from Polymarket CLOB API
- Returns best bid prices for UP and DOWN tokens

### 4. Web API (`api.py`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Main dashboard |
| `/{coin}` | GET | Coin-specific dashboard |
| `/api/coins/{coin}/start` | POST | Start bot for coin |
| `/api/coins/{coin}/stop` | POST | Stop bot for coin |
| `/api/export/orders` | GET | Export orders as TXT/MD |
| `/api/export/trades` | GET | Export trades as TXT/MD |
| `/ws/{coin}` | WebSocket | Real-time updates |

---

## Data Models

### PaperOrder
| Field | Type | Description |
|-------|------|-------------|
| `id` | string | UUID |
| `strategy` | StrategyType | UNDERVALUED or MOMENTUM |
| `strategy_variant` | string | e.g., "undervalued_48" |
| `coin_type` | CoinType | BTC, ETH, SOL, or XRP |
| `market_slug` | string | Target market |
| `outcome` | Outcome | UP or DOWN |
| `price` | float | Order price |
| `size` | float | Order size (shares) |
| `status` | OrderStatus | OPEN, FILLED, CANCELLED |

### Trade
| Field | Type | Description |
|-------|------|-------------|
| (Same as PaperOrder, plus:) | | |
| `result` | TradeResult | PENDING, WIN, LOSS |
| `pnl` | float | Profit/loss in dollars |
| `entry_time` | float | When filled |

### VariantMetrics
| Field | Type | Description |
|-------|------|-------------|
| `variant_name` | string | e.g., "undervalued_48" |
| `total_trades` | int | Total trades |
| `wins` | int | Winning trades |
| `losses` | int | Losing trades |
| `total_pnl` | float | Net P&L |
| `win_rate` | float | Wins / (wins + losses) × 100 |
| `roi` | float | P&L / invested × 100 |

---

## P&L Calculation

```python
# WIN: Predicted outcome matches actual
pnl = size * (1.0 - entry_price)

# LOSS: Predicted outcome differs
pnl = -size * entry_price
```

**Example** (10 shares, entry $0.48):
- WIN: 10 × (1.0 - 0.48) = **+$5.20**
- LOSS: -10 × 0.48 = **-$4.80**

---

## Configuration (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `UNDERVALUED_THRESHOLD` | 0.48 | Base threshold |
| `MOMENTUM_THRESHOLD` | 0.52 | Base threshold |
| `ORDER_SIZE_SHARES` | 10 | Shares per order |
| `ENTRY_WINDOW_START` | 1230 | 20:30 in seconds |
| `ENTRY_WINDOW_END` | 930 | 15:30 in seconds |
| `SIM_FILL_PROBABILITY` | 0.7 | Fill probability |

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| API timeout | Log error, wait 5s, retry |
| No markets found | Wait 5s, retry |
| Market gap (2+ hours) | Display next available market |
| WebSocket disconnect | Auto-reconnect after 3s |
| Resolution fetch fails | Retry on next poll cycle (15s) |

---

## Dashboard Visualizations

6 visualization types per coin dashboard:
1. **ROI Horizontal Bar Chart** - Compare ROI% across variants
2. **Cumulative P&L Line Chart** - Track P&L over time
3. **Win Rate Donut Charts** - Win/Loss/Pending ratio
4. **Grouped Bar Chart** - Undervalued vs Momentum
5. **P&L Sparklines** - Mini inline charts
6. **Heatmap Table Styling** - Color-coded cells

---

## Quick Start

```bash
git clone https://github.com/penguinsolver/polymarket_v2.1.git
cd polymarket_v2.1
pip install -e .
cp .env.example .env
python -m web.api
# Open http://localhost:8002
```

---

*Last updated: January 23, 2026*
