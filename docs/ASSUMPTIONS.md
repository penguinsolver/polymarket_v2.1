# Polymarket Strategy Tester v2.1 - Assumptions

## Entry Window Logic

### Timing Rationale

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Entry Window Start | 20:30 (countdown) | Allows time for price discovery |
| Entry Window End | 15:30 (countdown) | Ensures sufficient time for order fills |
| Window Duration | 5 minutes | Balance between opportunity and risk |

**Why this window?**
- Markets become more liquid as they approach activation
- Too early = poor price discovery, spreads may be wide
- Too late = risk of not filling before market starts

### Order Cancellation

All unfilled orders are **automatically cancelled** when countdown reaches 15:30 because:
- Prevents orders from filling at unfavorable prices during high volatility
- Ensures positions are only entered with sufficient time buffer

## Fill Simulation Model

### Initial Fill Probability

```python
sim_fill_probability = 0.7  # 70% chance of immediate fill
```

**Rationale**: Simulates realistic order book depth and slippage. Not all limit orders fill immediately.

### Second-Chance Fill

Orders that don't fill immediately remain **OPEN** during the entry window:

```
If current_market_price <= limit_price → Fill at limit_price
```

**Assumptions**:
- Market with sufficient depth to absorb our order size
- No partial fills (all-or-nothing for simplicity)
- Fill price is always the limit price (conservative assumption)

## Trade Resolution

### When Trades Are Resolved

Trades are resolved when:
1. Market `end_time` has passed (15 minutes after start)
2. Market outcome data is available from Polymarket API

### Resolution Polling

- Polls every 15 seconds for pending trades
- Fetches market outcome from Polymarket Gamma API
- If fetch fails, retries on next poll cycle

## P&L Calculation

```python
# WIN: Predicted outcome matches actual
pnl = size * (1.0 - entry_price)

# LOSS: Predicted outcome differs
pnl = -size * entry_price
```

**Example** (10 shares, entry $0.48):
- WIN: 10 × (1.0 - 0.48) = +$5.20
- LOSS: -10 × 0.48 = -$4.80

## Error Handling

### API Failures

| Scenario | Behavior |
|----------|----------|
| Price fetch fails | Skip order placement, log warning |
| Market slug not found | Retry with expanded time range |
| Resolution fetch fails | Retry on next poll cycle |
| WebSocket disconnect | Auto-reconnect after 3 seconds |

### Graceful Degradation

The system continues operating even if:
- Some coin engines fail (others continue)
- API temporarily unavailable (retries with backoff)
- Price data missing (skips that market window)

## Winning Variants Filter

On the main dashboard "Last 20 Trades" widget:

**Winning variant** = Strategy variant with net positive P&L across all trades

This filter helps identify which threshold strategies are performing best in current market conditions.
