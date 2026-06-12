from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.enums import LevelSetStatus
from backend.app.db.repositories import (
    DuplicateLevelSetError,
    archive_past_level_sets,
    assert_level_set_editable,
    cancel_daily_level_set,
    create_daily_level_set,
    update_daily_level_set,
)
from backend.app.db.session import Base
from backend.app.models.tables import DailyLevelSet, Instrument, Level, Position


def test_past_level_set_is_not_editable() -> None:
    level_set = DailyLevelSet(
        instrument_id=1,
        trading_day=date(2026, 5, 16),
        status=LevelSetStatus.ACTIVE.value,
    )

    try:
        assert_level_set_editable(level_set, today=date(2026, 5, 17))
    except ValueError as exc:
        assert "cannot be edited" in str(exc)
    else:
        raise AssertionError("Past level set should be locked from edits")


def test_duplicate_active_level_set_is_rejected() -> None:
    db = _db()
    instrument = _instrument(db)
    levels = _levels(100, 110)

    create_daily_level_set(db, instrument.id, date.today(), "test", levels)

    try:
        create_daily_level_set(db, instrument.id, date.today(), "test", levels)
    except DuplicateLevelSetError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Duplicate active level set should be rejected")
    finally:
        db.close()


def test_today_level_set_can_be_updated_and_cancelled() -> None:
    db = _db()
    instrument = _instrument(db)
    level_set = create_daily_level_set(db, instrument.id, date.today(), "test", _levels(100, 110))

    updated = update_daily_level_set(
        db=db,
        level_set_id=level_set.id,
        updated_by="test",
        levels=_levels(101, 111),
    )
    assert updated.levels[0].price == 101
    assert updated.levels[1].price == 111

    cancelled = cancel_daily_level_set(db, level_set.id, "test")
    assert cancelled.status == LevelSetStatus.CANCELLED.value
    db.close()


def test_past_level_sets_are_archived_with_execution_status() -> None:
    db = _db()
    executed_instrument = _instrument(db, symbol="EXECUTED_CE", token=123)
    missed_instrument = _instrument(db, symbol="MISSED_CE", token=124)
    past_day = date(2026, 5, 17)
    executed_level_set = DailyLevelSet(
        instrument_id=executed_instrument.id,
        trading_day=past_day,
        status=LevelSetStatus.ACTIVE.value,
        execution_status="PENDING",
    )
    executed_level_set.levels.extend([Level(**level) for level in _levels(100, 110)])
    missed_level_set = DailyLevelSet(
        instrument_id=missed_instrument.id,
        trading_day=past_day,
        status=LevelSetStatus.ACTIVE.value,
        execution_status="PENDING",
    )
    missed_level_set.levels.extend([Level(**level) for level in _levels(200, 210)])
    db.add_all([executed_level_set, missed_level_set])
    db.add(
        Position(
            instrument_id=executed_instrument.id,
            trading_day=past_day,
            quantity=1,
            entry_price=110,
            stoploss_price=100,
            trailing_stoploss_price=105,
            high_water_mark=112,
            status="CLOSED",
        )
    )
    db.commit()

    archived_count = archive_past_level_sets(db, today=date(2026, 5, 18))
    archived_executed = db.get(DailyLevelSet, executed_level_set.id)
    archived_missed = db.get(DailyLevelSet, missed_level_set.id)
    db.close()

    assert archived_count == 2
    assert archived_executed.status == LevelSetStatus.EXPIRED.value
    assert archived_executed.execution_status == "EXECUTED"
    assert archived_missed.status == LevelSetStatus.EXPIRED.value
    assert archived_missed.execution_status == "NOT_EXECUTED"


def _db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal()


def _instrument(db, symbol="TEST_CE", token=123):
    instrument = Instrument(
        symbol=symbol,
        exchange="NFO",
        instrument_token=token,
        lot_size=50,
        tick_size=0.05,
    )
    db.add(instrument)
    db.commit()
    db.refresh(instrument)
    return instrument


def _levels(l0, l1):
    return [
        {"level_name": "L0", "price": l0, "sort_order": 0, "role": "STOPLOSS"},
        {"level_name": "L1", "price": l1, "sort_order": 1, "role": "ENTRY"},
    ]
