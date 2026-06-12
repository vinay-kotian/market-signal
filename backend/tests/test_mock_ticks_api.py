from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.enums import LevelSetStatus, PositionStatus
from backend.app.db.session import Base, get_db
from backend.app.main import app
from backend.app.market.tick_cache import tick_cache
from backend.app.models.tables import DailyLevelSet, Instrument, Level, Order, Position


def test_mock_tick_endpoint_persists_paper_position_and_trailing_stop() -> None:
    tick_cache._latest_ticks.clear()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    instrument = Instrument(
        symbol="NIFTY_TEST_CE",
        exchange="NFO",
        instrument_token=1001,
        lot_size=50,
        tick_size=0.05,
    )
    db.add(instrument)
    db.flush()
    level_set = DailyLevelSet(
        instrument_id=instrument.id,
        trading_day=date.today(),
        status=LevelSetStatus.ACTIVE.value,
        created_by="test",
        updated_by="test",
    )
    level_set.levels.extend(
        [
            Level(level_name="L0", price=100, sort_order=0, role="STOPLOSS"),
            Level(level_name="L1", price=110, sort_order=1, role="ENTRY"),
            Level(level_name="L2", price=120, sort_order=2, role="CHECKPOINT"),
        ]
    )
    db.add(level_set)
    db.commit()
    db.close()

    def override_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    first = client.post("/ticks/mock", json={"instrument_token": 1001, "last_price": 108})
    entry = client.post("/ticks/mock", json={"instrument_token": 1001, "last_price": 110})
    checkpoint = client.post("/ticks/mock", json={"instrument_token": 1001, "last_price": 120})

    app.dependency_overrides.clear()

    assert first.status_code == 200
    assert entry.status_code == 200
    assert checkpoint.status_code == 200
    assert entry.json()["results"][0]["success"] is True
    assert checkpoint.json()["position"]["trailing_stoploss_price"] == 115

    verify_db = TestingSessionLocal()
    position = verify_db.scalar(select(Position))
    orders = verify_db.scalars(select(Order)).all()
    verify_db.close()

    assert position is not None
    assert position.status == PositionStatus.OPEN.value
    assert position.entry_price == 110
    assert position.trailing_stoploss_price == 115
    assert len(orders) == 1
    assert orders[0].side == "BUY"


def test_mock_tick_endpoint_publishes_realtime_tick(monkeypatch) -> None:
    tick_cache._latest_ticks.clear()
    published_messages = []
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    instrument = Instrument(
        symbol="NIFTY_TEST_CE",
        exchange="NFO",
        instrument_token=1001,
        lot_size=1,
        tick_size=0.05,
    )
    db.add(instrument)
    db.flush()
    level_set = DailyLevelSet(
        instrument_id=instrument.id,
        trading_day=date.today(),
        status=LevelSetStatus.ACTIVE.value,
        created_by="test",
        updated_by="test",
    )
    level_set.levels.extend(
        [
            Level(level_name="L0", price=100, sort_order=0, role="STOPLOSS"),
            Level(level_name="L1", price=110, sort_order=1, role="ENTRY"),
        ]
    )
    db.add(level_set)
    db.commit()
    db.close()

    def override_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(
        "backend.app.services.tick_processor.realtime_hub.publish",
        published_messages.append,
    )
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    response = client.post("/ticks/mock", json={"instrument_token": 1001, "last_price": 108})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert published_messages[0]["type"] == "tick"
    assert published_messages[0]["tick"]["instrument_token"] == 1001
    assert published_messages[0]["tick"]["last_price"] == 108
    assert published_messages[0]["tick"]["timestamp_ist"].endswith("IST")


def test_mock_tick_endpoint_allows_reentry_after_trade_is_closed() -> None:
    tick_cache._latest_ticks.clear()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    instrument = Instrument(
        symbol="SENSEX_TEST_PE",
        exchange="BFO",
        instrument_token=2002,
        lot_size=1,
        tick_size=0.05,
    )
    db.add(instrument)
    db.flush()
    level_set = DailyLevelSet(
        instrument_id=instrument.id,
        trading_day=date.today(),
        status=LevelSetStatus.ACTIVE.value,
        created_by="test",
        updated_by="test",
    )
    level_set.levels.extend(
        [
            Level(level_name="L0", price=100, sort_order=0, role="STOPLOSS"),
            Level(level_name="L1", price=110, sort_order=1, role="ENTRY"),
            Level(level_name="L2", price=120, sort_order=2, role="CHECKPOINT"),
        ]
    )
    db.add(level_set)
    db.commit()
    db.close()

    def override_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    client.post("/ticks/mock", json={"instrument_token": 2002, "last_price": 108})
    client.post("/ticks/mock", json={"instrument_token": 2002, "last_price": 110})
    client.post("/ticks/mock", json={"instrument_token": 2002, "last_price": 120})
    client.post("/ticks/mock", json={"instrument_token": 2002, "last_price": 114})
    reentry = client.post("/ticks/mock", json={"instrument_token": 2002, "last_price": 109})
    app.dependency_overrides.clear()

    assert reentry.status_code == 200
    assert any(result.get("action", {}).get("side") == "BUY" for result in reentry.json()["results"])

    verify_db = TestingSessionLocal()
    positions = verify_db.scalars(select(Position)).all()
    orders = verify_db.scalars(select(Order)).all()
    verify_db.close()

    assert len(positions) == 2
    assert positions[0].status == PositionStatus.CLOSED.value
    assert positions[1].status == PositionStatus.OPEN.value
    assert [order.side for order in orders] == ["BUY", "SELL", "BUY"]


def test_mock_tick_endpoint_handles_mixed_timestamp_awareness() -> None:
    tick_cache._latest_ticks.clear()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    instrument = Instrument(
        symbol="SENSEX_TEST_PE",
        exchange="BFO",
        instrument_token=3003,
        lot_size=1,
        tick_size=0.05,
    )
    db.add(instrument)
    db.flush()
    level_set = DailyLevelSet(
        instrument_id=instrument.id,
        trading_day=date.today(),
        status=LevelSetStatus.ACTIVE.value,
        created_by="test",
        updated_by="test",
    )
    level_set.levels.extend(
        [
            Level(level_name="L0", price=100, sort_order=0, role="STOPLOSS"),
            Level(level_name="L1", price=110, sort_order=1, role="ENTRY"),
        ]
    )
    db.add(level_set)
    db.commit()
    db.close()

    def override_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    first = client.post(
        "/ticks/mock",
        json={"instrument_token": 3003, "last_price": 108, "timestamp": "2026-05-18T09:15:00"},
    )
    second = client.post(
        "/ticks/mock",
        json={
            "instrument_token": 3003,
            "last_price": 109,
            "timestamp": "2026-05-18T09:15:01+00:00",
        },
    )
    app.dependency_overrides.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["direction"] == "UP"
