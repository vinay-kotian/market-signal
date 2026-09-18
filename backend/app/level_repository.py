from contextlib import nullcontext
from decimal import Decimal
from typing import List, Optional

from app.database import connect
from app.models import Level, LevelInput, LevelEvent
from app.trading_date import trading_date, utc_now


class LevelRepository:
    def __init__(self, database_path, clock=utc_now):
        self.database_path = database_path
        self.clock = clock

    def create(self, data: LevelInput) -> Level:
        timestamp = self.clock()
        now = timestamp.isoformat()
        today = trading_date(timestamp)
        level_date = data.level_date or today
        status = 'EXPIRED' if level_date < today else 'ACTIVE'
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """INSERT INTO levels (instrument, price, enabled, created_at, updated_at, level_date, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (data.instrument, data.price, data.enabled, now, now, level_date.isoformat(), status),
            )
            row = connection.execute('SELECT * FROM levels WHERE id = ?', (cursor.lastrowid,)).fetchone()
            return Level(**dict(row))

    def list(self, level_date=None) -> List[Level]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                'SELECT * FROM levels WHERE (? IS NULL OR level_date = ?) ORDER BY id',
                (level_date.isoformat() if level_date else None,) * 2,
            ).fetchall()
            return [Level(**dict(row)) for row in rows]

    def get(self, level_id: int) -> Optional[Level]:
        with connect(self.database_path) as connection:
            row = connection.execute('SELECT * FROM levels WHERE id = ?', (level_id,)).fetchone()
            return Level(**dict(row)) if row is not None else None

    def list_enabled(self, instrument: str, timestamp=None) -> List[Level]:
        today = trading_date(timestamp or self.clock()).isoformat()
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """SELECT * FROM levels WHERE instrument = ? AND enabled = 1
                AND level_date = ? AND status IN ('ACTIVE', 'DISARMED') ORDER BY id""",
                (instrument, today),
            ).fetchall()
            return [Level(**dict(row)) for row in rows]

    def update(self, level_id: int, data: LevelInput) -> Optional[Level]:
        timestamp = self.clock()
        with connect(self.database_path) as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM levels WHERE id = ?', (level_id,)).fetchone()
            if row is None:
                return None
            self._require_editable(row, timestamp)
            if data.level_date is not None and data.level_date.isoformat() != row['level_date']:
                raise ValueError('A level date cannot be changed; create a new daily level')
            connection.execute(
                """UPDATE levels SET instrument = ?, price = ?, enabled = ?, updated_at = ? WHERE id = ?""",
                (data.instrument, data.price, data.enabled, timestamp.isoformat(), level_id),
            )
            return Level(**dict(connection.execute('SELECT * FROM levels WHERE id = ?', (level_id,)).fetchone()))

    def delete(self, level_id: int) -> bool:
        with connect(self.database_path) as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM levels WHERE id = ?', (level_id,)).fetchone()
            if row is None:
                return False
            self._require_editable(row, self.clock())
            connection.execute('DELETE FROM levels WHERE id = ?', (level_id,))
            return True

    @staticmethod
    def _require_editable(row, timestamp):
        if row['status'] == 'EXPIRED' or row['level_date'] < trading_date(timestamp).isoformat():
            raise ValueError('Expired levels are retained for audit and cannot be edited or deleted')

    def expire_before(self, timestamp):
        with connect(self.database_path) as connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute(
                "SELECT id FROM levels WHERE level_date < ? AND status != 'EXPIRED'",
                (trading_date(timestamp).isoformat(),),
            ).fetchall()
            connection.execute(
                """UPDATE levels SET status = 'EXPIRED', updated_at = ?
                WHERE level_date < ? AND status != 'EXPIRED'""",
                (timestamp.isoformat(), trading_date(timestamp).isoformat()),
            )
            return [Level(**dict(connection.execute('SELECT * FROM levels WHERE id = ?', (row['id'],)).fetchone()))
                    for row in rows]

    def change_status(self, level_id, status, price, timestamp, connection=None, trade_id=None):
        if status not in ('ACTIVE', 'DISARMED'):
            raise ValueError('Unknown level state')
        context = connect(self.database_path) if connection is None else nullcontext(connection)
        with context as connection:
            changed = connection.execute(
                """UPDATE levels SET status = ?, updated_at = ? WHERE id = ?
                AND status = ? AND level_date = ?""",
                (status, timestamp.isoformat(), level_id,
                 'DISARMED' if status == 'ACTIVE' else 'ACTIVE', trading_date(timestamp).isoformat()),
            ).rowcount
            if changed:
                connection.execute("""INSERT INTO level_events
                    (level_id, event_type, underlying_price, timestamp, trade_id)
                    VALUES (?, ?, ?, ?, ?)""",
                    (level_id, 'LEVEL_REARMED' if status == 'ACTIVE' else 'LEVEL_DISARMED',
                     price, timestamp.isoformat(), trade_id))
            return bool(changed)

    def rearm(self, level, price, distance, timestamp):
        if abs(Decimal(str(price)) - Decimal(str(level.price))) >= Decimal(str(distance)):
            return self.change_status(level.id, 'ACTIVE', price, timestamp)
        return False

    def events(self, level_id):
        with connect(self.database_path) as connection:
            return [LevelEvent(**dict(row)) for row in connection.execute(
                'SELECT * FROM level_events WHERE level_id = ? ORDER BY id', (level_id,))]
