# Strategy Rules

This file is the source of truth for trading strategy behaviour.

Do not change these rules without explicit approval.

## Current Scope

The strategy is a reversal-at-level options buying strategy.

For now, implement signal generation, simulated option selection, paper trade entry,
and position monitoring with initial/trailing stops and breakeven protection.

Only simulated PAPER entries are implemented. Never place live orders.

## Level Trigger

A configured level is triggered when price touches or crosses it.

Example level:

25,000

Both are valid triggers:

* 24,980 → 25,005
* 25,020 → 24,995
* current price = 25,000

Touching and crossing are treated the same.

## Direction

When a level triggers, determine the direction from which price approached the level.

### FROM_ABOVE

Example:

25,100 → 25,060 → 25,020 → 25,000

Direction:

`FROM_ABOVE`

Future trading behaviour:

Buy ITM CE.

### FROM_BELOW

Example:

24,900 → 24,950 → 24,980 → 25,000

Direction:

`FROM_BELOW`

Future trading behaviour:

Buy ITM PE.

For valid signals, select CE for FROM_ABOVE and PE for FROM_BELOW.
Contract selection does not place an order.

## Simulated Option Selection

Use a local synthetic option universe for NIFTY and BANKNIFTY. The simulated
strike steps are 50 and 100 points respectively. Round trigger price to the
nearest strike step for ATM; exact halfway values round upward.

`itm_depth` defaults to 1 and must be a positive integer. CE strike is ATM minus
depth times strike step; PE strike is ATM plus depth times strike step.

`expiry_strategy` is NEAREST: select the earliest expiry on or after the signal's
UTC date. Synthetic expiry dates are valid for their entire date; exchange
session cutoffs are outside this simulated milestone.

Resolve the exact expiry, strike, and type against the supplied instrument
universe. If missing, store a failed selection without substituting another
strike or expiry. Rejected signals produce no selection. Persist successful and
failed selection results for newly generated valid signals; do not replay old
signals automatically.

## Lookback

Direction and approach distance should use recent price history.

Setting:

`lookback_minutes`

Default:

15 minutes

Do not rely only on the final two ticks when sufficient history exists.

## Approach Distance

Approach distance represents how far price travelled toward the configured level during the lookback period.

For a level approached from above:

`approach_distance = relevant_high - level`

For a level approached from below:

`approach_distance = level - relevant_low`

Use the relevant high or low within the configured lookback window.

### Latest Continuous Approach

When history contains prices on both sides of a level, use the latest continuous
approach (approved for this milestone). Starting before the triggering tick,
walk backward through the lookback window until the previous touch or a price
on the opposite side. Use the high or low from only this segment. Small moves
away from the level on the same side remain part of the segment.

Exclude the triggering tick from the approach range so crossing overshoot does
not increase the distance. Evaluate the segment independently for each level.

## Minimum Approach Distance

Settings:

`minimum_approach_distance_enabled`

`minimum_approach_distance_points`

If enabled:

Reject the signal when:

`approach_distance < minimum_approach_distance_points`

If disabled:

Do not reject based on approach distance.

Still calculate and store the distance for analysis.

## Signal Result

A triggered level should produce a signal containing:

* instrument
* level
* trigger price
* direction
* approach distance
* valid
* rejection reason
* timestamp

Possible rejection reason:

`MINIMUM_DISTANCE_NOT_MET`

## Multiple Levels

Multiple levels can exist for the same instrument.

Each level is evaluated independently.

Example:

NIFTY:

* 25,000
* 25,100
* 25,200

Each can generate its own signal.

## Paper Trading Records

### Current Entry Milestone

Successful option selections may create an OPEN PAPER trade. Execution is separate
from signal evaluation and contract selection. Quantity is the selected contract's
lot size multiplied by configured `number_of_lots` (default 1).

For this simulated universe only, NIFTY lot size is 10 and BANKNIFTY lot size is
20. These are test fixtures, not exchange specifications. Default synthetic option
quotes are 100 and 200 respectively; underlying ticks never serve as option quotes.

When no positive finite option quote is available, persist an entry failure
`OPTION_PRICE_UNAVAILABLE` and do not create a trade. A selection may create only
one trade, enforced by its unique selection ID in SQLite. Reprocessing returns
the original trade. Failed entries may be retried through the execution service
once a quote becomes available; there is no automatic retry or startup replay.

