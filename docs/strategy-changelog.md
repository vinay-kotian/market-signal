# Strategy changelog

Use an explicit `STRATEGY_VERSION` for each strategy release. Record the date,
behavior change, and relevant validation here before using a new version. Dates
are Asia/Kolkata calendar dates. Versions are not derived automatically from Git.
The complete current rules are in [strategy-rules.md](strategy-rules.md).

## 1.0.0 — 2026-09-18

Initial versioned baseline: records the existing strategy, including the level
rearming correction implemented on 2026-09-17. This entry marks the introduction
of version tracking, not a claim that earlier trades ran version 1.0.0.

- After a successful entry, persist the level as DISARMED. Block another entry
  until the underlying moves at least `level_rearm_distance_points` away from
  that level (default 50 points). Levels rearm independently and retain state
  across restarts. Implementation reference: `4df8d23` (2026-09-17).
- Retain existing approach-distance, option-selection, stop-loss, trailing-stop,
  breakeven, trading-window, and mandatory-exit rules.
- Capture the version and entry settings on new trades and the version on
  backtest results. Classification and RAW/STRATEGY reporting do not alter entry
  or exit rules.
- Validation: 257 backend tests passed after version/classification tracking was
  added. A corrected replay of 2026-09-17 remains pending historical data and
  confirmation of the defect being compared.

Historical trades without recorded provenance remain `UNKNOWN`; do not relabel
those trades as 1.0.0 or reconstruct their settings from today's configuration.

## Next release (unreleased)

No additional rule change is approved or assigned a version yet. For the next
release, record its explicit version (for example, 1.1.0), actual release date,
old and new behavior, settings/default changes, and test/backtest evidence.
Do not set `STRATEGY_VERSION=1.1.0` until that release is defined.

## Corrected replay comparison — 2026-09-17 (pending)

Compare persisted RAW PAPER execution with an isolated BACKTEST of the confirmed
correction. Neither the replay nor its interpretation changes original trades or
events. Record the actual replay version and entry settings with the result.

Required inputs:

- The day's PAPER trades and events, plus any positions carried into that day.
- Timestamped underlying and option prices, including sufficient lookback before
  the first evaluation and observations through the relevant exit times.
- The day's enabled levels, initial rearm state, instruments/contracts, and
  original settings; document any missing or assumed inputs explicitly.
- Confirmation of the defect and correction to replay. The level-rearming fix
  is a candidate, not yet a confirmed explanation for that day's trades.

The server API supplied all 159 PAPER trades for the date; see the
[RAW baseline comparison](strategy-comparison-2026-09-17.md). Historical tick
availability on the server is still unverified.

The local `backend/levels.sqlite3` contains no trades, and the bundled
`nifty-demo` fixture is synthetic data for 2026-09-14. Neither supplies the
2026-09-17 comparison. The current replay runner uses synthetic option contracts
and fresh level state; real contract data or carried state must be supported
faithfully before claiming an equivalent replay. Do not substitute demo prices,
trade events, or latest-only quotes for the missing tick history.

Once inputs are available, record the RAW and corrected results side by side:
trade/open/closed counts, wins/losses/breakeven, win rate, gross profit/loss, net
P&L, and profit factor. Explain changed entries and exits individually. Use the
same time range and metric definitions, and disclose data gaps. An entry-day
cohort includes that day's entries and their recorded outcomes; it is distinct
from P&L realised during that calendar day. State which comparison is used.
