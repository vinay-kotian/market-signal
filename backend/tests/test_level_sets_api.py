from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.session import Base, get_db
from backend.app.main import app
from backend.app.models.tables import Instrument


def test_level_sets_api_returns_instrument_and_updates_today_levels() -> None:
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
    db.commit()
    db.refresh(instrument)
    db.close()

    def override_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    create_response = client.post(
        "/level-sets",
        json={
            "instrument_id": instrument.id,
            "trading_day": date.today().isoformat(),
            "created_by": "test",
            "levels": [
                {"level_name": "L0", "price": 100, "sort_order": 0, "role": "STOPLOSS"},
                {"level_name": "L1", "price": 110, "sort_order": 1, "role": "ENTRY"},
                {"level_name": "L2", "price": 120, "sort_order": 2, "role": "CHECKPOINT"},
            ],
        },
    )
    level_set_id = create_response.json()["id"]

    list_response = client.get(f"/level-sets?trading_day={date.today().isoformat()}")
    update_response = client.put(
        f"/level-sets/{level_set_id}",
        json={
            "updated_by": "test",
            "levels": [
                {"level_name": "L0", "price": 101, "sort_order": 0, "role": "STOPLOSS"},
                {"level_name": "L1", "price": 111, "sort_order": 1, "role": "ENTRY"},
                {"level_name": "L2", "price": 121, "sort_order": 2, "role": "CHECKPOINT"},
            ],
        },
    )
    duplicate_response = client.post(
        "/level-sets",
        json={
            "instrument_id": instrument.id,
            "trading_day": date.today().isoformat(),
            "created_by": "test",
            "levels": [
                {"level_name": "L0", "price": 102, "sort_order": 0, "role": "STOPLOSS"},
                {"level_name": "L1", "price": 112, "sort_order": 1, "role": "ENTRY"},
                {"level_name": "L2", "price": 122, "sort_order": 2, "role": "CHECKPOINT"},
            ],
        },
    )
    delete_response = client.delete(f"/level-sets/{level_set_id}")
    after_delete_response = client.get(f"/level-sets?trading_day={date.today().isoformat()}")
    app.dependency_overrides.clear()

    assert create_response.status_code == 200
    assert list_response.status_code == 200
    assert update_response.status_code == 200
    assert duplicate_response.status_code == 409
    assert delete_response.status_code == 200
    assert after_delete_response.status_code == 200
    assert list_response.json()[0]["instrument"]["symbol"] == "NIFTY_TEST_CE"
    assert update_response.json()["instrument"]["symbol"] == "NIFTY_TEST_CE"
    assert update_response.json()["levels"][0]["price"] == 101
    assert duplicate_response.json()["detail"] == (
        "Levels already exist for this instrument today. Use Edit to update them."
    )
    assert delete_response.json()["deleted"] is True
    assert after_delete_response.json() == []


def test_level_sets_api_hides_cancelled_by_default() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    instrument = Instrument(
        symbol="NIFTY_TEST_PE",
        exchange="NFO",
        instrument_token=1002,
        lot_size=1,
        tick_size=0.05,
    )
    db.add(instrument)
    db.commit()
    db.refresh(instrument)
    db.close()

    def override_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    create_response = client.post(
        "/level-sets",
        json={
            "instrument_id": instrument.id,
            "trading_day": date.today().isoformat(),
            "created_by": "test",
            "levels": [
                {"level_name": "L0", "price": 100, "sort_order": 0, "role": "STOPLOSS"},
                {"level_name": "L1", "price": 110, "sort_order": 1, "role": "ENTRY"},
            ],
        },
    )
    level_set_id = create_response.json()["id"]
    cancel_response = client.post(f"/level-sets/{level_set_id}/cancel")
    default_list_response = client.get(f"/level-sets?trading_day={date.today().isoformat()}")
    history_list_response = client.get(
        f"/level-sets?trading_day={date.today().isoformat()}&include_cancelled=true"
    )
    app.dependency_overrides.clear()

    assert cancel_response.status_code == 200
    assert default_list_response.status_code == 200
    assert default_list_response.json() == []
    assert history_list_response.status_code == 200
    assert history_list_response.json()[0]["status"] == "CANCELLED"
