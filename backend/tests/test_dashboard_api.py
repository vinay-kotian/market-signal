from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.enums import LevelSetStatus
from backend.app.db.session import Base, get_db
from backend.app.main import app
from backend.app.market.tick_cache import tick_cache
from backend.app.models.tables import DailyLevelSet, Instrument, Level


def test_dashboard_summary_includes_mock_tick_state() -> None:
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
    client.post("/ticks/mock", json={"instrument_token": 1001, "last_price": 108})
    client.post("/ticks/mock", json={"instrument_token": 1001, "last_price": 110})
    response = client.get("/dashboard/summary")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["open_positions"] == 1
    assert body["counts"]["recent_orders"] == 1
    assert body["counts"]["latest_prices"] == 1
    assert body["counts"]["tracked_instruments"] == 1
    assert body["latest_prices"][0]["last_price"] == 110
    assert body["latest_prices"][0]["timestamp_ist"].endswith("IST")
    assert body["tracked_instruments"][0]["symbol"] == "NIFTY_TEST_CE"
    assert body["tracked_instruments"][0]["last_price"] == 110
    assert body["tracked_instruments"][0]["last_tick_at_ist"].endswith("IST")
    assert body["tracked_instruments"][0]["trade"]["status"] == "OPEN_TRADE"
    assert body["tracked_instruments"][0]["trade"]["label"] == "Open trade"
    assert body["tracked_instruments"][0]["trade"]["entry_price"] == 110
    assert body["tracked_instruments"][0]["decision"]["state"] == "IN_TRADE"
    assert body["tracked_instruments"][0]["decision"]["entry_price"] == 110
    assert body["tracked_instruments"][0]["levels"][0]["level_name"] == "L0"
    assert body["open_positions"][0]["symbol"] == "NIFTY_TEST_CE"
    assert body["open_positions"][0]["entry_price"] == 110
    assert body["orders"][0]["symbol"] == "NIFTY_TEST_CE"
    assert body["orders"][0]["side"] == "BUY"
    assert body["orders"][0]["reason"] == "L1 entry reached"
    assert body["orders"][0]["created_at_ist"].endswith("IST")
