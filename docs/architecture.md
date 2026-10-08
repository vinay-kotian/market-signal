# Architecture

The strategy is independent of the broker. PAPER and historical BACKTEST share
level monitoring, signal analysis, option selection, entry construction, time
rules, position monitoring and legacy/progressive protection.

PAPER supplies simulated or read-only Zerodha market data to `SimulationFlow`,
`LevelMonitor` and `PositionMonitor`, with `PaperExecutor` for entries and
`MarketCloseService` for scheduled closes. Live orders are unsupported.

BACKTEST supplies recorded observations and a dated contract catalogue through
`HistoricalDataSource` and `HistoricalMarketDataProvider`. `BacktestRunner`
injects a historical clock and isolated SQLite repositories into the shared
services. `BacktestExecutor` reserves entries and calls the shared PAPER entry
implementation when an eligible option quote arrives. `PositionMonitor`
processes historical prices and mandatory closes without a separate stop
algorithm. `BacktestTimeline` audits the resulting state transitions.

See [backtesting.md](backtesting.md) for interfaces, storage, source requirements,
execution ordering and regression considerations.
