# Contextual help and troubleshooting

## Scope and architecture

This checkout had no Help Center before this feature. The implementation supplies
the shared registry, global Help & Guide tab, searchable category navigation,
individual `/help/<category>/<topic>` routes, article contents and related links,
and contextual decision dialogs. Phase 7 uses the same articles as field help.

- `frontend/src/help/registry.js`: verified definitions, defaults, formulas,
  illustrative examples, configuration/effective-time notes, related topic IDs,
  search and field-to-topic lookup. There are no external documentation requests.
- `frontend/src/help/reasons.js`: exact machine-code mapping and deterministic
  projections of recorded data. Arbitrary error text is never classified by
  substring. Unknown codes link to the explicit unavailable-details article.
- `ContextHelp.jsx`: accessible dialog outside clipped tables/forms, keyboard
  focus containment/restoration, Escape/outside dismissal, full-guide links.
  Buttons are type=button and prevent parent form, checkbox, row and summary
  actions. Modified guide-link clicks retain ordinary browser behaviour.
- `HelpCenter.jsx`: shared articles and search. Deep links work on first load,
  in-app navigation and browser history. Help uses the existing SPA route fallback.

All explanations are code-driven; no model, remote assistant, brokerage order or
strategy configuration update is involved.

## Audit and documentation inventory

The audit covered application pages/forms, event timelines/markers, persisted
models, signal/entry/exit logic, option selection, level arming, ATR data,
progressive protection, trading windows, report metrics and historical replay.
The registry contains articles under all twelve requested categories. Key
component coverage:

| Surface | Contextual help / evidence | Registry topics |
|---|---|---|
| Dashboard watchlist / LTP | Latest received observation, freshness and frozen strategy interpretation | `dashboard/quotes`, `settings/strategy-selection` |
| Dashboard / Levels states | Current displayed underlying price, current index threshold and derived live distance; explicitly separate from original arming | `signals/arm-distance`, `levels/lifecycle` |
| Level form | Price/touch-cross, calendar-date and enabled-state semantics, timeframe metadata | `signals/touch-cross`, `levels/lifecycle`, `levels/timeframe` |
| Signal table / backtest signal results | Stored rejection/acceptance code, approach distance/direction, applied filter and lookback snapshot, sample count | `signals/approach` |
| Option-selection results | Exact supported-contract failure code and verified selection rules; no guessed missing quote | `entries/option-selection` |
| Entry failures / backtest entry results | Stable reason, actual applied entry window, attempted time/price, strategy selection and history/risk evidence when present | `entries/eligibility`, `entries/time-window`, `atr/wilder`, `atr/risk-guard` |
| Trades / report trade rows | Selected frozen exit strategy, initial stop, Strategy 3 source/ATR/fallback, recorded exit reason | `settings/strategy-selection`, `trades/initial-stop`, `atr/fixed-stop`, `atr/fallback` |
| Report trade events | Event-time stop/price, frozen activation thresholds; distinguish event metadata from final trade values | `trades/trailing-stop`, `trades/breakeven`, `trades/progressive` |
| Charts / selected marker detail | Exact marker code and values, frozen trade context, recorded arm threshold and signal snapshot where recorded | `dashboard/charts`, corresponding event articles |
| Backtest saved results / timeline / warnings | Structured warning/error codes, original messages, resolution, execution model, frozen partial-entry policy and actual run/trade context | `backtesting/data-quality`, `backtesting/candle-limitations` |
| Backtest fee field / configuration reference | Fee scope and field-to-registry help | `backtesting/costs`, settings/strategy-specific topics |
| Reports | Metric definitions, scope and net/gross/risk semantics | `reports/metrics`, `reports/r-multiple`, `trades/pnl` |
| Settings | Exit selections, individual ATR/Strategy 3/Legacy/progressive configuration fields, trading-time fields, index distance, notifications | settings/strategy-specific articles via `fieldTopic` |
| Connection | Authentication and socket state, instrument sync, actual credential-free error codes/messages and timestamps | `zerodha/connection`, `zerodha/instruments` |
| Help & Guide | All categories, searchable rules, defaults, related articles, illustrative examples and glossary | Full registry |

