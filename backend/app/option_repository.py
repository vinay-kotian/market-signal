from app.date_range import timestamp_scope
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

    def recent(self, limit: int = 100, from_date=None, to_date=None) -> list[StoredOptionSelection]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with connect(self.database_path) as connection:
            clauses, values = timestamp_scope(connection, 'timestamp', from_date, to_date)
            where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
            rows = connection.execute(
                f"SELECT * FROM option_selections{where} ORDER BY id DESC LIMIT ?", (*values, limit)
            ).fetchall()
            return [StoredOptionSelection(**dict(row)) for row in rows]

    def history(self, page=1, page_size=20, from_date=None, to_date=None):
        with connect(self.database_path) as connection:
            clauses, values = timestamp_scope(connection, 'timestamp', from_date, to_date)
            where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
            connection.execute('BEGIN')
            total = connection.execute(f'SELECT COUNT(*) FROM option_selections{where}', values).fetchone()[0]
            rows = connection.execute(f"""SELECT s.*,
                (SELECT entry_price FROM trades t WHERE t.option_selection_id=s.id AND t.trade_mode='PAPER') AS entry_premium
                FROM option_selections s{where} ORDER BY s.id DESC LIMIT ? OFFSET ?""",
                (*values, page_size, (page - 1) * page_size)).fetchall()
            return dict(items=[{**StoredOptionSelection(**dict(row)).model_dump(mode='json'),
                                'entry_premium': row['entry_premium']} for row in rows],
                        total=total, page=page, page_size=page_size)
