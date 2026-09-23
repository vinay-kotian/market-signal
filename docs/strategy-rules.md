## Initial Stop Loss

When a paper trade is opened, calculate and persist an initial stop loss.

Setting:

`stop_loss_percentage`

Formula:

`initial_stop_loss = entry_price × (1 - stop_loss_percentage / 100)`

Example:

Entry = 100
Stop loss = 10%

Initial stop = 90

If the option price reaches or falls below the effective stop loss, close the trade.

## Trailing Stop Loss

Settings:

`trailing_stop_percentage`

Maintain:

* highest price reached
* current stop loss

Formula:

`trailing_stop = highest_price × (1 - trailing_stop_percentage / 100)`

The effective stop must never move downward.

Use:

`current_stop_loss = max(initial_stop_loss, previous_current_stop_loss, trailing_stop)`

Example:

Entry = 100
Initial stop = 90
Trailing stop = 10%

Price reaches 105:

Trailing stop = 94.5

Price reaches 120:

Trailing stop = 108

If price later falls to 108 or below, close the trade.

## Breakeven Protection

Settings:

* `breakeven_protection_enabled`
* `breakeven_activation_percent`
* `breakeven_lock_percent`

Default behaviour:

* protection enabled
* activation at +10%
* lock = 0%

When the highest option price reaches the configured activation threshold, protect the entry price.

Activation condition:

`highest_price >= entry_price × (1 + breakeven_activation_percent / 100)`

Protected stop:

`breakeven_stop = entry_price × (1 + breakeven_lock_percent / 100)`

Example:

Entry = 100
Activation = 10%
Lock = 0%

When price reaches 110:

Breakeven stop = 100

If lock = 1%:

Breakeven stop = 101

## Effective Stop

When breakeven protection is active:

`current_stop_loss = max(initial_stop_loss, previous_current_stop_loss, trailing_stop, breakeven_stop)`

The stop loss must only move upward.

It must never be reduced when price falls.

## Position Exit

For an OPEN paper trade:

If:

`current_price <= current_stop_loss`

close the trade.

Persist:

* exit price
* exit time
* exit reason
* realised P&L
* realised P&L percentage
* CLOSED status

Possible exit reasons for this milestone:

`STOP_LOSS`, `TRAILING_STOP_LOSS`, `MARKET_CLOSING_EXIT`, or `MANUAL_SQUARE_OFF`.
Manual square-off is a supported stored reason; there is currently no manual
square-off action in this milestone.

## Trade Events

Persist important risk-management events:

* `POSITION_OPENED`
* `TRAILING_STOP_UPDATED`
* `BREAKEVEN_PROTECTION_ACTIVATED`
* `STOP_LOSS_HIT`
* `POSITION_CLOSED`

`BREAKEVEN_PROTECTION_ACTIVATED` should occur only once per trade.

`TRAILING_STOP_UPDATED` should only be recorded when the effective stop actually increases.

Duplicate ticks must not create duplicate exit or risk-management events.

## Trading Times and Mandatory Exit

All configured times are daily Asia/Kolkata wall-clock times:

- `trading_start_time`: 09:15 by default.
- `new_trade_cutoff_time`: 15:15 by default.
- `mandatory_exit_time`: 15:25 by default.

New PAPER entries are allowed at or after start and at or before cutoff.
Outside that window, entry results record `BEFORE_TRADING_START` or
`NEW_TRADE_CUTOFF_REACHED`. Existing positions still receive stop monitoring.

At or after mandatory exit, close all OPEN PAPER positions at the latest
persisted simulated option quote. The observed entry quote is the fallback
for legacy positions. Persist normal exit fields and P&L, with exit reason
`MARKET_CLOSING_EXIT`, plus `MARKET_CLOSING_EXIT_TRIGGERED` and `POSITION_CLOSED`.
At the deadline, market-close exit takes precedence over stop evaluation.

Check on startup, every second while running, and after simulated ticks.
Positions from earlier dates are overdue and close on recovery even before
that day's trading start. No holiday or market-calendar rules apply.
Closed trades are never closed again; trade state and exit events commit together.


