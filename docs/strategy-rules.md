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

`STOP_LOSS` or `MARKET_CLOSING_EXIT`

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