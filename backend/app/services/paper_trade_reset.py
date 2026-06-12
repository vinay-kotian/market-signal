from datetime import date, datetime, time
from typing import Dict, Optional

from sqlalchemy import delete, false, select
from sqlalchemy.orm import Session

from backend.app.core.timezone import IST, as_utc
from backend.app.models.tables import AuditLog, Order, Position


TRADE_AUDIT_EVENTS = {
    "PAPER_EXECUTION",
    "PAPER_EXECUTION_FAILED",
    "DUPLICATE_POSITION_BLOCKED",
    "EOD_SQUARE_OFF",
    "EOD_SQUARE_OFF_SKIPPED",
    "BUY",
    "SELL",
    "TARGET_CHECKPOINT_REACHED",
    "UPDATE_TRAILING_STOPLOSS",
}


def reset_paper_trades_for_day(
    db: Session, trading_day: date, instrument_id: Optional[int] = None
) -> Dict[str, int]:
    day_start = as_utc(datetime.combine(trading_day, time.min), naive_timezone=IST).replace(
        tzinfo=None
    )
    day_end = as_utc(datetime.combine(trading_day, time.max), naive_timezone=IST).replace(
        tzinfo=None
    )
    position_statement = select(Position.id).where(Position.trading_day == trading_day)
    if instrument_id is not None:
        position_statement = position_statement.where(Position.instrument_id == instrument_id)
    position_ids = list(db.scalars(position_statement).all())

    order_statement = delete(Order).where(
        (Order.position_id.in_(position_ids) if position_ids else false())
        | ((Order.created_at >= day_start) & (Order.created_at <= day_end))
    )
    if instrument_id is not None:
        order_statement = order_statement.where(Order.instrument_id == instrument_id)

    position_delete_statement = delete(Position).where(Position.trading_day == trading_day)
    audit_delete_statement = delete(AuditLog).where(
        AuditLog.event_type.in_(TRADE_AUDIT_EVENTS),
        AuditLog.created_at >= day_start,
        AuditLog.created_at <= day_end,
    )
    if instrument_id is not None:
        position_delete_statement = position_delete_statement.where(
            Position.instrument_id == instrument_id
        )
        audit_delete_statement = audit_delete_statement.where(
            AuditLog.instrument_id == instrument_id
        )

    orders_result = db.execute(order_statement)
    positions_result = db.execute(position_delete_statement)
    audit_result = db.execute(audit_delete_statement)
    db.commit()
    return {
        "orders_deleted": orders_result.rowcount or 0,
        "positions_deleted": positions_result.rowcount or 0,
        "audit_events_deleted": audit_result.rowcount or 0,
    }
