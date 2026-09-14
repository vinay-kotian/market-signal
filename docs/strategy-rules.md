# Strategy Rules

This file is the source of truth for trading strategy behaviour.

Do not change these rules without explicit approval.

## Current Scope

The strategy is a reversal-at-level options buying strategy.

For now, implement signal generation, simulated option selection, and paper trade entry.

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

The fields and actions below involving stops, exits, and P&L remain deferred until
their respective milestones. This step persists entry snapshots and the latest
entry outcome per selection.

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
* trailing stop loss
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
* stop loss
* trailing stop loss
* paper trading reports
* live trading
* mandatory market-close exit
* backtesting

Add them only when their milestone begins.
