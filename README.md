# Market Signal

Market Signal provides a FastAPI backend and React frontend for SQLite-backed
levels, simulated price ticks, approach signal analysis, simulated option selection, paper trade entry, and initial/trailing stop monitoring with breakeven protection.

## Run locally

From the repository root, using Python 3.9 or newer:

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/health in your browser, or run:

```sh
curl http://127.0.0.1:8000/health
```

Expected response (HTTP 200):

```json
{"status": "ok"}
```

Stop the server with Ctrl+C.

In a second terminal, from the repository root (Node.js 22.12+):

```sh
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite, normally http://127.0.0.1:5173.
The frontend sends `/api` requests through Vite to the backend at port 8000.
For a different backend address, set `API_TARGET` when starting Vite. No CORS
change is needed for this local proxy. The production frontend build is a static
bundle; hosting it later requires an equivalent `/api` reverse proxy.

The Dashboard shows the watchlist, configured levels, simulation controls, and
recent signals and option selections. The Trades page shows persisted paper entries
and entry failures. The Levels page supports adding, editing, toggling, and deleting
levels. Prices reflect successful submissions from this browser session and reset
on refresh; they are not an authoritative server price feed. Signals refresh after
each successful tick or level change and when you click Refresh. Ticks published
by another client require Refresh to see their signals.

## Levels API

| Method | Path | Result |
| --- | --- | --- |
| POST | `/levels` | Create a level (201) |
| GET | `/levels` | List levels in ID order (200) |
| GET | `/levels/{id}` | Read one level (200) |
| PUT | `/levels/{id}` | Replace its editable fields (200) |
| DELETE | `/levels/{id}` | Delete a level (204, empty body) |

Create a level while the server is running:

```sh
curl -X POST http://127.0.0.1:8000/levels \
  -H 'Content-Type: application/json' \
  -d '{"instrument":"NIFTY","price":25000,"enabled":true}'
```

The response includes `id`, `instrument`, `price`, `enabled`, `created_at`, and
`updated_at`. The server generates the ID and UTC timestamps. Updates preserve
`created_at` and refresh `updated_at`. `PUT` requires all three editable fields:
`instrument`, `price`, and `enabled`.

Instrument names are trimmed and cannot be blank; prices must be finite numbers.
Extra fields are rejected. IDs must be positive integers within SQLite's signed
64-bit range. Missing records return 404; invalid IDs and invalid request bodies
return 422. Interactive API documentation is at
http://127.0.0.1:8000/docs.

## Database and request flow

- `backend/app/models.py` defines the request and response models.
- `backend/app/database.py` initializes SQLite and manages connections and transactions.
- `backend/app/level_repository.py` contains the SQL for creating, reading, updating,
  and deleting levels.
- `backend/app/levels.py` maps HTTP requests to repository operations and HTTP responses.
- `backend/app/main.py` assembles the application and initializes SQLite at startup.

On startup, SQLite creates `backend/levels.sqlite3` if it does not exist.
`CREATE TABLE IF NOT EXISTS` creates the levels table without deleting existing
data. This file persists across restarts and is ignored by Git. No separate
database server or additional Python dependency is needed: `sqlite3` is built in.
This is initial table setup, not a schema migration system.

```text
POST /levels with JSON
        ↓
LevelInput validates the request
        ↓
API route calls the repository
        ↓
Repository inserts the row into SQLite and commits
        ↓
Level response model → JSON response (201)
```

SQL parameters keep submitted values separate from SQL statements. Each repository
operation opens its own connection, commits on success or rolls back on error,
and closes the connection. SQLite stores enabled as 0/1 and timestamps as UTC text;
the response model converts them to booleans and datetime values for JSON.
Prices use SQLite REAL (floating point) for this milestone.

Routes handle HTTP concerns; the repository handles storage. This keeps SQL out of
routes and lets storage change without rewriting request handling. The SQLite
routes use regular `def` functions so FastAPI runs blocking database work in its
worker thread pool instead of blocking the async event loop.

## Simulated market data

Create an enabled NIFTY level at 25000 using the example above. Then establish a
previous price and publish a price that crosses the level:

```sh
curl -X POST http://127.0.0.1:8000/simulation/tick \
  -H 'Content-Type: application/json' \
  -d '{"instrument":"NIFTY","price":24990}'

curl -X POST http://127.0.0.1:8000/simulation/tick \
  -H 'Content-Type: application/json' \
  -d '{"instrument":"NIFTY","price":25005}'

curl http://127.0.0.1:8000/simulation/events
```

`POST /simulation/tick` returns `{"status":"processed"}` (200) after the monitor
finishes. `GET /simulation/events` returns up to 100 recent events, newest first,
or `[]` when none have triggered. Each event includes `event_type` set to
`LEVEL_TRIGGERED`, an event `id`, `level_id`, `instrument`, `level_price`,
`previous_price`, `current_price`, and a UTC `triggered_at` timestamp.

```text
POST /simulation/tick → validated PriceTick
        ↓
SimulatedMarketDataProvider.publish()
        ↓ await