`trade_mode` supports PAPER and LIVE as configuration values, but LIVE execution
returns `LIVE_MODE_NOT_SUPPORTED` without creating any trade.

Initial stop-loss exits and realised P&L are now implemented for PAPER positions.
Other exits and aggregate reports remain deferred.

### Initial Stop Loss

`stop_loss_percentage` defaults to 10 and must be greater than 0 and less than 100.
At entry, persist the configured percentage and
`initial_stop_loss = entry_price * (1 - stop_loss_percentage / 100)`.
Existing stops do not change when configuration changes.

An option-symbol tick closes matching OPEN PAPER positions when price is at or
below the stored stop. Exit price is the received price, including gaps below the
stop. Zero is a valid exit price; negative option prices are rejected.

Persist status CLOSED, exit reason STOP_LOSS, exit price/time, and:

* `realised_pnl = (exit_price - entry_price) * quantity`
* `realised_pnl_percentage = (exit_price - entry_price) / entry_price * 100`

These are gross simulated results without fees or slippage modelling. Persist
POSITION_OPENED, STOP_LOSS_HIT, and POSITION_CLOSED events. Update trade state and
events atomically. Closed positions cannot close again or be reopened by retrying
their original option selection.

Legacy entries without stops are migrated once using the configured percentage
at startup. Their entry records and IDs remain intact. Their reconstructed
POSITION_OPENED events are marked as reconstructed.

### Trailing Stop and Breakeven Protection

Defaults: trailing_stop_percentage = 10, breakeven_protection_enabled = true,
breakeven_activation_percent = 10, breakeven_lock_percent = 0. Persist these
settings per trade. New settings do not change an existing trade's protection.

Initialize highest_price to entry_price, current_stop_loss to initial_stop_loss,
and breakeven_activated to false. On each option tick for an OPEN PAPER trade:

* highest_price = max(existing highest_price, current price)
* trailing_stop = highest_price * (1 - trailing_stop_percentage / 100)
* If enabled and highest_price >= entry_price * (1 + activation percent / 100),
  activate protection permanently for this trade.
* Once active, breakeven_stop = entry_price * (1 + lock percent / 100).
* current_stop_loss = max(initial stop, previous current stop, trailing stop,
  breakeven stop if active).

Persist protection changes and then close if current price <= current_stop_loss.
The stop can never decrease. Exit reason remains STOP_LOSS for all stop exits.
Record TRAILING_STOP_UPDATED only if trailing strictly exceeds the initial,
previous, and breakeven stop candidates. A tie with breakeven is credited to
breakeven protection. Record BREAKEVEN_PROTECTION_ACTIVATED once when the threshold
is first reached, even if a stronger trailing stop already applies.

Migrate older positions once with highest_price = entry_price and current_stop_loss
= initial_stop_loss; historical highs cannot be reconstructed from missing ticks.
Keep existing trade/event IDs and exits. No synthetic activation or trailing events
are emitted by migration.

When paper trading is introduced, every simulated trade must be stored in the database.

Persist at minimum:

* trade ID
* instrument
* trigger level
* direction
* option symbol
* option type
* strike
* expiry
* entry price
* entry time
* highest price reached
* initial stop loss
* exit price
* exit time
* exit reason
* realised P&L
* realised P&L percentage
* trade mode = PAPER

Also store important trade actions/events, such as:

* level triggered
* signal accepted
* signal rejected
* option selected
* order simulated
* position opened
* stop loss updated
* trailing stop updated
* exit triggered
* trade closed
* manual square-off
* market-closing exit

The system should make it possible to reconstruct exactly what happened during a trade and why.

## Paper Trading Report

Create a dedicated paper-trading report/history page.

It should show:

* total trades
* winning trades
* losing trades
* win rate
* gross profit
* gross loss
* net P&L
* average profit
* average loss
* maximum profit
* maximum loss
* maximum drawdown
* profit factor

Also provide a trade table with:

* date
* instrument
* level
* option
* entry
* exit
* quantity
* P&L
* P&L %
* exit reason
* trade duration

Each trade should be expandable or clickable to show its full event/action history.

## Future Rules

These are not part of the current milestone:

* quantity
* order placement
* trailing stop loss
* paper trading reports
* live trading
* mandatory market-close exit
* backtesting

Add them only when their milestone begins.
