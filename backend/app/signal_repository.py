from contextlib import nullcontext

from app.database import connect
from app.signal_models import SignalAnalysis, SignalResult


class SignalRepository:
    def __init__(self, database_path):
        self.database_path = database_path

    def save(self, signal: SignalAnalysis) -> SignalResult:
        return self.save_many([signal])[0]

    def save_many(self, signals: list[SignalAnalysis], connection=None) -> list[SignalResult]:
        """Commit all results from one price transition together."""
        if not signals:
            return []
        saved = []
        context = connect(self.database_path) if connection is None else nullcontext(connection)
        with context as connection:
            for signal in signals:
                cursor = connection.execute(
                    """
                    INSERT INTO signals (
                        trigger_id, level_id, instrument, level, trigger_price,
                        direction, approach_distance, valid, rejection_reason, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (signal.trigger_id, signal.level_id, signal.instrument, signal.level,
                     signal.trigger_price, signal.direction, signal.approach_distance,
                     signal.valid, signal.rejection_reason, signal.timestamp.isoformat()),
                )
                saved.append(SignalResult(id=cursor.lastrowid, **signal.model_dump()))
        return saved

    def recent(self, limit: int = 100) -> list[SignalResult]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [SignalResult(**dict(row)) for row in rows]