LevelMonitor.on_tick()
        ↓
Read previous price + load enabled instrument levels from SQLite
        ↓
Check touches/crossings → store LEVEL_TRIGGERED events in memory
        ↓
Update previous price → respond with status: processed
```

`app/market_data.py` defines the `PriceTick`, `MarketDataProvider` protocol, and
simulated implementation. The protocol is the small contract for publishing
normalized instrument/price events. The simulator implements it structurally,
without requiring inheritance. Its consumer callback receives the event, so the
provider does not contain level-detection rules. Future sources can feed the same
monitor with the same event shape.

`app/level_monitor.py` owns a dictionary of previous prices keyed by instrument.
On the first tick, there is no crossing to compare, but an exact touch still
triggers. Every processed price becomes the next baseline, even if no levels exist.
Instrument matching is case-sensitive; surrounding whitespace is trimmed.

A level triggers when any of these conditions holds:

- `previous < level <= current`
- `previous > level >= current`
- `current == level`

One combined condition emits at most one event per level per transition, including
when a crossing ends exactly on a level. Consecutive identical prices are ignored,
so repeated ticks at a level do not emit duplicates. Moving away and crossing or
touching again can trigger another event. There is no permanent "already triggered"
flag. Enabled levels are loaded on each changed tick; CRUD changes take effect on
the next changed price. These ticks have no source event IDs, so a delayed replay
after intervening ticks is treated as a new tick, not a deduplicated retry.

`app/simulation.py` contains the two HTTP routes. Publishing directly awaits the
monitor, and an async lock keeps each transition's read/evaluate/update operation
together. No background workers, queues, or new threads are created. The existing
SQLite repository performs a small synchronous query inside this flow; it can
briefly block the event loop. This is suitable for this local milestone, not a
high-throughput data feed.

Run one server process for simulation. Previous prices and recent events are
in-memory state and reset on restart or development reload; level records remain
in SQLite. Event IDs are local to that process lifetime. The recent-event buffer
is for inspection, not a durable audit log.

## Run the tests

From `backend`, with the virtual environment activated:

```sh
python -m pytest
```

Frontend checks, from `frontend`:

```sh
npm test
npm run build
```

Tests use FastAPI's `TestClient` to make in-process requests. Each test uses a
temporary SQLite database, so tests never modify `backend/levels.sqlite3`.
Coverage includes health, create, list, read, update, delete, invalid IDs and
request bodies, and persistence across application restarts. No running server
is needed. `pytest` runs the tests; `httpx` supports `TestClient`.

Simulation tests additionally cover upward/downward crossings, exact touches,
no crossing, disabled levels, multiple levels, per-instrument initialization,
duplicate ticks, later recrosses, current level changes, invalid ticks, bounded
event history, restart behavior, and concurrent duplicate publication.

## How it works

Uvicorn is the server. `app.main:app` tells it to import the `app` object from
`app/main.py`. That object is the FastAPI application. `--reload` restarts the
server when you edit code during local development.

```text
Browser/API request: GET /health
        ↓
FastAPI route: @app.get("/health")
        ↓
Python function: health()
        ↓
JSON response: {"status": "ok"}
```

The route decorator connects the HTTP method and path to the Python function.
FastAPI converts the returned dictionary into JSON and defaults to HTTP 200.
The endpoint reports that the application responds; it checks no dependencies.

Learn the distinction between the server, the route, and the function, then
practice verifying the response through both a browser and an automated test.
For this step, also learn request validation, HTTP status codes, SQL CRUD,
transactions, persistent storage, and separating HTTP handling from database access.
For simulation, follow the normalized event through the provider and monitor;
learn how per-instrument state enables transition detection, how to avoid duplicate
results, and how transient event state differs from persistent configuration.

## Signal analysis

`GET /signals` reads the latest 100 signal results from SQLite, newest ID first. Each contains
`id`, `trigger_id`, `level_id`, `instrument`, `level`, `trigger_price`, `direction`,
`approach_distance`, `valid`, `rejection_reason`, and a UTC `timestamp`.

The processing flow is:

```text
Simulated tick → LevelMonitor reads recent price history
              → touch/cross → LEVEL_TRIGGERED → SignalEngine
              → SignalRepository → SQLite → GET /signals → Dashboard
