# Market Signal

Market Signal is a FastAPI + SQLite trading signal platform for daily option-buying levels, paper trading, and deterministic strategy testing.

Current focus:
- Daily instrument levels with read-only history after the trading day passes
- L1 entry from either direction with approach direction captured
- L0 as the initial protective stoploss
- Upper levels as checkpoints that tighten trailing stoploss
- Paper trading first, live trading disabled by default
- Mock tick replay API for strategy demos
- Zerodha websocket adapter skeleton that normalizes Kite ticks into internal Tick DTOs

## Run locally

### Prerequisites

- Python 3.9+
- `pip`

The frontend is currently static HTML that uses Tailwind and daisyUI from CDNs. No Node.js setup is required yet.

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
python3 -m pip install -r requirements.txt
```

### 3. Create local environment config

The app defaults to paper trading and disables live trading. You can create a local `.env` with the same safe defaults:

```text
TRADING_MODE=PAPER
ENABLE_LIVE_TRADING=false
BROKER=ZERODHA
DATABASE_URL=sqlite:///./market_signal.db
FRONTEND_URL=http://127.0.0.1:3000
```

SQLite tables are created automatically when the API starts.

### 4. Start the API

```bash
uvicorn backend.app.main:app --reload
```

The API runs at:

```text
http://127.0.0.1:8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

### 5. Start the frontend

In a second terminal:

```bash
cd frontend
python3 -m http.server 3000
```

Open:

```text
http://127.0.0.1:3000
```

The levels page is available at:

```text
http://127.0.0.1:3000/levels.html
```

### 6. Run tests

```bash
python3 -m pytest
```

## Useful local commands

Fetch dashboard state:

```bash
curl http://127.0.0.1:8000/dashboard/summary
```

Run a one-click demo simulation:

```bash
curl -X POST http://127.0.0.1:8000/simulations/demo
```

This creates a demo instrument and today's levels if they do not exist, replays sample prices through the persisted paper workflow, and returns the resulting dashboard state.

Square off open paper positions at the latest in-memory price:

```bash
curl -X POST http://127.0.0.1:8000/trading/eod-square-off
```

Process one mock live tick against levels saved in SQLite:

```bash
curl -X POST http://127.0.0.1:8000/ticks/mock \
  -H "Content-Type: application/json" \
  -d '{"instrument_token": 1001, "last_price": 110}'
```

This endpoint:
- finds the instrument by token
- loads today's active levels
- runs the tick workflow
- keeps the latest tick in memory for direction/velocity
- saves paper order/position changes and audit events
- does not save raw ticks to SQLite

Replay a mock strategy path through the API:

```bash
curl -X POST http://127.0.0.1:8000/backtests/replay \
  -H "Content-Type: application/json" \
  -d '{
    "instrument_id": 1,
    "instrument_token": 1001,
    "symbol": "NIFTY_TEST_CE",
    "trading_day": "2026-05-17",
    "trailing_gap": 5,
    "levels": [
      {"name": "L0", "price": 100, "role": "STOPLOSS"},
      {"name": "L1", "price": 110, "role": "ENTRY"},
      {"name": "L2", "price": 120, "role": "CHECKPOINT"}
    ],
    "ticks": [
      {"price": 108},
      {"price": 110},
      {"price": 120}
    ]
  }'
```

## Zerodha setup

Check Zerodha readiness:

```bash
curl http://127.0.0.1:8000/zerodha/status
```

Create a local `.env` when you are ready to test Kite login:

```text
KITE_API_KEY=your_api_key
KITE_API_SECRET=your_api_secret
KITE_REDIRECT_URL=http://127.0.0.1:8000/zerodha/callback
FRONTEND_URL=http://127.0.0.1:3000
```

For a hosted server, configure the same callback URL in the Zerodha developer console:

```text
https://your-domain.com/zerodha/callback
```

Then connect Zerodha through the browser:

```text
http://127.0.0.1:8000/zerodha/login
```

The callback stores the daily access token in SQLite. You do not need to edit `.env` every day.

Manual request-token exchange is also available:

```bash
curl -X POST http://127.0.0.1:8000/zerodha/session \
  -H "Content-Type: application/json" \
  -d '{"request_token": "token_from_redirect"}'
```

Check whether today's DB session is active:

```bash
curl http://127.0.0.1:8000/zerodha/status
```

Deactivate today's session:

```bash
curl -X POST http://127.0.0.1:8000/zerodha/logout
```

Start Zerodha websocket stream after login and after today's levels are active:

```bash
curl -X POST http://127.0.0.1:8000/zerodha/stream/start
```

Check stream status:

```bash
curl http://127.0.0.1:8000/zerodha/stream/status
```

Stop stream:

```bash
curl -X POST http://127.0.0.1:8000/zerodha/stream/stop
```
