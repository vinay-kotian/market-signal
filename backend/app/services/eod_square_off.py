from datetime import date, datetime
from typing import Dict, List

from sqlalchemy.orm import Session

from backend.app.core.enums import OrderSide, PositionStatus
from backend.app.db.trading_state import list_open_positions
from backend.app.market.tick_cache import tick_cache
from backend.app.models.tables import AuditLog, Order


def square_off_open_positions(db: Session, trading_day: date) -> Dict[str, object]:
    closed: List[dict] = []
    skipped: List[dict] = []
    latest_ticks = tick_cache.latest()

    for position in list_open_positions(db, trading_day):
        tick = latest_ticks.get(position.instrument_id)
        if tick is None:
            skipped.append(
                {
                    "position_id": position.id,
                    "instrument_id": position.instrument_id,
                    "reason": "No latest price available",
                }
            )
            db.add(
                AuditLog(
                    event_type="EOD_SQUARE_OFF_SKIPPED",
                    instrument_id=position.instrument_id,
                    message="No latest price available for EOD square-off",
                )
            )
            continue

        exit_price = tick.last_price
        realized_pnl = (exit_price - position.entry_price) * position.quantity
        position.status = PositionStatus.CLOSED.value
        position.closed_at = datetime.utcnow()
        position.exit_price = exit_price
        position.realized_pnl = realized_pnl
        db.add(
            Order(
                instrument_id=position.instrument_id,
                position_id=position.id,
                side=OrderSide.SELL.value,
                quantity=position.quantity,
                price=exit_price,
                reason="EOD square-off",
            )
        )
        db.add(
            AuditLog(
                event_type="EOD_SQUARE_OFF",
                instrument_id=position.instrument_id,
                message=f"Closed position {position.id} at {exit_price}",
            )
        )
        closed.append(
            {
                "position_id": position.id,
                "instrument_id": position.instrument_id,
                "exit_price": exit_price,
                "realized_pnl": realized_pnl,
            }
        )

    db.commit()
    return {"closed": closed, "skipped": skipped}
