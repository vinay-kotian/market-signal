from datetime import datetime, timezone
from contextlib import nullcontext
from decimal import Decimal
from typing import List, Optional

from app.database import connect
from app.models import Level, LevelInput, LevelEvent


class LevelRepository:
    def __init__(self, database_path):
        self.database_path = database_path

    def create(self, data: LevelInput) -> Level:
        now = datetime.now(timezone.utc).isoformat()
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO levels (instrument, price, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (data.instrument, data.price, data.enabled, now, now),
            )
            row = connection.execute(
                "SELECT * FROM levels WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return Level(**dict(row))

    def list(self) -> List[Level]:
        with connect(self.database_path) as connection:
            rows = connection.execute("SELECT * FROM levels ORDER BY id").fetchall()
            return [Level(**dict(row)) for row in rows]

    def get(self, level_id: int) -> Optional[Level]:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM levels WHERE id = ?", (level_id,)
            ).fetchone()
            return Level(**dict(row)) if row is not None else None

    def list_enabled(self, instrument: str) -> List[Level]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM levels WHERE instrument = ? AND enabled = 1 ORDER BY id",
                (instrument,),
            ).fetchall()
            return [Level(**dict(row)) for row in rows]

    def update(self, level_id: int, data: LevelInput) -> Optional[Level]:
        now = datetime.now(timezone.utc).isoformat()
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE levels
                SET instrument = ?, price = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (data.instrument, data.price, data.enabled, now, level_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM levels WHERE id = ?", (level_id,)
            ).fetchone()
            return Level(**dict(row))

    def delete(self, level_id: int) -> bool:
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                "DELETE FROM levels WHERE id = ?", (level_id,)
            )
            return cursor.rowcount > 0

    def change_status(self, level_id, status, price, timestamp, connection=None, trade_id=None):
        if status not in ('ACTIVE', 'DISARMED'):
            raise ValueError('Unknown level state')
        context = connect(self.database_path) if connection is None else nullcontext(connection)
        with context as connection:
            changed = connection.execute(
                'UPDATE levels SET status = ?, updated_at = ? WHERE id = ? AND status != ?',
                (status, timestamp.isoformat(), level_id, status),
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
