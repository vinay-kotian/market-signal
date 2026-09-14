from contextlib import nullcontext
from datetime import datetime

from app.database import connect
from app.option_models import OptionSelection, StoredOptionSelection


class OptionSelectionRepository:
    def __init__(self, database_path):
        self.database_path = database_path

    def save(self, signal_id: int, selection: OptionSelection, timestamp: datetime,
             connection=None) -> StoredOptionSelection:
        context = connect(self.database_path) if connection is None else nullcontext(connection)
        with context as connection:
            connection.execute(
                """
                INSERT INTO option_selections (
                    signal_id, instrument, trigger_price, direction, option_type,
                    itm_depth, expiry, atm_strike, itm_strike, option_symbol,
                    status, failure_reason, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id) DO NOTHING
                """,
                (signal_id, selection.instrument, selection.trigger_price, selection.direction,
                 selection.option_type, selection.itm_depth,
                 selection.expiry.isoformat() if selection.expiry else None,
                 selection.atm_strike, selection.itm_strike, selection.option_symbol,
                 selection.status, selection.failure_reason, timestamp.isoformat()),
            )
            # The first result for a signal is authoritative, including failures.
            row = connection.execute(
                "SELECT * FROM option_selections WHERE signal_id = ?", (signal_id,)
            ).fetchone()
            return StoredOptionSelection(**dict(row))

    def recent(self, limit: int = 100) -> list[StoredOptionSelection]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM option_selections ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [StoredOptionSelection(**dict(row)) for row in rows]
