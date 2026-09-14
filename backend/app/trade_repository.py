from contextlib import nullcontext

from app.database import connect
from app.trade_models import Trade, TradeEntry, TradeEntryResult


class TradeRepository:
    def __init__(self, database_path):
        self.database_path = database_path

    def get_by_selection(self, selection_id, connection):
        row = connection.execute(
            "SELECT * FROM trades WHERE option_selection_id = ?", (selection_id,)
        ).fetchone()
        return Trade(**dict(row)) if row else None

    def save(self, entry: TradeEntry, connection=None) -> Trade:
        context = connect(self.database_path) if connection is None else nullcontext(connection)
        with context as connection:
            values = entry.model_dump(mode="json")
            # Column names come only from the fixed model, never from request data.
            columns = ', '.join(values)
            placeholders = ', '.join('?' for _ in values)
            connection.execute(
                f"INSERT INTO trades ({columns}) VALUES ({placeholders}) "
                "ON CONFLICT(option_selection_id) DO NOTHING", tuple(values.values()),
            )
            return self.get_by_selection(entry.option_selection_id, connection)

    def record_result(self, result: TradeEntryResult, connection):
        connection.execute(
            """INSERT INTO trade_entry_results
                (option_selection_id, trade_id, status, failure_reason, timestamp)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(option_selection_id) DO UPDATE SET
                    trade_id = excluded.trade_id, status = excluded.status,
                    failure_reason = excluded.failure_reason, timestamp = excluded.timestamp
            """,
            (result.option_selection_id, result.trade_id, result.status,
             result.failure_reason, result.timestamp.isoformat()),
        )
        return result

    def recent(self, limit=100):
        with connect(self.database_path) as connection:
            return [Trade(**dict(row)) for row in connection.execute(
                "SELECT * FROM trades ORDER BY trade_id DESC LIMIT ?", (limit,)
            ).fetchall()]

    def recent_results(self, limit=100):
        with connect(self.database_path) as connection:
            return [TradeEntryResult(**dict(row)) for row in connection.execute(
                "SELECT * FROM trade_entry_results ORDER BY timestamp DESC, option_selection_id DESC LIMIT ?",
                (limit,),
            ).fetchall()]
