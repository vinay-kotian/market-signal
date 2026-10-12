# Historical replay implementation

The previous backtester reused the strategy in isolated SQLite databases but
used synthetic contracts and previously observed quotes for fills. This version
adds a dated historical catalogue and replaces those fills with pending
historical execution. The optional Zerodha candle loader is described below;
recorded tick archives remain upload/local-file based.

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


## ATR exits and comparisons

Choose `exit_strategy: "LEGACY"` or `"ATR"` in `/backtests/run`; the shared
PAPER/exit implementation supplies all protection decisions. `exit_configuration`
contains independent ATR settings, and `transaction_cost_per_order` supplies a
nonnegative flat fee estimate per entry or exit. Defaults are described in the
[exit strategy settings](../README.md#independent-exit-strategies).

Supply prior completed five-minute OHLC as an optional `candles` array in the
uploaded/archive JSON and in the API request. Tick dates retain their existing
single-day restriction; warmup candles may come from earlier trading dates.
Candle symbols must exist in the supplied catalogue or match the underlying.
Maximum 100,000 candles, unique by symbol/start, with finite valid OHLC and
five-minute aligned timezone-aware start timestamps. For example:

```json
{
  "symbol": "TEST-NIFTY-20260917-25050-PE",
  "timestamp": "2026-09-14T09:20:00+05:30",
  "open": 100,
  "high": 104,
  "low": 98,
  "close": 102,
  "available_at": "2026-09-14T09:25:00+05:30"
}
```

`available_at` defaults to candle end. Delayed candles use their later actual
availability time. ATR entry filters both completion and availability against
entry time and freezes the result. It needs at least the configured period of
eligible candles. Recorded ticks can build observed OHLC during replay;
authoritative supplied OHLC takes precedence. No intra-candle ticks are invented.
Missing option ATR skips entry with `OPTION_ATR_UNAVAILABLE` and retains its audit
result. Supplied index ATR is recorded separately and never determines the stop.

`POST /backtests/compare` accepts the same request and loads historical data once,
then saves Current plus ATR multiplier runs for 1, 1.25, 1.5, 1.75, 2 and 2.5.
Dataset hashes and all entry settings match across runs. Exit-dependent position
availability can affect subsequent entries through the existing single-position
rule. Each result includes run ID, strategy/multiplier, trade count, win rate,
average profit/loss, profit factor, net P&L, realised drawdown, average R, stop hits
and transaction costs. Open trade entry fees are included in net P&L and total
costs; closed-trade metrics/drawdown use net realised results. Average R uses net
closed-trade P&L divided by the immutable initial risk amount. Saved trade P&L
continues to represent gross execution P&L. Older saved runs retain their original
metrics and may lack ATR/risk/cost fields.

## Zerodha historical candle replay

Select **Zerodha historical · 1-minute candles** in Backtest after configuring
`MARKET_DATA_MODE=ZERODHA` and connecting Kite. The UI starts with the current
configured exit strategy and latest completed weekday session in Asia/Kolkata.
It has no exchange holiday calendar: an empty holiday session is rejected.
The existing archive/upload sources and synthetic NIFTY demo remain available.

```json
{
  "trading_date": "2026-10-09",
  "instrument": "NIFTY",
  "levels": [25200, 25300],
  "data_source": "ZERODHA_HISTORICAL",
  "exit_strategy": "ATR",
  "transaction_cost_per_order": 2
}
```

`BacktestInput` retains the existing `trading_date` naming and current-settings
merge behavior. Explicit settings override only this run. Zerodha history may
not be combined with uploaded data or a demo fixture. Both `/backtests/run` and
`/backtests/compare` use the same loader and existing isolated replay engine.
Only NIFTY/BANKNIFTY are supported for this source. Sessions, entry cutoffs and
mandatory exits must fall on whole-minute boundaries.

### Dated contracts and downloads

The first successful Zerodha instrument sync each day now archives a catalogue
by Kolkata calendar date in `zerodha_instrument_catalogues`; later refreshes
retain that earliest snapshot. Post-session-only snapshots are rejected because
expiring contracts may already have been removed. This is an additive table
created automatically in the application database. The previously saved latest
dump is backfilled under its original sync date before a new sync replaces it.
Existing strategy tables
and PAPER records are unaffected. A legacy latest dump is usable only if its
saved sync timestamp belongs to the requested date. An undated or newer dump
cannot prove the historical nearest expiry and is rejected, including across
weekends. Saving catalogues starts with this release; historical catalogues
cannot be retroactively reconstructed from today's master.

The shared `OptionSelector` supplies all expiry, strike, CE/PE and ITM decisions.
The loader prefetches contracts it could select at the recorded index closes,
in both directions. This keeps strategy comparisons on one frozen archive
without downloading an entire option chain. An unavailable unused candidate
is retained as a coverage warning; a run actually selecting it fails. Missing
strikes never fall back to another expiry.

Completed-session minute downloads must contain every session minute, in
chronological order with unique timestamps and finite valid OHLCV. An empty,
missing or duplicate minute fails coverage validation. Sparse option histories
are therefore rejected even when a trade might otherwise have filled; no price
interpolation is performed. No successful trading result is produced using a
selected contract with incomplete session history.

Validated downloads are stored in `HISTORICAL_DATA_DIRECTORY/zerodha-history.sqlite3`,
defaulting to `historical-data` beside the application database. Cache keys include the full dated contract
identity/token, requested interval and exact range, preventing token-reuse
collisions. Cache hits do not change the dataset hash. Previously validated
cached prices can replay after expiry or without an active session; uncached
expired-contract tokens are rejected because they cannot safely identify a
historical contract through today's API. Backtest reports, catalogue/token
snapshots, coverage, source, assumptions and audit events remain in each run's
existing isolated `results.sqlite3`.

The existing read-only Kite connector throttles history requests to less than
three per second using one async lock shared with charts and PAPER ATR history.
HTTP 429, server failures and network failures retry up to three attempts with
bounded backoff. Expired authentication requires reconnecting; it never falls
back to simulated prices. No order APIs are added or called.

### Execution assumptions

Results explicitly identify `data_resolution: "1_MINUTE_OHLC"` and
`execution_model: "CANDLE_APPROXIMATION"`:

1. Feed completed index **closes** to the unchanged level/signal engine at
   candle end. Do not infer index touches or order of multiple intraminute
   levels from OHLC. Initial arming/rearming, approach distance, deduplication,
   direction and the single-position rule remain shared with PAPER.
2. Reserve an eligible signal, then fill at the next option candle **open**.
   At an equal timestamp, completed option bars are handled first, then index
   closes/signals, then the next option opens. The preceding completed option
   close is never an entry fill. Actual entry time is revalidated against the
   configured cutoff by the shared executor.
3. At completion of a held option candle, pass its **low, high, low again,
   close** through the existing protection implementation, stopping once the
   trade closes. A low that already breaches the existing stop exits before
   crediting the high. Otherwise the high can raise protection, and the repeated
   low conservatively tests ambiguous high/low ordering against that protection.
   Stop exits fill at the adverse observed low, rather than a favorable stop
   price. This is a documented stress assumption, not a claimed tick path.
   Exit timestamps are bar completion timestamps, not exact intraminute times.
4. Evaluate a completed preceding option bar before its next open. A surviving
   position exits at the first option open at or after the mandatory deadline
   through the shared position monitor. No stale closing quote is used.
5. Build ATR from authoritative option OHLC aggregated into **complete five-minute
   bars**, matching the existing ATR timeframe, plus prior completed Kite
   five-minute bars from a ten-calendar-day warmup range. Only bars completed
   and available by entry contribute. Option ATR determines the stop; index ATR
   does not. Missing warmup is reported; insufficient eligible candles retain
   the existing `OPTION_ATR_UNAVAILABLE` entry skip.
6. Flat per-order transaction costs use the existing backtest model and are
   reported with gross/net P&L and average R. There is no independent configurable
   slippage or brokerage-tax breakdown in that existing model. The adverse
   candle-low fill is the conservative execution assumption; it cannot model
   real spreads, liquidity or exchange tick ordering.

An actual 9 October run requires a reliable catalogue for **9 October**, cached
or retrievable prices for its selected contracts, and Kite history access.
Automated tests use mock broker responses, including an entire 375-minute
9 October BANKNIFTY session. They do not establish that a user's Kite account
or the exchange archive can supply the requested day's contracts/prices.

Official API references: [historical candle data](https://kite.trade/docs/connect/v3/historical/)
and [history rate limits/errors](https://kite.trade/docs/connect/v3/exceptions/).
