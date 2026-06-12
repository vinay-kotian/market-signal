from typing import Optional

from backend.app.core.enums import RiskStatus, SignalType
from backend.app.dto.trading_dto import PositionState, RiskDecision, StrategySignal


class RiskAgent:
    def validate(self, signal: StrategySignal, position: Optional[PositionState]) -> RiskDecision:
        if signal.signal_type == SignalType.BUY and position and position.is_open:
            return RiskDecision(
                status=RiskStatus.REJECTED,
                signal=signal,
                reason="Open position already exists for instrument",
            )

        if signal.signal_type in {SignalType.SELL, SignalType.EOD_EXIT}:
            if not position or not position.is_open:
                return RiskDecision(
                    status=RiskStatus.REJECTED,
                    signal=signal,
                    reason="Cannot sell without open bought position",
                )

        return RiskDecision(status=RiskStatus.APPROVED, signal=signal, reason="Approved")