```

- `app/events.py` defines the shared trigger event, so the monitor and engine do
  not depend on each other's event definitions.
- `app/price_history.py` stores received prices and UTC receive times per instrument.
  Each deque keeps at most 2,000 samples within the configured time window.
  Expired samples and inactive instrument histories are pruned on incoming ticks.
  Repeated prices are recorded, but still do not generate duplicate triggers.
- `app/signal_engine.py` evaluates each trigger against supplied history; it owns
  no price history, result buffer, database access, or ID counter.
- `app/signal_models.py` defines the analysis and persisted result models.
- `app/signal_repository.py` inserts results and queries recent records from SQLite.
  SQLite assigns durable IDs. The monitor owns price history and coordinates
  evaluation and persistence. All results for one transition commit together;
  if saving fails, no partial signals are retained and the transition can be retried.
- `app/settings.py` validates startup settings; `app/signals.py` provides the read API.

Direction uses the latest continuous approach approved for this milestone. The
engine walks backward from before the triggering tick, stopping at a previous
touch, the opposite side of the level, or the lookback boundary. Prices above the
level mean `FROM_ABOVE`; prices below mean `FROM_BELOW`. Same-side pullbacks remain
in the segment. It uses the segment's high/low, not just the final pair of ticks:

```text
FROM_ABOVE: distance = maximum approach price − level
FROM_BELOW: distance = level − minimum approach price
```

The triggering price is excluded from that range, so crossing overshoot does not
inflate distance. For example, 24900 → 24980 → 25005 at level 25000 yields
`FROM_BELOW`, distance 100. A later 24990 → 25000 recross uses that new approach,
not an extreme from before the previous crossing.

With no prior price in the current approach/window, the result is rejected as
`INSUFFICIENT_PRICE_HISTORY` with null direction and distance. One prior price is
enough for a short approach; a full 15 minutes of observations is not required.
An initial exact touch still produces a trigger and a rejected analysis.

Settings are read from environment variables when the backend starts:

| Variable | Default | Meaning |
| --- | --- | --- |
| `LOOKBACK_MINUTES` | `15` | Positive rolling time window |
| `MINIMUM_APPROACH_DISTANCE_ENABLED` | `false` | Enable distance rejection |
| `MINIMUM_APPROACH_DISTANCE_POINTS` | `0` | Nonnegative minimum distance |

For example, start the backend with a 100-point minimum:

```sh
LOOKBACK_MINUTES=15 MINIMUM_APPROACH_DISTANCE_ENABLED=true MINIMUM_APPROACH_DISTANCE_POINTS=100 python -m uvicorn app.main:app --reload
```

When enabled, a distance strictly below the minimum is rejected with
`MINIMUM_DISTANCE_NOT_MET`; equality passes. When disabled, distance is still
calculated, but it never causes rejection. Missing history is a separate failure.
Restart the backend to change settings. Tests can pass `SignalSettings` directly
to `create_app` without modifying the environment.

Signals are stored in the `signals` table in `backend/levels.sqlite3` and survive
repository reload and application restart. Startup adds the table if missing
without deleting existing levels or signals. The latest-100 limit applies only
to reads; older records remain stored. Level edits/deletion do not erase signal
snapshots. The additional `level_id` and `trigger_id` fields preserve the existing
API; trigger IDs refer to in-memory events and are only unique within a process
lifetime, while signal IDs remain unique across restarts.

Previous prices and rolling history remain in memory and reset on restart. The
sample cap can shorten available history during a dense tick stream; analysis
uses retained samples. Existing persisted signals remain visible while new ticks
build fresh history. Use one backend process for this milestone.

Persistence tests verify complete field round-trips (including rejected results
with unknown direction/distance), repository reload, application restart, durable
IDs, retained records beyond the read limit, and rollback/retry after a failed
multi-level save.

The monitor answers "was a level touched or crossed?" while the engine answers
"what was the approach, and does it meet the configured distance requirement?"
Keeping these separate lets analysis evolve without changing trigger detection.
Learn the difference between events and their interpretation, bounded time-based
state, per-level analysis, and an explicit rejection versus missing information.

## Option selection

Each newly generated valid signal is passed to `OptionSelector`. Rejected signals
produce no selection. Existing signals are not replayed at startup.

- `app/option_instruments.py`: the broker-independent source protocol and seeded
  simulated contracts. The source provides both strike steps and complete symbols.
- `app/option_selector.py`: evaluates the desired type, expiry, ATM, and ITM strike,
  then looks up an exact contract. It does not write to storage or place orders.
- `app/option_models.py` and `app/option_repository.py`: result models and SQLite
  persistence. One result is allowed per durable signal ID.
- `app/option_routes.py`: `GET /option-selections`, returning the most recent 100
  stored results by descending ID. Older records remain in SQLite.

ATM rounds the signal's **trigger price**, not its configured level, to the
nearest strike step using decimal half-up rounding. At a simulated NIFTY step
of 50, 25024.99 rounds to 25000, while 25025 rounds to 25050. Depth 1 means one
step from ATM; depth 2 means two steps:

```text
FROM_ABOVE → CE → ITM strike = ATM − depth × step
FROM_BELOW → PE → ITM strike = ATM + depth × step
```

At NIFTY trigger price 25005, ATM is 25000: depth 1 selects 24950 CE or 25050 PE;
depth 2 selects 24900 CE or 25100 PE. These are synthetic examples.

Startup seeds 21 strikes per instrument, both CE and PE, for two synthetic
expiries 7 and 14 days after the startup UTC date:

| Instrument | Simulated step | Seeded strike range |
| --- | --- | --- |
| NIFTY | 50 | 24500–25500 |
| BANKNIFTY | 100 | 50000–52000 |

Symbols look like `SIM-NIFTY-2026-09-21-24950-CE`. They are local test symbols,
not exchange contracts. Expiries are synthetic dates, not an exchange calendar.
The source is fixed for the process lifetime; restarting regenerates the seed
relative to that startup date, while historical selection records remain intact.

Start the backend with settings as needed:

```sh
ITM_DEPTH=2 EXPIRY_STRATEGY=NEAREST python -m uvicorn app.main:app --reload
```

Defaults are depth 1 and NEAREST. Only positive integer depths and the NEAREST
strategy are supported. Expiries earlier than the signal's UTC date are excluded;
an expiry on that date remains eligible throughout the date for this simulation.
The nearest expiry is chosen before looking for the exact strike/type. No fallback
occurs if that contract is absent.

Successful results have `status: SELECTED` and an `option_symbol`. Failed attempts
have `status: FAILED`, a null symbol, and one of `UNSUPPORTED_INSTRUMENT`,
`NO_UNEXPIRED_CONTRACT`, or `MISSING_OPTION_CONTRACT`. A failed selection does not
change the signal's validity. Results also store the signal ID, instrument,
trigger price, direction, option type, configured depth, expiry, ATM/ITM strikes,
and timestamp. Unknown expiry or strikes are null.

Signal and option selection inserts share one SQLite transaction for each price
transition. A database failure rolls back both, leaving the transition retryable.
The `option_selections` table is added during startup without deleting existing
data. A unique signal ID prevents storing two selections for the same signal.
Saving the same signal again returns the original stored result without raising
an error or changing it, even after a reload or settings change. This applies to
both successful and failed selections. Distinct signals may select the same
contract independently.

On the Dashboard, recent option selections refresh alongside signals after ticks,
level changes, or manual Refresh. The table shows contract, expiry, ATM/ITM strike,
and success/failure, with loading, empty, and error states.

Later, an adapter can translate a broker's instrument dump into the same source
contract: instrument, expiry, strike, type, symbol, and strike-step metadata.
Real expiry/session policy will need a separate explicit implementation. The
selector and signal rules need no Zerodha imports. No broker APIs are used here.

Learn to separate a signal (why a level matters), a contract selection (which
instrument matches the rule), and a future order (an action not implemented yet).
Also learn deterministic rounding, exact instrument lookup, explicit selection
failures, and atomic persistence across related results.

## Paper trade entry

New valid signals now flow through selection into paper execution:

```text
Level trigger → SignalEngine → OptionSelector → persisted selection
             → PaperExecutor → simulated option quote → TradeRepository → SQLite
