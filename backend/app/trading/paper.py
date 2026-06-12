from datetime import date
from typing import Optional

from backend.app.core.enums import OrderSide, SignalType
from backend.app.dto.trading_dto import ExecutionResult, PositionState, StrategySignal, TradeAction


class PaperTradingAgent:
    def execute(
        self,
        signal: StrategySignal,
        position: Optional[PositionState],
        trading_day: date,
    ) -> ExecutionResult:
        if signal.signal_type == SignalType.BUY:
            new_position = PositionState(
                instrument_id=signal.instrument_id,
                trading_day=trading_day,
                quantity=signal.quantity,
                entry_price=signal.price,
                stoploss_price=signal.stoploss_price or signal.price,
                trailing_stoploss_price=signal.trailing_stoploss_price or signal.stoploss_price or signal.price,
                high_water_mark=signal.price,
            )
            action = TradeAction(
                side=OrderSide.BUY,
                instrument_id=signal.instrument_id,
                quantity=signal.quantity,
                price=signal.price,
                reason=signal.reason,
                stoploss_price=new_position.stoploss_price,
            )
            return ExecutionResult(action=action, success=True, message="Paper buy filled", position=new_position)

        if signal.signal_type in {SignalType.SELL, SignalType.EOD_EXIT} and position:
            position.is_open = False
            position.exit_price = signal.price
            position.realized_pnl = (signal.price - position.entry_price) * position.quantity
            action = TradeAction(
                side=OrderSide.SELL,
                instrument_id=signal.instrument_id,
                quantity=position.quantity,
                price=signal.price,
                reason=signal.reason,
            )
            return ExecutionResult(action=action, success=True, message="Paper sell filled", position=position)

        action = TradeAction(
            side=OrderSide.BUY,
            instrument_id=signal.instrument_id,
            quantity=0,
            price=signal.price,
            reason=signal.reason,
        )
        return ExecutionResult(action=action, success=False, message="No executable paper action", position=position)

    def apply_state_signal(self, signal: StrategySignal, position: Optional[PositionState]) -> None:
        if not position:
            return
        if signal.signal_type == SignalType.TARGET_CHECKPOINT_REACHED and signal.checkpoint_name:
            position.reached_checkpoints.add(signal.checkpoint_name)
        if signal.trailing_stoploss_price is not None:
            position.trailing_stoploss_price = max(
                position.trailing_stoploss_price, signal.trailing_stoploss_price
            )
        position.high_water_mark = max(position.high_water_mark, signal.price)
