from datetime import datetime, timezone
from typing import List, Optional

from app.database import connect
from app.models import Level, LevelInput


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