```

`app/paper_executor.py` handles execution only. It checks that selection succeeded,
resolves the selected contract's lot size, reads the current quote from
`app/option_prices.py`, and persists an OPEN PAPER trade. It does not calculate
signal direction or select another contract. The engine and selector remain
independent of execution and broker code.

`app/trade_models.py` defines entry, stored trade, and entry-result models.
`app/trade_repository.py` owns SQLite access. Startup creates `trades` and
`trade_entry_results` in the existing database without deleting previous data.

Configure the backend before starting it:

```sh
TRADE_MODE=PAPER NUMBER_OF_LOTS=2 python -m uvicorn app.main:app --reload
```

Defaults: PAPER mode, one lot. `NUMBER_OF_LOTS` must be a positive integer.
LIVE is a recognized mode but always returns `LIVE_MODE_NOT_SUPPORTED` and cannot
create a trade; the SQLite schema also allows only PAPER trades.

Quantity is `contract.lot_size × number_of_lots`. The synthetic NIFTY contracts
have lot size 10 and BANKNIFTY contracts have lot size 20. These are explicit test
values, not current exchange lot sizes. Both the lot size and lot count are saved
with quantity so the calculation remains inspectable after configuration changes.

The default quote source starts with a 100.00 premium for each synthetic NIFTY
option and 200.00 for each synthetic BANKNIFTY option. These are arbitrary test
quotes, not market-derived prices or a pricing model. The source keeps the last
supplied quote by option symbol; `set_price(symbol, price)` can update it in code.
Underlying ticks do not update option premiums. Tests can inject an empty/custom
`SimulatedOptionPrices` through `create_app(option_prices=...)`. Option-symbol ticks sent to `/simulation/tick` update the current simulated quote
and monitor open positions. There is no live feed.

Missing, zero, negative, or non-finite quotes produce a persisted
`OPTION_PRICE_UNAVAILABLE` entry result and no trade. Missing contract metadata
or invalid lot sizes produce explicit failures too. Failed selections and rejected
signals are skipped by execution.

`GET /trades` returns the latest 100 stored trades, newest trade ID first. Each has
`trade_id`, `signal_id`, `option_selection_id`, `instrument`, `trigger_level`,
`direction`, `option_symbol`, `option_type`, `strike`, `expiry`, `lot_size`,
`number_of_lots`, `quantity`, `entry_price`, `entry_time`, `trade_mode`, and `status`.
Older trades remain stored. `GET /trade-entry-results` exposes the latest 100 entry
outcomes, including failure reasons. The React Trades page shows entries across
all instruments and any failures in these recent outcomes.

`option_selection_id` is a UNIQUE key in the trades table. Reprocessing an already
entered selection returns the original trade before looking up quotes or current
lot settings. A failed attempt may be retried through the execution service; if it
later succeeds, its latest entry outcome changes to OPEN. This is a latest-outcome
record, not a full retry history. There is no background retry or automatic replay
of selections on startup. Old successful selections do not create trades merely
because the application restarts.

During tick processing, signal, selection, trade, and entry outcome writes share
one transaction. Database failures roll back the transition, while expected
execution failures persist their reason alongside the valid signal/selection.
Records survive restarts; rolling underlying history and option quotes do not.

Persisting entries now provides stable trade identities and entry snapshots for
future monitoring. Other exit types and broker execution logic remain deferred. Learn the boundary between deciding what to trade and
simulating an entry, quantity sizing from contract metadata, durable idempotency,
and the difference between a failed entry attempt and an open trade.

## Position monitoring and initial stop loss

Set `STOP_LOSS_PERCENTAGE` before starting the backend; the default is 10 and
valid values are strictly between 0 and 100. Each new PAPER trade stores the
percentage and `initial_stop_loss = entry_price * (1 - percentage / 100)`.
A 100.00 entry with 10% stop stores 90.00. Changing configuration never changes
an existing trade's stop. Calculations use decimal arithmetic before conversion
for SQLite REAL storage; no exchange tick-size rounding is applied.

`PaperExecutor` creates positions; `PositionMonitor` responds to subsequent option
prices. Known seeded option symbols and any symbol referenced by a persisted
trade are routed to the position monitor rather than the underlying level monitor.
This also works for old trade symbols that are absent from the current seed.
Other instrument names continue through level detection.

Use the exact `option_symbol` returned by `GET /trades` (the example symbol here
is illustrative; startup dates determine your seeded symbols):

```sh
curl -X POST http://127.0.0.1:8000/simulation/tick \
  -H 'Content-Type: application/json' \
  -d '{"instrument":"SIM-NIFTY-2026-09-22-25050-PE","price":90}'