Trading start: 09:15
New trade cutoff: 15:15
Mandatory exit: 15:25
Timezone: Asia/Kolkata


## Paper Trading Reporting

Paper trading performance must be calculated only from persisted PAPER trades.

OPEN trades should appear in trade history but must not contribute to realised performance metrics.

A CLOSED trade is classified as:

* WIN when realised P&L > 0
* LOSS when realised P&L < 0
* BREAKEVEN when realised P&L = 0

Breakeven trades should not be counted as wins or losses.

## Paper Trading Metrics

The paper trading report should calculate:

* total trades
* winning trades
* losing trades
* breakeven trades
* win rate
* gross profit
* gross loss
* net P&L
* average profit
* average loss
* maximum profit
* maximum loss
* profit factor

Win rate should be calculated using only completed winning and losing trades.

Example:

Wins = 6
Losses = 4
Breakeven = 2

Win rate:

`6 / (6 + 4) = 60%`

Breakeven trades do not affect win rate.

Profit factor:

`gross_profit / gross_loss`

If there are no losing trades, profit factor should be treated as unavailable rather than forcing an artificial value.

## Trade History

Paper trade history should show both OPEN and CLOSED trades.

Each trade should include:

* instrument
* trigger level
* option
* quantity
* entry price
* entry time
* current status
* stop loss
* highest price
* exit price
* exit time
* exit reason
* realised P&L
* realised P&L percentage

Trade history should support:

* newest-first ordering
* pagination
* instrument filtering
* status filtering

## Trade Event Timeline

Each trade should provide a chronological event history using only events that were actually persisted.

Possible events include:

* POSITION_OPENED
* TRAILING_STOP_UPDATED
* BREAKEVEN_PROTECTION_ACTIVATED
* STOP_LOSS_HIT
* MARKET_CLOSING_EXIT_TRIGGERED
* POSITION_CLOSED

Do not fabricate historical events that were not stored at the time they occurred.

The event timeline should make it possible to understand how a trade moved from entry to exit.

## Reporting Separation

Reporting logic must remain separate from:

* signal generation
* option selection
* execution
* position monitoring

The reporting layer should interpret persisted trading data but must not modify trading behaviour.

## Backtesting

Backtesting must reuse the same strategy logic used by paper trading.

Backtesting should change only:

* market data source
* clock/time source
* execution mode
* storage isolation

Do not create separate trading rules specifically for backtesting.

## Historical Replay

Historical price records must be replayed in timestamp order.

The backtest must not use future prices when evaluating:

* level triggers
* direction
* approach distance
* option entry
* stop loss
* trailing stop
* breakeven protection
* mandatory exit

## Backtest Mode

Backtest trades must use:

`trade_mode = BACKTEST`

BACKTEST trades must not contribute to PAPER trading reports.

Each backtest run must be isolated from:

* PAPER trades
* other backtest runs
* current simulated market state
* current dashboard prices

## Backtest Inputs

A backtest may configure:

* instrument
* levels
* lookback minutes
* minimum approach distance settings
* ITM depth
* number of lots
* stop loss percentage
* trailing stop percentage
* breakeven settings
* trading start time
* new trade cutoff time
* mandatory exit time

## Backtest Results

Backtest results should include:

* total trades
* wins
* losses
* breakeven trades
* win rate
* gross profit
* gross loss
* net P&L
* profit factor
* individual trade history

Use the same reporting definitions as paper trading.

## Open Trades

If the supplied historical dataset ends before a trade reaches an exit condition or mandatory exit time, the trade may remain OPEN.

Do not fabricate a closing price after the historical dataset ends.


## Zerodha Market Data V1

`market_data_mode` selects SIMULATED (default) or ZERODHA. This changes the
instrument source and incoming prices, never signal, selection, or risk rules.
The running Zerodha application must use PAPER execution. No broker order API
is exposed or called. Isolated BACKTEST replay remains separate.

For a valid selection, fetch a read-only option LTP before the SQLite entry
transaction. If the quote is unavailable, preserve OPTION_PRICE_UNAVAILABLE.
Evaluate entry-time eligibility again at execution time after fetching a quote.

