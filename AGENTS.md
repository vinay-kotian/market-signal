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

Zerodha authentication, instruments, and market data are read-only; execution remains PAPER.
Paper option entries only; no live orders.
Initial and trailing stops with breakeven protection for PAPER trades only.
Backtesting V1 reuses the strategy with isolated BACKTEST state and local fixtures.