```

Option ticks update the current simulated quote and monitor all matching OPEN
PAPER trades, without the latest-100 display limit. `price <= initial_stop_loss`
closes at the received price. A gap to 85 closes at 85, not 90. Zero is accepted;
negative option prices return 422. Underlying ticks never close option positions.

The close saves `exit_price`, UTC `exit_time`, `exit_reason=STOP_LOSS`,
`realised_pnl=(exit-entry)*quantity`, `realised_pnl_percentage=(exit-entry)/entry*100`,
and `status=CLOSED`. An entry at 100, exit at 85, quantity 10 yields −150 and −15%.
The percentage uses the entry premium, not the underlying level or account balance.
Results exclude fees and additional slippage assumptions.

`app/trade_events.py` defines `TradeEventRepository`. POSITION_OPENED is saved
with entry; STOP_LOSS_HIT and POSITION_CLOSED are saved with the close. Inspect
chronological events at `GET /trades/{trade_id}/events`. The Trades page shows
open and closed trades, initial stops, exit prices/reasons, and realised P&L.
Use Refresh after sending ticks from another client.

The position monitor uses a SQLite write transaction and only updates trades
still marked OPEN. The trade row and both exit events commit or roll back together.
A unique index on `(trade_id, event_type)` for lifecycle/activation events prevents duplicates; trailing updates have a separate unique `(trade_id, current_stop)` index. Repeated
stop ticks, later lower ticks, app restarts, or a repeated execution request cannot
close or reopen the same position again. Entry-result records describe the entry
attempt; use `/trades` for current position status.

`app/trade_schema.py` migrates the previous OPEN-only trade schema transactionally,
preserving IDs, entry records, and the option-selection uniqueness constraint.
It backfills initial stops from the configured percentage at first migration.
Historical POSITION_OPENED events reconstructed from entries have
`reconstructed=true`; newly emitted events have false. Restarting later neither
recalculates stops nor duplicates events. Existing trades, stops, exits, and events
are SQLite-backed; monitoring does not depend on an in-memory position cache.

## Trailing stop and breakeven protection

New trades snapshot these environment settings at entry:

| Setting | Default |
| --- | --- |
| `TRAILING_STOP_PERCENTAGE` | `10` |
| `BREAKEVEN_PROTECTION_ENABLED` | `true` |
| `BREAKEVEN_ACTIVATION_PERCENT` | `10` |
| `BREAKEVEN_LOCK_PERCENT` | `0` |

Trailing percentage must be strictly between 0 and 100; activation/lock percentages
must be finite and nonnegative. Initial stop settings still apply. Changing settings
only affects new trades; existing positions retain their saved configuration.

Every open trade stores `highest_price`, `current_stop_loss`, and
`breakeven_activated`. The high starts at entry and never falls. On each option tick:

```text
highest = max(saved highest, current price)
trailing = highest × (1 − trailing percentage / 100)
activation threshold = entry × (1 + activation percentage / 100)
protected stop = entry × (1 + lock percentage / 100), once activated
current stop = max(initial stop, previous current stop, trailing, protected stop if active)
```

Breakeven activates only when enabled and the high reaches the threshold. Activation
remains recorded even after prices fall. With entry 100 and defaults, prices 105,
110, and 120 move the stop to 94.5, 100, and 108. A fall to 115 leaves it at 108;
a tick at 108 closes. Lock 1% protects 101 instead of 100 after activation.
The monitor updates protection first, then compares the tick to the effective stop.
All exits retain `STOP_LOSS` as their reason and use the received price for P&L.

`TRAILING_STOP_UPDATED` records the tick price plus previous/new effective stops,
only when trailing is strictly stronger than all other candidates. Breakeven-only
increases do not emit a trailing update; ties are credited to protection.
`BREAKEVEN_PROTECTION_ACTIVATED` occurs exactly once per trade, including activation
when trailing already supplies a higher stop. Read these at `/trades/{trade_id}/events`.

The monitor reads persisted state under the existing SQLite write transaction.
Repeated ticks neither raise the high/stop nor reactivate protection. Stop-change,
activation, and exit writes commit together, or all roll back on failure. Unique
partial indexes prevent repeated activation/lifecycle events and repeated trailing
updates to the same stop. Closed trades are excluded from monitoring.

`app/trailing_schema.py` upgrades older databases transactionally. Existing entries
start with entry as their high and initial stop as their effective stop; previously
unrecorded highs are unavailable. Existing trade/event IDs, stops, and exits are
preserved. Migration does not generate trailing/activation events. Subsequent
restarts preserve all recorded highs, stops, flags, and per-trade settings.

The Trades page displays the high and effective/initial stops next to entry price,
and shows breakeven status as Waiting, Active, or Disabled.

## Daily paper-trading window

Set these environment variables before starting the backend (Asia/Kolkata):

```sh
export TRADING_START_TIME=09:15
export NEW_TRADE_CUTOFF_TIME=15:15
export MANDATORY_EXIT_TIME=15:25
```

These are the defaults. Start and cutoff are inclusive; settings must satisfy
start <= cutoff < mandatory exit. Outside the entry window, signals and option
selections can still be evaluated, but no new paper trade is created. Entry
failures are visible on the Trades page. Existing positions remain monitored.

`app/trading_time.py` owns the clock rules and an asyncio mandatory-exit task.
It checks at startup and every second, with an additional check after ticks.
The app must be running for timely exits; an overdue position is closed on
restart, including positions left open on an earlier date. Exit time records
the actual processing time. No scheduler library, holiday calendar, or live
broker integration is used.

Latest simulated option quotes are saved in SQLite's `simulated_option_quotes`
table and restored at startup. Mandatory exits use that quote (the observed
entry price is the fallback for legacy trades). The exit and both trade events
are one transaction. Failed periodic checks are logged and retried. The Trades
page displays **Market closing exit** with its normal realised P&L.

Run verification:

```sh
cd backend
.venv/bin/python -m pytest -q
cd ../frontend
npm test
npm run build
```

## Paper trading report and history

Open the **Report** tab for all-time PAPER performance, filtered trade history,
and a trade's persisted event timeline. Use Refresh to reload results; history
filters apply only to the history table, not the all-time report.

- `GET /reports/paper-trading`: total/open/closed trades, wins, losses,
  breakeven count, win rate, gross profit/loss, net P&L, average and maximum
  profit/loss, and profit factor. Calculations live in `app/paper_report.py`.
- `GET /trades/history?page=1&page_size=20&status=CLOSED&instrument=NIFTY`:
  PAPER history with `items`, `total`, `page`, and `page_size`. Status and
  instrument are optional; instrument matches exactly after trim/uppercase.
  Page size is 1–100. Newest entry time first, with descending trade ID as a
  tie-breaker. The existing `GET /trades` list remains compatible.
- `GET /trades/{trade_id}`: `{trade, events}` read in one SQLite snapshot;
  returns 404 for a missing paper trade. Events are ordered by timestamp then
  ID, including every persisted event rather than a recent-events limit.

Only CLOSED trades contribute realised performance. Positive P&L is a win,
negative P&L is a loss, and zero is breakeven. Win rate is winners / (winners + losers)
× 100, or zero when there are neither. Breakeven trades are excluded. Total trades includes OPEN positions,
which remain visible in history with unknown exit/P&L displayed as a dash.

Gross/average/maximum loss are positive loss magnitudes. Net P&L is gross profit
minus gross loss. Averages use winning or losing trades respectively. Profit
factor is gross profit / gross loss; when gross loss is zero it is JSON `null`
and displayed as N/A (including profitable reports with no losses).

The timeline displays recorded trade events and marks legacy reconstructed
events. Level triggers, signal acceptance, and option selection are not stored
as trade events and are not fabricated for this view; signal and selection IDs
are shown for reference. Reporting introduces no changes to execution rules.


## Backtesting V1

Open **Backtest** in React. Select NIFTY and level 25000 to run the bundled
**NIFTY demo · 14 Sep 2026**, or upload a local JSON array. Expand settings to
configure lookback/distance, ITM depth, lots, stops, breakeven protection,
trading times, and an optional timestamp range. Input timestamps must include
an offset; trading-window times use Asia/Kolkata.

```http
POST /backtests/run
Content-Type: application/json

