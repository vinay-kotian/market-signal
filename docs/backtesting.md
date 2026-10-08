# Historical replay implementation

The previous backtester reused the strategy in isolated SQLite databases but
used synthetic contracts and previously observed quotes for fills. This version
adds a dated historical catalogue and replaces those fills with pending
historical execution. No external historical archive is currently connected.

## Reused components and abstractions

- `LevelMonitor`, `LevelRepository`, `SignalEngine`, `PriceHistory`: unchanged
  arming, rearming, approach/direction and signal rules. Option selection now
  consistently receives the Asia/Kolkata date.
- `OptionSelector`: unchanged ATM rounding, direction, ITM depth and nearest
  unexpired expiry; injected `HistoricalOptionInstrumentSource` uses the archive.
- `PaperExecutor`: shared entry validation, position construction, sizing,
  snapshots and initial stop. It enforces the requested single active trade per
  instrument. A reserved historical signal may fill after its level was consumed.
- `TradingTimeRules`, `PositionMonitor`, `progressive_stop`: shared entry windows,
  deadlines, strongest/monotonic protection and exit classification.
- `HistoricalDataSource.load(date, instrument)`: adapter boundary for future
  external historical sources; `LocalHistoricalDataSource` reads JSON exports.
- `HistoricalMarketDataProvider`: stable chronological delivery through the same
  `PriceTick` interface used by PAPER, with a replay clock.
- `BacktestExecutor`: pending entries filled through `PaperExecutor` at observed
  historical timestamps. Its exit-price hook receives the shared monitor's
  triggering observation so later slippage can be added without changing
  protection rules. It does not calculate stops or infer option prices.
- `BacktestTimeline`: audits transitions from shared state/events. No separate
  signal or stop algorithms. Mandatory-exit trigger time and fill time are
  distinct when the archive has no quote at the deadline.

The PAPER `MarketCloseService` retains its previously observed quote behavior;
it is not used in historical execution. BACKTEST uses `PositionMonitor`'s
existing deadline check at the first subsequent valid option observation.

## Data format

A file named `2026-09-14-BANKNIFTY.json` in `HISTORICAL_DATA_DIRECTORY`, or uploaded
through the UI, must use this structure. These records are illustrative test
observations; replace them with your archive's actual exchange contracts/prices.

```json
{
  "source": "YOUR_ARCHIVE_NAME",
  "contracts": [
    {
      "instrument": "BANKNIFTY",
      "expiry": "2026-09-30",
      "strike": 59900,
      "option_type": "CE",
      "symbol": "YOUR_ACTUAL_ARCHIVED_SYMBOL",
      "lot_size": 30,
      "instrument_token": 123456
    }
  ],
  "ticks": [
    {"timestamp": "2026-09-14T10:00:00+05:30", "instrument": "BANKNIFTY", "price": 60100},
    {"timestamp": "2026-09-14T10:01:00+05:30", "instrument": "BANKNIFTY", "price": 60000},
    {"timestamp": "2026-09-14T10:01:01+05:30", "instrument": "YOUR_ACTUAL_ARCHIVED_SYMBOL", "price": 200},
    {"timestamp": "2026-09-14T15:25:01+05:30", "instrument": "YOUR_ACTUAL_ARCHIVED_SYMBOL", "price": 210}
  ]
}
```

For an API upload:

```json
{
  "trading_date": "2026-09-14",
  "instrument": "BANKNIFTY",
  "levels": [59800, 60000, 60250],
  "contracts": ["replace with contract objects from the file"],
  "dataset": ["replace with tick objects from the file"],
  "index_settings": {"BANKNIFTY": {"initial_arm_distance_points": 80}}
}
```

`instrument_token` is optional. Symbols and expiry/strike/type identities must be
unique. All contracts must belong to the selected underlying, all timestamps
must be timezone-aware and belong to the selected Kolkata date, and all tick
symbols must resolve to the underlying or catalogue. Up to 100 levels, 10,000
contracts and 100,000 ticks are accepted. Ties retain file order. Negative/NaN
prices are rejected. Zero option quotes cannot fill entries but can trigger
stops and mandatory exits, matching the shared PAPER monitor.

The provider must export a **complete dated selection universe**, not merely
contracts it expects to trade. Include the nearest expiry's available strikes
and both option types; an absent required strike must fail selection rather
than silently falling back to another expiry. Include option prices for every
contract that the selected levels/settings could select. The application
cannot verify completeness against an exchange archive that is not connected.

Candle close observations can be supplied as ticks but only test decisions at
those observations. Candle OHLC does not reveal intrabar ordering, touches,
missed stops or spread/slippage. For accurate tick-level replay, provide
recorded ticks, not invented intra-candle paths. Missing early/late market
observations cannot be reconstructed.

## Storage

Existing strategy tables remain in each run's separate SQLite file. Three
run-local tables are added: `backtest_run` (identity/status/date/settings/levels
and immutable saved result), `backtest_contracts` (exact dated catalogue), and
`backtest_events` (run/trade/signal identity, timestamp/type, JSON payload).
Selected contract token, expiry, strike and lot size are retained in the
catalogue, option-selection events and saved trade result. Signal timestamps
remain separate from potentially delayed entry timestamps.

No migration of the application's PAPER database is required for these tables.
Older run result files remain readable by ID; old runs are not re-executed.
Archive hash plus settings snapshot make comparisons reproducible. Operational
creation/completion timestamps and run UUIDs differ across otherwise identical
replays. No live order API is called.

## Regression considerations

Delayed fills can cross cutoff, coincide with other level signals, or follow
rearming. Pending reservations prevent duplicate/competing entries and the
shared executor revalidates the actual fill timestamp. Deadline timers never
supply stale/future prices; missing closing quotes produce FAILED runs with
partial audit history. Tests cover both directions, initial arm distance,
historical expiry/ITM and lot size, equal-time ordering, pending fills/cutoff,
legacy/progressive protection parity, deterministic reruns, snapshot changes,
run persistence and PAPER/dashboard/broadcast isolation.
