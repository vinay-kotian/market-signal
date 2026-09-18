# Strategy changelog

Dates below are implementation dates in Asia/Kolkata, not deployment dates.
Versions are explicit `STRATEGY_VERSION` labels, never inferred from Git.
Commit links identify the implementation; they do not prove the version label
configured on the server. The current application default is **1.1.0**, but an
explicit environment setting takes precedence. Existing trade versions and entry
settings snapshots are never rewritten when the default changes.

See [strategy-rules.md](strategy-rules.md) for the current rules.

## 1.1.0 — 2026-09-18 — Daily-expiring levels

Implementation: [03c1da9](https://github.com/vinay-kotian/market-signal/commit/03c1da9ddea492d0478b1bcc1e04b19d48c00f88).

Previously, levels could remain eligible across calendar days. Each level now
belongs to one `level_date`, defaulting to today's Asia/Kolkata calendar date.

- Only enabled levels dated today are eligible. ACTIVE levels can trigger;
  DISARMED levels can rearm at the existing distance threshold. The rearming
  tick itself does not trigger another entry.
- Previous-day levels become ineligible at local midnight. Startup, tick
  processing, and a single background check every second persist EXPIRED.
  Execution checks the date again after quote preparation. Disabled levels
  expire too; future-dated levels are ineligible until their date.
- EXPIRED is terminal: no signals, new trades, or rearming. Expired records
  cannot be edited or deleted. Dates cannot be changed to renew a level; create
  a new daily level. Existing positions keep their normal risk monitoring.
- Migration preserves IDs and existing events. Legacy `level_date` derives from
  `created_at` converted to Asia/Kolkata; legacy naive timestamps are interpreted
  as UTC. Old levels are not assigned the migration date.
- Backtests assign levels the first replay record's trading date, after range
  filtering. A later replay date expires them, including an explicit end time
  crossing midnight. Levels are not automatically renewed on subsequent dates.
- The Levels page defaults to today and offers an all-dates history view.
  Apart from daily level eligibility, signal, selection, quantity, rearming
  distance, stop, breakeven, and trading-time rules are unchanged.

Validation at implementation: 270 backend tests and 13 frontend tests passed;
production frontend build passed. Interactive browser verification was unavailable.

Deployment is tracked by the [1.1.0 workflow run](https://github.com/vinay-kotian/market-signal/actions/runs/35305859884).
Set the server's explicit `STRATEGY_VERSION=1.1.0` when deploying this behavior.
A successful code deployment alone does not verify that environment value.

## 1.0.0 — 2026-09-18 — Initial versioned baseline and trade classification

Implementation: [59ad38f](https://github.com/vinay-kotian/market-signal/commit/59ad38f4c7eed2dd4948c68ee3ae86fc45e918cd).

Introduced explicit version tracking around the existing strategy, including the
2026-09-17 rearming fix described below. This release did not introduce a new
entry or exit rule, or retroactively assign a version to older executions.

- New PAPER/BACKTEST trades store a strategy version and entry-time settings
  snapshot. New trades default to VALID and included in strategy metrics.
  New backtest results also persist their strategy version.
- Manual classification changes reporting metadata without changing execution
  fields or persisted trade events.
- STRATEGY is the default PAPER report view and excludes trades whose
  `exclude_from_strategy_metrics` flag is true. RAW includes all PAPER trades.
  The flag controls inclusion independently of the validity label; realised
  performance still uses CLOSED trades only.
- Legacy trade migration preserves records/events and assigns version UNKNOWN,
  status MANUAL_REVIEW, and a LEGACY_UNAVAILABLE snapshot marker. Legacy trades
  remain included until explicitly excluded; current settings are not substituted
  for missing historical provenance.

Validation at implementation: 257 backend tests and 12 frontend tests passed;
production frontend build passed. The [1.0.0 deployment workflow](https://github.com/vinay-kotian/market-signal/actions/runs/35304370825)
completed successfully; the server's explicit version setting was not inspected.

## Before version tracking — 2026-09-17 — Persistent level rearming

Implementation: [4df8d23](https://github.com/vinay-kotian/market-signal/commit/4df8d23db36c112a7a213248d90e414c59924ff0).

A successful entry disarms its level. Further entries are blocked until the
underlying moves at least `level_rearm_distance_points` away (default 50 points).
Rearming requires a later touch/cross for another entry. Rejected signals and
failed entries do not disarm levels. Each level's state is independent and
survives restart. Daily expiry was added later in 1.1.0.

This implementation predates version capture. Do not label its historical trades
1.0.0 solely from their date or infer which code was running from the commit time.

## Corrected replay of 2026-09-17 — Not yet run

The server API supplied 159 PAPER trades for the date in the snapshot retrieved
on 2026-09-18. The [RAW baseline comparison](strategy-comparison-2026-09-17.md)
records those outcomes and the outstanding replay inputs.

A corrected replay still needs historical underlying/option ticks, original
levels/settings and starting state, contract metadata, and confirmation of the
defect and correction being tested. The current runner uses synthetic contracts
and fresh level state; the bundled 2026-09-14 demo is not the flawed day's data.
Do not treat deduplicating recorded trades as a corrected backtest.

No corrected results or performance improvement are claimed. Neither a future
replay nor reclassification should rewrite the original execution history.
