from datetime import time
from typing import List, Optional

from backend.app.core.enums import EntryApproachDirection, SignalType
from backend.app.dto.trading_dto import LevelContext, MarketContext, PositionState, StrategySignal


class LevelStrategy:
    def __init__(self, tick_size: float = 0.05, trailing_gap: float = 5.0) -> None:
        self.tick_size = tick_size
        self.trailing_gap = trailing_gap

    def evaluate(
        self,
        market: MarketContext,
        levels: LevelContext,
        position: Optional[PositionState],
        square_off_time: Optional[time] = None,
    ) -> List[StrategySignal]:
        tick = market.tick
        signals: List[StrategySignal] = []

        if position and position.is_open:
            signals.extend(self._evaluate_open_position(market, levels, position))
            if square_off_time and tick.timestamp.time() >= square_off_time:
                signals.append(
                    StrategySignal(
                        signal_type=SignalType.EOD_EXIT,
                        instrument_id=tick.instrument_id,
                        price=tick.last_price,
                        quantity=position.quantity,
                        reason="Square-off time reached",
                    )
                )
            return signals

        if self._reached_level(market.previous_price, tick.last_price, levels.l1.price):
            direction = self._entry_direction(market.previous_price, tick.last_price, levels.l1.price)
            signals.append(
                StrategySignal(
                    signal_type=SignalType.BUY,
                    instrument_id=tick.instrument_id,
                    price=levels.l1.price,
                    reason="L1 entry reached",
                    quantity=1,
                    entry_approach_direction=direction,
                    entry_velocity=market.velocity_per_second,
                    stoploss_price=levels.l0.price,
                    trailing_stoploss_price=levels.l0.price,
                )
            )

        return signals

    def _evaluate_open_position(
        self, market: MarketContext, levels: LevelContext, position: PositionState
    ) -> List[StrategySignal]:
        tick = market.tick
        signals: List[StrategySignal] = []

        if tick.last_price <= position.trailing_stoploss_price:
            return [
                StrategySignal(
                    signal_type=SignalType.SELL,
                    instrument_id=tick.instrument_id,
                    price=position.trailing_stoploss_price,
                    quantity=position.quantity,
                    reason="Trailing stoploss hit",
                )
            ]

        high_water_mark = max(position.high_water_mark, tick.last_price)
        trailing_is_active = position.trailing_stoploss_price > position.stoploss_price
        trailing_stop = position.trailing_stoploss_price

        for level in levels.upper_levels:
            if level.name in position.reached_checkpoints:
                continue
            if self._reached_level(market.previous_price, tick.last_price, level.price):
                trailing_is_active = True
                trailing_stop = max(trailing_stop, level.price - self.trailing_gap)
                signals.append(
                    StrategySignal(
                        signal_type=SignalType.TARGET_CHECKPOINT_REACHED,
                        instrument_id=tick.instrument_id,
                        price=tick.last_price,
                        reason=f"{level.name} checkpoint reached",
                        checkpoint_name=level.name,
                        trailing_stoploss_price=trailing_stop,
                    )
                )

        if trailing_is_active:
            trailing_stop = max(trailing_stop, high_water_mark - self.trailing_gap)

        if trailing_stop > position.trailing_stoploss_price:
            signals.append(
                StrategySignal(
                    signal_type=SignalType.UPDATE_TRAILING_STOPLOSS,
                    instrument_id=tick.instrument_id,
                    price=tick.last_price,
                    reason="Trailing stoploss moved upward",
                    trailing_stoploss_price=trailing_stop,
                )
            )

        return signals

    def _reached_level(
        self, previous_price: Optional[float], current_price: float, level_price: float
    ) -> bool:
        if abs(current_price - level_price) <= self.tick_size:
            return True
        if previous_price is None:
            return False
        low = min(previous_price, current_price)
        high = max(previous_price, current_price)
        return low <= level_price <= high

    def _entry_direction(
        self, previous_price: Optional[float], current_price: float, level_price: float
    ) -> EntryApproachDirection:
        if previous_price is None:
            return EntryApproachDirection.UNKNOWN_AT_LEVEL
        if previous_price < level_price <= current_price:
            return EntryApproachDirection.BELOW_TO_L1
        if previous_price > level_price >= current_price:
            return EntryApproachDirection.ABOVE_TO_L1
        return EntryApproachDirection.UNKNOWN_AT_LEVEL
