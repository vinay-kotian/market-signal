from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.database import connect


class TradeEvent(BaseModel):
    id: int
    trade_id: int
    event_type: Literal['POSITION_OPENED', 'STOP_LOSS_HIT', 'POSITION_CLOSED',
                        'TRAILING_STOP_UPDATED', 'BREAKEVEN_PROTECTION_ACTIVATED']
    price: float
    timestamp: datetime
    reconstructed: bool
    previous_stop: Optional[float] = None
    current_stop: Optional[float] = None


class TradeEventRepository:
    def __init__(self, database_path):
        self.database_path = database_path

    def record(self, trade_id, event_type, price, timestamp, connection,
               previous_stop=None, current_stop=None):
        connection.execute("""INSERT INTO trade_events
            (trade_id, event_type, price, timestamp, previous_stop, current_stop)
            VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (trade_id, event_type, price, timestamp.isoformat(), previous_stop, current_stop))

    def for_trade(self, trade_id):
        with connect(self.database_path) as connection:
            return [TradeEvent(**dict(row)) for row in connection.execute(
                'SELECT * FROM trade_events WHERE trade_id = ? ORDER BY id', (trade_id,)
            ).fetchall()]