Stream enabled monitored indices and option contracts for OPEN PAPER trades.
Refresh required tokens after ticks and during idle periods; rebuild the full
subscription set after reconnect. Reject manual simulation ticks in ZERODHA
mode so the two price sources cannot feed the same running strategy.


## Zerodha Login UX

Connect Zerodha starts backend login and returns through a browser-bound callback.
The backend exchanges the request token and persists the access-token session in
an owner-readable local credential file, outside trading tables. React receives
only authentication status, never the access token or API secret. Authentication
and streaming status are separate. Login does not alter PAPER execution or any
strategy/risk rule.


## Level Rearming

After a trade is successfully entered for a configured level,
that level becomes DISARMED.

A DISARMED level cannot generate another trade.

The level becomes ACTIVE again only when the underlying price
moves at least the configured distance away from the level.

Setting:

level_rearm_distance_points = 50

Rearm condition:

abs(current_price - level) >= level_rearm_distance_points

Example:

Level = 23231
Rearm distance = 50

The level reactivates when price reaches:

23281 or higher

or

23181 or lower

Level state must persist across application restart.

Different configured levels are independent.

## Level State

Each configured level has a persistent state:

ACTIVE
DISARMED
EXPIRED

A successful trade entry changes the level to DISARMED.

Rejected signals or failed trade entries do not disarm the level.

A DISARMED level continues to receive underlying price updates but cannot generate a new signal.

The level becomes ACTIVE again when:

abs(current_price - level) >= level_rearm_distance_points

The re-arming tick only changes the level back to ACTIVE.
A later touch/cross is required for another trade.

Level state must survive application restart.

Each level is independent.


## Daily Level Validity

Each configured level is valid for one trading day only.

A level stores:
- level_date
- status

Possible states:
ACTIVE
DISARMED
EXPIRED

Only levels for the current trading date are eligible for monitoring and trading.

At the start of a new trading day, all previous-day levels become EXPIRED.

Expired levels:
- must not generate signals
- must not create trades
- must not rearm
- remain stored for audit/history

Trading date is determined using Asia/Kolkata.

The trading date is the Asia/Kolkata calendar date of the injected application
clock, including in historical replay. Expiry begins at local midnight, not at
the entry cutoff or mandatory position-exit time. No holiday calendar is added.

Startup and a single background check every second reconcile old levels. Tick
processing also reconciles before evaluating, and execution rechecks the date
after quote preparation. Date checks block stale entries even before the next
background check has persisted EXPIRED. Expiry applies to disabled levels too.

Level dates cannot be edited to renew an old level. Expired levels cannot be
edited, deleted, or rearmed; create a new daily level instead. Their original
IDs, dates, and existing level events remain queryable. Expiring a level does
not close its trades or alter the existing position-risk rules.

Migration derives each legacy level's date from its creation timestamp converted
to Asia/Kolkata (legacy naive timestamps are interpreted as UTC). It preserves
IDs and existing events; startup then expires any overdue rows. It never assigns
all old levels today's date.

Backtest levels use the first replay record's trading date. Advancing the replay
clock expires them on a later date, including when only the requested end time
crosses midnight. Backtests do not automatically recreate levels on subsequent
dates; configure a separate daily run for each new daily level set.

## Bulk trade classification

A trade's reporting date is its entry timestamp converted to Asia/Kolkata, not
its exit date or the browser's local date. Date queries include every PAPER
trade for that date, regardless of execution status or classification.

Bulk classification updates only validity status, validity reason, and the
strategy-metric exclusion flag for the explicitly requested trade IDs. The whole
batch commits or none of it does; a missing or non-PAPER target rejects the batch.
Original execution fields, timestamps, versions, snapshots, and events are retained.

The UI confirms the selected count, classification, and inclusion choice before
applying. RAW metrics continue to include every PAPER trade; STRATEGY metrics
exclude flagged trades. Restoring VALID and clearing the exclusion flag restores
metric inclusion without changing execution history or trading behavior.

## Initial Level Arming

New or edited levels must not become immediately eligible for trading.

When a level is created or edited:

- capture the latest underlying index price as `activation_reference_price`
- set the level status to `PENDING_ARM`
- do not allow the level to generate a signal while in `PENDING_ARM`

