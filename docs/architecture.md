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


Traded option watchlist membership is stored by `TradeRepository` in the trade
transaction. `OptionWatchlistRepository` reuses trade metadata and persisted
quotes; `LiveEventPublisher` supplies changes through the existing browser
feed. Zerodha unions watchlist tokens with indices and open positions on its
single socket. This feature does not modify strategy decisions or enable LIVE
orders. See the watchlist section in [README.md](../README.md).
