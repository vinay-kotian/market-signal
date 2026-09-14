# Market Signal

Market Signal provides a FastAPI backend and React frontend for SQLite-backed
levels, simulated price ticks, and approach signal analysis.

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
recent signals. The Levels page supports adding, editing, toggling, and deleting
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
