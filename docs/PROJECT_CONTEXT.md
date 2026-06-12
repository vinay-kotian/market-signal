# Market Signal Project Context

Last updated: 2026-05-18

## Product Direction

Market Signal is a FastAPI + SQLite paper-trading platform for options buying strategies using Zerodha Kite market data.

The immediate goal is to get the app running end to end before investor/job-seeker polish. Keep the code simple, readable, and modular.

## Current Operating Rules

- Paper trading only for now.
- `TRADING_MODE=PAPER`
- `ENABLE_LIVE_TRADING=false`
- Options buying only.
- Fresh option selling is forbidden.
- Lot size defaults to `1`.
- Zerodha instrument sync should include `NFO` and `BFO` options.
- Instrument sync should filter to option contracts (`CE`, `PE`) when Zerodha provides `instrument_type`.
- Do not store raw ticks in the database.
- Latest ticks live in memory through the tick cache.
- Historical data can be fetched from Zerodha later.

## Level Strategy Rules

- Daily levels are set per instrument and trading day.
- Past trading days must not be editable.
- Only one `ACTIVE` level set is allowed per instrument per day.
- `L0` is stoploss.
- `L1` is entry.
- `L2+` are target/checkpoint levels.
- `L1` entry is valid whether price comes from below or above.
- Capture entry approach direction:
  - `BELOW_TO_L1`
  - `ABOVE_TO_L1`
  - `UNKNOWN_AT_LEVEL`
- Upper targets do not immediately sell.
- When upper targets are reached, keep testing higher targets and tighten trailing stoploss.
- EOD square-off closes open paper positions at latest available in-memory price.

## Important UX Decision

Saving the same instrument/day twice must **not** silently update.

Expected behavior:

- `Save Today's Levels` creates only when no active setup exists for that instrument today.
- If active levels already exist, show a clear error:
  `Levels already exist for this instrument today. Use Edit to update them.`
- Updates must happen only through explicit `Edit` from `Today’s Level Sets`.

This was discussed after a `409 Conflict`; do not reintroduce automatic update-on-POST.

## Current UI Shape

Frontend is currently a static `frontend/index.html` using Tailwind + daisyUI CDN, not React yet.

Operator Setup:

- Typeahead instrument selection from synced Zerodha instruments.
- Instrument search supports exchange filtering: All, `NFO`, `BFO`.
- Instrument token is hidden from the user.
- No manual "Create Instrument" button in the UI.
- Level editor starts blank with:
  - `L0` Stoploss
  - `L1` Entry
  - `L2` Target
- `+ Target` adds `L3`, `L4`, etc.
- Saved levels should be visible as colored cards/pills.
- `Today’s Level Sets` should show instrument symbol, not `#instrument_id`.
- Active level sets should have `Edit` and `Delete`.
- Today’s level rows should stay sleek and single-line where possible, not large boxy cards.
- Live Instrument Monitor should show all instruments with active levels today, including latest price when a tick has arrived and `No tick` otherwise.
- Browser receives live price updates through backend WebSocket `/ws/prices`.
- Zerodha stream ticks and mock ticks both publish realtime tick messages after `process_tick`.

## Zerodha Flow

- `GET /zerodha/login` redirects to Kite login.
- `/zerodha/callback` stores access token in SQLite.
- After callback, the app should return to the frontend.
- Instruments should sync automatically after Zerodha connection.
- Automatic sync should include both `NFO` and `BFO` option contracts.
- Manual sync remains a fallback.

## Current Git State

Branch: `development`

Last pushed commit:

- `132c105 Refine operator setup and level management`

Uncommitted work exists after that commit:

- Backend level-set response includes nested instrument data.
- Level-set list/update API typing was cleaned up with optional filters.
- New focused test: `backend/tests/test_level_sets_api.py`.
- UI changes:
  - level-set cards instead of tiny table rows
  - saved setup preview
  - edit loads levels into Operator Setup
  - duplicate save shows a clear error and does not update

Before continuing tomorrow, inspect:

```bash
git status -sb
git diff --stat
```

## Validation State

Latest validation after the duplicate-save/error-message fix:

```bash
python3 -m pytest
```

Result:

```text
25 passed
```

## How To Run

Backend:

```bash
uvicorn backend.app.main:app --reload
```

Frontend:

```bash
cd frontend
python3 -m http.server 3000
```

Open:

```text
http://127.0.0.1:3000
```

If frontend changes do not appear, hard refresh the browser.

## Next Useful Steps

1. Manually test the full level workflow in the browser:
   - select synced instrument
   - enter L0/L1/L2
   - save once
   - verify colored saved setup appears
   - try saving again and confirm proper duplicate error
   - click Edit and confirm update works
2. Improve visible status/errors so they are not only tiny text in the top action bar.
3. Show instrument symbol in Paper Trades instead of `#instrument_id`.
4. Verify Zerodha stream subscribes only to instruments with active level sets.
5. Add clearer paper position UI: entry direction, entry price, trailing stoploss, checkpoints hit, exit reason.
