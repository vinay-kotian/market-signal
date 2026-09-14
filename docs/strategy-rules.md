# Strategy Rules

This file is the source of truth for trading strategy behaviour.

Do not change these rules without explicit approval.

## Current Scope

The strategy is a reversal-at-level options buying strategy.

For now, only implement signal generation.

Do not place trades yet.

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

Do not implement CE/PE selection yet.

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
* quantity
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

* ITM option selection
* quantity
* order placement
* stop loss
* trailing stop loss
* paper trading
* paper trading reports
* live trading
* mandatory market-close exit
* backtesting

Add them only when their milestone begins.
