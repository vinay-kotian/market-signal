from contextlib import nullcontext
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.database import connect


class TradeEvent(BaseModel):
    id: int
    trade_id: int
    event_type: Literal['POSITION_OPENED', 'STOP_LOSS_HIT', 'POSITION_CLOSED',
                        'TRAILING_STOP_UPDATED', 'BREAKEVEN_PROTECTION_ACTIVATED',
                        'MARKET_CLOSING_EXIT_TRIGGERED', 'PROFIT_LOCK_ACTIVATED', 'TRAILING_STEP_CHANGED']
    price: float
    timestamp: datetime
    reconstructed: bool
    previous_stop: Optional[float] = None
    current_stop: Optional[float] = None
    highest_price: Optional[float] = None
    trailing_pct: Optional[float] = None
    trailing_step: Optional[int] = None
    profit_lock_activated: Optional[bool] = None


class TradeEventRepository:
    def __init__(self, database_path):
        self.database_path = database_path

    def record(self, trade_id, event_type, price, timestamp, connection,
               previous_stop=None, current_stop=None, *, protection=None):
        metadata = (None, None, None, None) if protection is None else (
            float(protection.highest), float(protection.trailing_pct) if protection.trailing_pct is not None else None,
            protection.step, protection.activated)
        connection.execute("""INSERT INTO trade_events
            (trade_id, event_type, price, timestamp, previous_stop, current_stop,
             highest_price, trailing_pct, trailing_step, profit_lock_activated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (trade_id, event_type, price, timestamp.isoformat(), previous_stop, current_stop, *metadata))

    def for_trade(self, trade_id, connection=None):
        context = connect(self.database_path) if connection is None else nullcontext(connection)
        with context as connection:
            return [TradeEvent(**dict(row)) for row in connection.execute(
                'SELECT * FROM trade_events WHERE trade_id = ? ORDER BY julianday(timestamp), id', (trade_id,)
            ).fetchall()]
