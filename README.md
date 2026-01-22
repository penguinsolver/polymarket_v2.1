# Polymarket Strategy Tester v2.1

Multi-coin paper trading dashboard for Polymarket 15-minute crypto markets.

## Features

- **Multi-coin Support**: BTC, ETH, SOL, XRP
- **Individual Controls**: Start/stop each coin separately
- **Paginated Tables**: Show 8 rows with expand option
- **Export Functions**: TXT and Markdown formats
- **Strategy Comparison**: Undervalued vs Momentum

## Quick Start

```bash
# Install dependencies
pip install -e .

# Run the dashboard
python -m web.api
```

Then open http://localhost:8002 in your browser.

## Configuration

Copy `.env.example` to `.env` and configure:

```
UNDERVALUED_THRESHOLD=0.48
MOMENTUM_THRESHOLD=0.52
ORDER_SIZE_SHARES=10
```

## Project Structure

```
polymarket_strategy_tester_v2/
├── src/
│   ├── config.py           # Configuration with coin types
│   ├── models.py           # Data models
│   ├── market_tracker.py   # Multi-coin market tracking
│   ├── strategy_engine.py  # Trading engine
│   └── clob_client.py      # Polymarket API client
├── web/
│   ├── api.py              # FastAPI backend
│   └── static/
│       ├── index.html      # Main dashboard
│       ├── btc.html        # BTC dashboard
│       ├── eth.html        # ETH dashboard
│       ├── sol.html        # SOL dashboard
│       ├── xrp.html        # XRP dashboard
│       └── dashboard.js    # JavaScript
└── pyproject.toml
```
