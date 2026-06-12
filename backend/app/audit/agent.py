from sqlalchemy.orm import Session

from backend.app.dto.trading_dto import ExecutionResult, StrategySignal
from backend.app.models.tables import AuditLog


class AuditAgent:
    def record_signal(self, db: Session, signal: StrategySignal) -> AuditLog:
        message = f"{signal.signal_type.value}: {signal.reason} at {signal.price}"
        if signal.checkpoint_name:
            message = f"{message} ({signal.checkpoint_name})"
        log = AuditLog(
            event_type=signal.signal_type.value,
            instrument_id=signal.instrument_id,
            message=message,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    def record_execution(self, db: Session, result: ExecutionResult) -> AuditLog:
        event_type = "EXECUTION_SUCCESS" if result.success else "EXECUTION_FAILED"
        log = AuditLog(
            event_type=event_type,
            instrument_id=result.action.instrument_id,
            message=f"{result.action.side.value}: {result.message} at {result.action.price}",
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log