{"instrument":"NIFTY","levels":[25000],"fixture":"nifty-demo"}
```

Alternatively provide `dataset` instead of `fixture`:

```json
{
  "instrument": "NIFTY",
  "levels": [25000],
  "dataset": [
    {"timestamp":"2026-09-14T09:59:00+05:30","instrument":"SIM-NIFTY-2026-09-21-25050-PE","price":100},
    {"timestamp":"2026-09-14T10:00:00+05:30","instrument":"NIFTY","price":24900},
    {"timestamp":"2026-09-14T10:01:00+05:30","instrument":"NIFTY","price":25000},
    {"timestamp":"2026-09-14T10:02:00+05:30","instrument":"SIM-NIFTY-2026-09-21-25050-PE","price":90}
  ]
}
```

The POST runs replay and returns its UUID, status, performance metrics, trades,
signals, option selections, entry results, and trade events. Read the saved
result later with `GET /backtests/{id}`. Runs use separate
`backend/backtests/{id}/results.sqlite3` files, including the input/settings and
result snapshot. There is no shared PAPER price cache, history, trade state,
or background wall-clock scheduler inside replay. Results survive app restart;
interrupted RUNNING runs are not automatically resumed in V1.

`HistoricalMarketDataProvider` sorts ticks by timestamp (stable source order
for ties), and `BacktestRunner` injects historical time into the existing
services. It advances through mandatory-exit deadlines before later ticks, so
future option quotes cannot affect earlier exits. A quote at exactly a deadline
is processed after that deadline's timer event. An explicit `end_time` can
advance past the final tick to exercise the normal mandatory exit. Otherwise,
OPEN positions stay OPEN if the dataset ends early, and are excluded from
realised performance. Range filtering is inclusive and does not preload
quotes or strategy history from before `start_time`.

V1 supports 1–10,000 records and up to 100 level inputs for one underlying
(NIFTY or BANKNIFTY). Duplicate level inputs are collapsed. Local data is JSON;
CSV ingestion is not included. The option universe is synthetic, seeded from
the first included tick's Asia/Kolkata date, with expiries +7/+14 days and the
existing fixed strike ranges and test lot sizes. These are not real exchange
contracts. Include matching synthetic option symbols and quotes in the data;
underlying-only data can create signals/selections but cannot create trades.
No premiums are derived from the underlying. Expired/unavailable contracts
retain the shared selector's failure behavior; V1 does not roll the universe
forward or integrate an exchange calendar.

Settings use the same defaults and validation as paper trading, with
`trade_mode` fixed to `BACKTEST`. This is deterministic replay of supplied
observations, not a model of historical spreads, liquidity, fees, or fills.
There are no charts, sweeps, live orders, or broker historical-data calls.


## Zerodha Integration V1 — market data, PAPER execution

Install backend requirements, then configure environment variables in the shell
that starts FastAPI (no credentials belong in source files or the frontend):

```sh
export MARKET_DATA_MODE=ZERODHA
export TRADE_MODE=PAPER
# Set ZERODHA_API_KEY and ZERODHA_API_SECRET securely in your environment.
# Optionally set ZERODHA_ACCESS_TOKEN for an existing current session.
cd backend
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Default MARKET_DATA_MODE is SIMULATED. Restart the backend to change modes.
Use a single app process for one broker session. The default development app
is local-only; these connection-management endpoints are not a public hosted
authentication system. Environment files are ignored by Git and are not loaded
automatically. The connector exposes no broker order methods.

