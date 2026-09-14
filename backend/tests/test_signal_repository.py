import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest

from app.database import connect, initialize_database
from app.level_monitor import LevelMonitor
from app.level_repository import LevelRepository
from app.market_data import PriceTick
from app.models import LevelInput
from app.signal_models import SignalAnalysis
from app.signal_repository import SignalRepository


@pytest.mark.parametrize("direction,distance,valid,reason", [
    ("FROM_ABOVE", 100, True, None),
    ("FROM_BELOW", 10, False, "MINIMUM_DISTANCE_NOT_MET"),
    (None, None, False, "INSUFFICIENT_PRICE_HISTORY"),
])
def test_signal_fields_survive_repository_reload(tmp_path, direction, distance, valid, reason):
    path = tmp_path / "signals.sqlite3"
    initialize_database(path)
    analysis = SignalAnalysis(
        trigger_id=1, level_id=1, instrument="NIFTY", level=25000,
        trigger_price=25000, direction=direction, approach_distance=distance,
        valid=valid, rejection_reason=reason,
        timestamp=datetime(2026, 9, 14, tzinfo=timezone.utc),
    )
    saved = SignalRepository(path).save(analysis)
    initialize_database(path)
    loaded, = SignalRepository(path).recent()
    assert loaded == saved
    assert loaded.model_dump(exclude={"id"}) == analysis.model_dump()
    assert SignalRepository(path).save(analysis).id > saved.id


def test_failed_multi_level_write_rolls_back_and_can_retry(tmp_path):
    path = tmp_path / "atomic.sqlite3"
    initialize_database(path)
    levels = LevelRepository(path)
    for price in [25000, 25100]:
        levels.create(LevelInput(instrument="NIFTY", price=price, enabled=True))
    with connect(path) as connection:
        connection.execute("""
            CREATE TRIGGER fail_second_signal BEFORE INSERT ON signals
            WHEN NEW.level = 25100 BEGIN SELECT RAISE(ABORT, 'test failure'); END
        """)

    async def scenario():
        monitor = LevelMonitor(levels)
        await monitor.on_tick(PriceTick(instrument="NIFTY", price=24900))
        with pytest.raises(sqlite3.IntegrityError):
            await monitor.on_tick(PriceTick(instrument="NIFTY", price=25200))
        assert SignalRepository(path).recent() == []
        assert monitor.recent_events() == []
        with connect(path) as connection:
            connection.execute("DROP TRIGGER fail_second_signal")
        await monitor.on_tick(PriceTick(instrument="NIFTY", price=25200))
        signals = SignalRepository(path).recent()
        assert [(s.level, s.approach_distance) for s in signals] == [(25100, 200), (25000, 100)]
        await monitor.on_tick(PriceTick(instrument="NIFTY", price=25200))
        assert SignalRepository(path).recent() == signals

    asyncio.run(scenario())
