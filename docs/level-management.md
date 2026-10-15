# Level dates, ordering and timeframes

Level lists use ascending numeric price, then ID for stable ties. Dashboard and Levels retain their instrument/date filters after refresh and streamed updates. Strategy evaluation retains its original ID order so changing presentation order does not change which signal is considered first.

## Editing dates safely

`PUT /levels/{id}` accepts `level_date` along with instrument, price, enabled and timeframe. Omitted dates retain the stored date. Calendar strings must use `YYYY-MM-DD`; timestamps and numeric dates are rejected.

A non-expired level with no persisted signals can move to today or a future date. A date edit that collides with another level returns HTTP 409. Expired levels retain the existing audit restriction and cannot be edited or deleted. Any existing signal, including a rejected signal or one linked to an open/closed trade, blocks date changes with HTTP 409; create a new level instead. Edits wait for in-flight market processing, including asynchronous option quote preparation, before checking eligibility.

Other existing editable attributes remain editable on non-expired levels. Updating a level never rewrites a stored signal or trade. The existing arming calculation still applies on update, and future dates remain ineligible for signals until their date. Updates publish `LEVEL_UPDATED` and the UI refreshes its snapshot.

## Timeframe metadata

`timeframe` is a nullable structured duration, such as `5m`, `15m`, `1h` or `1d`. These four choices are always supported. Add choices with a comma-separated backend environment setting, for example:

```sh
LEVEL_TIMEFRAMES=30m,4h,1w
```

Durations use positive integer values followed by `m`, `h`, `d` or `w`. `GET /levels/timeframes` exposes configured choices to the form and Reports. Unsupported choices are rejected. A previously saved duration remains readable if an extra configured choice is later removed; unchanged updates retain it.

A missing/null timeframe means **Not recorded**. Old clients may omit it when creating levels. Updates that omit it preserve the existing value; explicit null clears the level's value. There is no inferred default for historical data.

The duplicate identity is `(instrument, level_date, price, timeframe)`, including null as one distinct timeframe value. Creation and identity-changing edits check duplicates in a SQLite write transaction. External ingestion uses the same identity and retains its idempotency handling. Existing duplicate rows are retained by migration, and non-identity edits remain available.

The monitor copies timeframe into each generated signal, and PAPER/BACKTEST execution copies the signal's timeframe into an independent trade entry column. Reports read this entry snapshot, never the current level. This metadata does not change approach, arming, entry or exit rules, ATR candle selection, or any broker behavior. In particular, the existing **one open trade per instrument** restriction still applies: same-price levels with different timeframes can create separate signals, but simultaneous entries can receive `ACTIVE_TRADE_EXISTS`.

## Reports and backtesting

Trade history, trade detail and backtesting trade tables show Timeframe alongside the level. Historical null values display Not recorded and export as an empty CSV cell. CSV exports include a `timeframe` column after `trigger_level`.

Report summaries, history, matching trade IDs, strategy comparison and CSV accept `timeframe=5m` (or another duration). `timeframe=UNKNOWN` filters for null snapshots. Omitting the filter includes all values. Reports provides a selector that applies to these scopes together.

Existing backtest numeric input remains supported:

```json
{"levels": [25000, 25100]}
```

Per-level structured input supports mixed or identical prices with different timeframes:

```json
{"levels": [{"price": 25000, "timeframe": "5m"}, {"price": 25000, "timeframe": "1h"}]}
```

Duplicate price/timeframe pairs are deduplicated in request order. In the Backtest form, enter `25000@5m` and `25000@1h` on separate lines, or use spaces/commas. Plain numbers continue to mean timeframe not recorded. Saved results and event payloads retain the metadata; previously saved reports display their absent values as Not recorded.

## Migration

Restart the backend to run its existing transactional, idempotent startup migration. It adds nullable `timeframe TEXT` columns to levels, signals and trades and lookup indexes. The existing daily-level table rebuild also preserves timeframe when present. No separate migration command is required.

No existing rows are backfilled, merged or deleted; IDs, timestamps, signals, trade snapshots and events retain their values. Existing database files in this repository were not modified. Previously saved isolated backtest databases remain historical artifacts; new runs initialize the expanded schema.

## Changed files

Backend:

- `backend/app/timeframes.py`: duration type, configured choices and validation.
- `backend/app/models.py`, `backend/app/level_schema.py`, `backend/app/database.py`: level input and backward-compatible schema initialization.
- `backend/app/level_repository.py`, `backend/app/levels.py`, `backend/app/external_levels.py`: safe date edits, duplicate identities, ordered level APIs and timeframe choices.
- `backend/app/events.py`, `backend/app/level_monitor.py`, `backend/app/signal_engine.py`, `backend/app/signal_models.py`, `backend/app/signal_repository.py`: timeframe propagation and serialized API edits.
- `backend/app/paper_executor.py`, `backend/app/trade_models.py`, `backend/app/trade_repository.py`: frozen entry timeframe and history scope.
- `backend/app/report_csv.py`, `backend/app/report_filters.py`, `backend/app/trade_routes.py`: timeframe in CSV and shared report filters.
- `backend/app/backtests.py`, `backend/app/backtest_events.py`: compatible structured inputs and replay metadata.

Frontend:

- `frontend/src/TimeframeSelect.jsx`, `frontend/src/LevelForm.jsx`: shared configured selector and editable dates.
- `frontend/src/main.jsx`, `frontend/src/format.js`, `frontend/src/liveFeed.js`: timeframe columns, numeric sorting and historical trigger matching.
- `frontend/src/TradesPage.jsx`, `frontend/src/PaperReportPage.jsx`, `frontend/src/StrategyPerformanceComparison.jsx`, `frontend/src/reportFilters.js`: report visibility and consistent filters.
- `frontend/src/BacktestPage.jsx`, `frontend/src/backtestInput.js`: timeframe input, reports and per-level timeline selection.

Tests and documentation:

- `backend/tests/test_level_timeframes.py`: date validation, persistence, websocket updates, duplicate/concurrent writes, snapshots, report/CSV filters, migration, in-flight tick editing and LEGACY/ATR replay equivalence.
- `backend/tests/test_daily_levels.py`: replace the old blanket date lock assertion and distinguish an intentionally duplicated fixture by timeframe.
- `backend/tests/test_external_levels.py`, `backend/tests/test_initial_arming.py`: retain arming scenarios using distinct timeframe identities.
- `frontend/src/levelManagement.test.js`: form interaction, configured choices, sorting/filter refresh, reports/details, CSV query scopes and backtest rendering.
- `README.md`, `docs/level-management.md`: API ordering and behavior/migration notes.

## Validation results

- Backend: `.venv/bin/python -m pytest -q --disable-warnings` — 700 passed.
- Frontend: `npm test` — 90 passed.
- Production: `npm run build` — passed.
- `git diff --check` — passed.

The full suites include existing entry, initial/trailing protection, ATR, LEGACY, PAPER and isolated BACKTEST scenarios. Tests use simulated/local data and do not execute live broker orders. No unresolved implementation decisions remain; intentional restrictions are described above.