Configure the registered callback and frontend return URL:

```sh
export ZERODHA_REDIRECT_URL=http://127.0.0.1:8000/zerodha/callback
export FRONTEND_URL=http://127.0.0.1:5173
```

Register that exact callback URL in the Kite developer console for your API key.
Kite chooses the callback from its registered app configuration; the environment
variable does not update the developer console. Keep the path `/zerodha/callback`.
The frontend URL is the app's base URL, without `/connection`.

Open **Connection** in React:

1. Click **Connect Zerodha**. The backend validates its API key and redirects
   your browser to Kite. Complete password/OTP login on Zerodha yourself.
2. Kite returns the request token to the backend callback. The backend validates
   the browser-bound login attempt, exchanges the token using its API secret,
   and saves the session. No manual token copy/paste is needed.
3. You return automatically to frontend `/connection`, showing **CONNECTED**.
   Click **Sync instruments** to start the price feed. Authentication status is
   separate from the WebSocket's connection state, which is also displayed.
4. Add enabled NIFTY/BANKNIFTY levels. The watchlist displays received prices;
   dashboard data refreshes every five seconds. Simulation input is hidden and
   its API is blocked while ZERODHA mode is active.

Connection authentication states are NOT_CONNECTED, AUTH_REQUIRED, CONNECTED,
and ERROR. Callback failures return to Connection with ERROR and a retry button.
Use the same browser for the entire login; attempts expire after ten minutes.
The backend starts login on the configured callback hostname so localhost versus
127.0.0.1 does not lose the HttpOnly login cookie.

