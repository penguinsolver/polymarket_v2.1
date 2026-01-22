# Polymarket Strategy Tester v2.1 - Data Model

## Core Models

### MarketWindow

Represents a 15-minute Polymarket market.

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | Market identifier (e.g., "will-btc-go-up-1737612000") |
| `coin_type` | CoinType | BTC, ETH, SOL, or XRP |
| `condition_id` | string | Polymarket condition identifier |
| `up_token_id` | string | Token ID for UP outcome |
| `down_token_id` | string | Token ID for DOWN outcome |
| `start_time` | int | Unix timestamp of market start |
| `end_time` | int | Unix timestamp of market end (start + 900s) |
| `winner` | Outcome? | Resolved outcome (UP/DOWN/null) |

---

### PaperOrder

Represents a simulated order.

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
| `limit_price` | float | Target fill price for second-chance |
| `status` | OrderStatus | PENDING, OPEN, FILLED, CANCELLED |
| `filled_size` | float | Filled quantity |
| `market_start_time` | int | Market start timestamp |
| `created_at` | float | Order creation time |
| `updated_at` | float | Last update time |

---

### Trade

Represents a filled order with resolution.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | UUID |
| `strategy` | StrategyType | UNDERVALUED or MOMENTUM |
| `strategy_variant` | string | e.g., "undervalued_48" |
| `coin_type` | CoinType | BTC, ETH, SOL, or XRP |
| `market_slug` | string | Target market |
| `outcome` | Outcome | UP or DOWN |
| `entry_price` | float | Fill price |
| `size` | float | Position size |
| `filled_size` | float | Filled quantity |
| `invested` | float | size × entry_price |
| `entry_time` | float | Fill timestamp |
| `resolution_time` | float? | Resolution timestamp |
| `result` | TradeResult | WIN, LOSS, or PENDING |
| `pnl` | float | Profit/loss |
| `market_start_time` | int | Market start timestamp |

---

### VariantMetrics

Per-variant performance statistics.

| Field | Type | Description |
|-------|------|-------------|
| `variant_name` | string | e.g., "undervalued_48" |
| `threshold` | float | Strategy threshold (e.g., 0.48) |
| `coin_type` | CoinType? | Coin or null for aggregate |
| `total_trades` | int | Total trades |
| `wins` | int | Winning trades |
| `losses` | int | Losing trades |
| `pending` | int | Unresolved trades |
| `total_pnl` | float | Net P&L |
| `total_invested` | float | Trading volume |
| `win_rate` | float | Wins / (wins + losses) × 100 |
| `roi` | float | P&L / invested × 100 |

---

## Enums

### StrategyType
- `UNDERVALUED` - Buy when price ≤ threshold
- `MOMENTUM` - Buy when price ≥ threshold

### Outcome
- `UP` - Price goes up
- `DOWN` - Price goes down

### OrderStatus
- `PENDING` - Created, not yet open
- `OPEN` - Waiting for fill
- `FILLED` - Fully filled
- `CANCELLED` - Cancelled by system
- `EXPIRED` - Expired without fill

### TradeResult
- `WIN` - Correct prediction
- `LOSS` - Incorrect prediction
- `PENDING` - Awaiting resolution