The level becomes `ACTIVE` only after the underlying index moves the configured initial arming distance away from the captured reference price.

Formula:

abs(current_price - activation_reference_price)
>= initial_arm_distance_points

The tick that satisfies the arming condition only changes the level from:

PENDING_ARM → ACTIVE

It must not generate a trade on the same tick.

A later touch or crossing of the configured level is required.

### Index-wise Initial Arm Distance

Initial arming distance is configured per index.

Defaults:

- NIFTY = 30 points
- BANKNIFTY = 30 points
- SENSEX = 30 points

All levels belonging to the same index use that index's configured value.

The setting is managed from:

Settings → Index Rules

Example:

NIFTY Initial Arm Distance = 30
BANKNIFTY Initial Arm Distance = 50

Changing an index setting:

- affects `PENDING_ARM` levels for that index
- does not reset `ACTIVE` levels
- does not reset `DISARMED` levels
- does not affect other indices
- does not affect `EXPIRED` levels

The configuration must persist across application restarts.

### Difference From Post-Trade Rearming

Initial arming and post-trade rearming are separate rules.

Initial arming:

- happens after level create/edit
- measures movement from `activation_reference_price`
- uses the index-wise initial arm distance

Post-trade rearming:

- happens after a successful trade
- measures movement from the configured level itself
- uses `level_rearm_distance_points`

These two rules must not be mixed.

## SENSEX Support

NIFTY, BANKNIFTY, and SENSEX share the same level lifecycle, signal engine,
option selection, PAPER execution, post-trade rearming, and daily expiry rules.
Each index has an independent initial arming distance in Settings → Index Rules.
Existing saved distances and timestamps are preserved when SENSEX is added.

Zerodha sync includes the BSE SENSEX index and BFO SENSEX CE/PE contracts.
Strike spacing is derived from synced strikes using the existing metadata-based
source; expiry, lot size, symbols, and exchange come from the instrument master.
No SENSEX-specific selection or strategy rule is introduced. Refresh instrument
sync after upgrading to populate SENSEX in an existing instrument cache.

Simulation and historical replay use synthetic SENSEX contracts around 80000
with 100-point spacing, lot size 20, and expiries 7/14 days after the seed date.
These are local fixture values, not exchange specifications. Simulation seeds
option premiums at 200; backtests only use option quotes supplied in historical
records. SENSEX backtests use local JSON data, the historical clock, isolated
index settings (default 30 or explicit per-run overrides), and the shared engine.

## Stop Exit Classification

If the trade exits using the original downside stop before the effective stop
has advanced through trailing or breakeven protection:

exit_reason = STOP_LOSS

If the effective stop has moved forward because of trailing-stop or breakeven
protection and that protected stop is triggered:

exit_reason = TRAILING_STOP_LOSS

Classification must be based on the effective stop state at the time of exit,
not only on final realised P&L.

At a stop trigger, compare the effective stop calculated for that tick with
`initial_stop_loss`. A strictly higher effective stop produces
`TRAILING_STOP_LOSS`; otherwise use `STOP_LOSS`. The effective stop still uses
the existing maximum of initial, previous, trailing, and activated breakeven
protection. No stop formula, activation threshold, or entry rule changes.

Trailing protection that advances the stop while it is still below entry also
counts as `TRAILING_STOP_LOSS`. Breakeven protection that moves the stop to
entry or above uses the same reason. A gap/slippage below entry does not turn
an advanced-stop exit into `STOP_LOSS`; P&L describes the outcome, not the
protection that triggered it.

Both stop classifications retain `STOP_LOSS_HIT` and `POSITION_CLOSED` events.
Market-close precedence and its events remain unchanged. Non-stop reasons are
not inferred from stop state. Historical CLOSED trades retain their saved
reasons and events, even if their stop fields suggest an advanced stop; there
is no historical reclassification or backfill.

PAPER and BACKTEST both use `PositionMonitor` and `TradeRepository.close_at_stop`,
passing the effective stop from the triggering tick. Persisted stop protection
survives restart. Trades, Report, and Backtest display the four reasons as
Stop Loss, Trailing Stop Loss, Market Closing Exit, and Manual Square Off.