`KiteConnector` handles the login URL, SHA-256 token exchange, instrument master,
and selected-contract LTP only. API key/secret are read on the backend; React
receives only the backend login URL. Kite's redirect necessarily includes its
public API key, but never the API secret or access token.

A successful exchange writes `<database-stem>.zerodha-session.json` beside the
backend database, atomically with owner-only permissions (0600). This local
single-user file contains the access token, API-key fingerprint, and expiry;
it is **not encrypted**, is ignored by Git, and is never served by the app.
Treat it as a credential. Restarts restore the session for the matching API key;
expired sessions are discarded and rejected HTTP sessions delete the saved
credential. An environment access token takes precedence over the saved file.
A restored or environment session attempts instrument sync on startup.

Access tokens remain redacted in memory and absent from API responses.
Callback query strings are stripped from Uvicorn access logs, and callback
redirects use no-store/no-referrer headers. HTTP errors are sanitized and
streaming failures log states without credential-bearing URLs or exceptions.
External reverse proxies must also avoid recording callback query strings.
The backend remains local-only; this is not a multi-user authentication system.

`ZerodhaInstrumentService` filters the master to NSE NIFTY 50 / NIFTY BANK and
NFO NIFTY/BANKNIFTY CE/PE contracts. Normalized metadata (tokens, exchange,
symbol, underlying, segment, type, strike, expiry, lots and tick size) is stored
in SQLite keyed by exchange and symbol, with a last-successful-sync timestamp.
Invalid syncs leave the previous master intact. Sync again each trading day;
V1 does not add a scheduling framework. Token mappings are replaced and the
socket restarted after sync, since derivative tokens can be reused.

OptionSelector receives ordinary OptionContract records, with strike spacing
inferred from the normalized strikes. It contains no Kite objects or calls.
Before paper entry, an async read-only LTP request fetches the selected option's
premium outside the write transaction. No synthetic price seed is used in this
mode; a missing/invalid quote produces the existing entry failure. This avoids
subscribing to the entire option chain merely to discover an entry price.

The asyncio ZerodhaMarketDataProvider subscribes in LTP mode to enabled index
levels and contracts for OPEN PAPER positions. It converts binary NSE/NFO paise
quotes into PriceTick, then uses the same SimulationFlow, LevelMonitor,
SignalEngine, OptionSelector, PaperExecutor and PositionMonitor. Text updates,
heartbeats, malformed frames, unknown/unsubscribed tokens, and invalid prices
are not treated as strategy ticks. PriceTick uses receipt time as before.

Subscription differences are sent after ticks and at one-second idle checks.
New positions gain an option subscription; closed positions and disabled levels
lose it when no longer required. Reconnect uses delays from one to thirty
seconds and sends the entire current subscription set on a fresh socket.
Disconnect gaps are not filled in V1; the strategy resumes with the next received
price. Existing mandatory-exit rules still use the latest stored observation.
Choose source changes with positions in mind: synthetic symbols have no Zerodha
token, and a removed/expired contract cannot receive live updates from a new
master. All entries remain PAPER and the app refuses ZERODHA + LIVE/BACKTEST.

Connection API:

- GET /connection — mode, PAPER execution, session availability, socket/sync
  states, last successful sync, and latest received prices; no secrets.
- GET /zerodha/login — validate configuration, bind a login attempt, and redirect to Kite.
- GET /zerodha/callback — exchange and persist the session, then redirect to frontend /connection.
- GET /zerodha/login-url — compatibility endpoint returning the backend login URL.
- POST /zerodha/session — optional development-only manual request_token fallback;
  persists the resulting session without returning the access token.
- POST /zerodha/instruments/sync — refresh filtered master and reconnect.

Protocol references: [Kite authentication](https://kite.trade/docs/connect/v3/user/),
[instruments and quotes](https://kite.trade/docs/connect/v3/market-quotes/),
[WebSocket framing and subscriptions](https://kite.trade/docs/connect/v3/websocket/).
Tests use fake connectors/sockets and HTTP mocks; automated tests never log in
or connect to Zerodha. Backtests continue to use their isolated synthetic inputs.


If login returns ERROR, the Connection page now reports a fixed diagnostic code
and next step, without broker tokens or raw exception details. In particular,
API_SECRET_MISSING means ZERODHA_API_SECRET was not exported in the terminal
that started Uvicorn. Stop the full Uvicorn reloader, set both credentials from
the same Kite app, and restart; Python auto-reload does not reread shell exports.


## AWS Lightsail deployment

See [deploy/README.md](deploy/README.md) for Ubuntu, Nginx, systemd, external SQLite storage, HTTPS, and deployment on push to main. No Docker is required.