## Additive backend evidence

Existing reason strings, field meanings and trading outcomes remain unchanged.
New nullable/empty-safe audit fields are added; existing snapshots are not
rewritten and old records default to empty context.

- Signals gain `decision_context` with applied `settings_snapshot` and
  `approach_sample_count`.
- Trades and entry results gain `decision_context`: evaluated timestamps/window,
  selected strategy/configuration/source, actual available/required candle count
  and candle duration where checked, attempted entry price, initial stop and risk
  where calculated. The original `settings_snapshot` contract is preserved.
- ATR data exposes `completed_candle_count` and `required_candle_count` without
  changing Wilder calculation. Strategy 3 entry plans expose
  `pre_entry_candle_count` and `valid_tr_count`; effective ATR sample count remains
  separate. Risk rejection exceptions retain the same ValueError messages and
  additionally carry the already-calculated risk/stop for audit.
- Arming audit events from create/edit/initial-arm include the evaluated
  `initial_arm_distance_points`. Chart signal and trade events expose recorded
  context alongside existing fields.
- Historical bundles/results keep the existing `warnings` / `data_warnings`
  strings and gain indexed `warning_details` (`code`, `message`, `context`,
  `warning_index`). Loader codes are `OPTION_HISTORY_UNAVAILABLE` and
  `ATR_WARMUP_UNAVAILABLE`. No diagnostic matching against human messages occurs.
- Incomplete replays retain their existing status/message and gain
  `INCOMPLETE_POST_ENTRY_CANDLES` or `INCOMPLETE_EXIT_COVERAGE` error codes. Other
  replay exceptions use the honest generic `BACKTEST_REPLAY_ERROR` classification.
  Warning metadata is excluded from the market dataset hash.

## Accuracy boundaries and remaining gaps

- Older signals/failed entries may lack thresholds, history counts, selected
  override source or attempted risk. The dialog says these are unavailable;
  current configuration/defaults never backfill old events. ATR sample count + 1
  is not used to invent a candle count because gaps can invalidate that inference.
- Some historical rearming audit events do not carry the evaluated distance.
  They retain an unavailable threshold; current level-table quotes/settings are
  explicitly labelled current observations/configuration.
- Many older ATR/Legacy protection events lack their event-time highest premium
  or all competing stop candidates. The final trade high/stop is not substituted.
  Trailing candidate arithmetic is shown only from sufficient recorded inputs and
  remains labelled derived, not identified as the winning candidate.
- Backtest timeline highs can be reconstructed by the existing timeline service;
  contextual help labels them as timeline-reported and does not derive a precise
  candidate from those reconstructed highs.
- Generic PAPER mandatory exits can use changed time settings and cached/fallback
  quotes. An entry snapshot does not prove the applied exit-time deadline or quote
  freshness. Strategy 3's separate frozen cutoff is shown when available.
- Free-text broker/network failures and old backtest warnings without a machine
  code receive general troubleshooting, their original message and any recorded
  connection/run evidence. An unknown code never acquires a guessed diagnosis.
- OHLC explanations describe conservative priority and partial-entry assumptions;
  they do not promise intrabar ordering or executable threshold fills.
- Some page headings/metrics use a shared section-level guide rather than an icon
  beside every repeated numeric cell. Every requested decision class has a
  contextual entry point; search also exposes glossary, sizing, classification and
  related reference articles. Future settings should be added to `fieldTopic`
  and their existing article or a new registry topic.

## Validation

`frontend/src/help.test.js` checks registry/link integrity, search, machine-code
mapping, unknown IDs/codes, old/missing evidence, frozen calculations, current vs
recorded values, exit-reason safety, focus trapping/restoration, Escape/outside
clicks, form/checkbox/row isolation, deep links/history and trade-table integration.
`backend/tests/test_decision_context.py` checks persistence, frozen metadata,
ATR vs Strategy 3 history requirements, guard-rejection values, selection source,
incomplete replay codes and old-database migration without fabricated backfill.
Existing execution/replay tests continue to validate the underlying outcomes.
