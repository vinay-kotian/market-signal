# Project Rules

This is an incremental options trading platform.

## Principles

- Keep implementations simple and modular.
- Do not over-engineer.
- Build one working capability at a time.
- Explain important design decisions for learning.
- Use async/event-driven processing where appropriate.
- Do not create one thread per instrument or price level.
- Trading strategy logic must remain independent of Zerodha.
- Simulated, Zerodha, and historical market data should eventually use the same strategy engine.
- Do not change trading rules without explicit approval.
- Paper trading must be implemented before live trading.
- Never execute live broker orders from tests.

## Current Milestone

Milestone 1:

FastAPI + React + SQLite + Levels + Simulated Market Data.

No Zerodha integration yet.
Paper option entries only; no live orders.
No stop loss yet.
No backtesting yet.
