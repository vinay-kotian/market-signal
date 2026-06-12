import sys
import types
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.broker import zerodha_config
from backend.app.db.broker_sessions import save_zerodha_session
from backend.app.db.session import Base, get_db
from backend.app.main import app
from backend.app.market.tick_cache import tick_cache
from backend.app.models.tables import Instrument


def test_zerodha_status_reports_missing_credentials(monkeypatch) -> None:
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_api_key", "")
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_api_secret", "")
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_access_token", "")
    client = TestClient(app)

    response = client.get("/zerodha/status")

    assert response.status_code == 200
    body = response.json()
    assert body["api_key_configured"] is False
    assert body["ready_for_websocket"] is False


def test_zerodha_login_url_uses_kite_client_when_configured(monkeypatch) -> None:
    class FakeKiteConnect:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def login_url(self) -> str:
            return f"https://kite.test/login?api_key={self.api_key}"

    fake_module = types.SimpleNamespace(KiteConnect=FakeKiteConnect)
    monkeypatch.setitem(sys.modules, "kiteconnect", fake_module)
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_api_key", "test-key")
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_access_token", "")

    client = TestClient(app)
    response = client.get("/zerodha/login-url")

    assert response.status_code == 200
    assert response.json()["login_url"] == "https://kite.test/login?api_key=test-key"


def test_zerodha_session_is_stored_in_database(monkeypatch) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    class FakeKiteConnect:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.access_token = ""

        def set_access_token(self, access_token: str) -> None:
            self.access_token = access_token

        def generate_session(self, request_token: str, api_secret: str) -> dict:
            return {
                "access_token": f"access-{request_token}",
                "public_token": "public-token",
                "user_id": "AB1234",
                "user_name": "Test User",
            }

        def instruments(self, exchange: str = None) -> list:
            return [
                {
                    "instrument_token": 111,
                    "tradingsymbol": "NIFTY26MAY22000CE",
                    "exchange": exchange or "NFO",
                    "lot_size": 50,
                    "tick_size": 0.05,
                }
            ]

    def override_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    fake_module = types.SimpleNamespace(KiteConnect=FakeKiteConnect)
    monkeypatch.setitem(sys.modules, "kiteconnect", fake_module)
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_api_key", "test-key")
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_api_secret", "test-secret")
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_access_token", "")
    app.dependency_overrides[get_db] = override_db

    client = TestClient(app)
    response = client.post("/zerodha/session", json={"request_token": "req-token"})
    status_response = client.get("/zerodha/status")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"].startswith("Zerodha connected")
    assert response.json()["user_id"] == "AB1234"
    assert response.json()["instrument_sync"]["synced"] == 3
    assert status_response.json()["db_session_active"] is True
    assert status_response.json()["access_token_configured"] is True


def test_zerodha_callback_redirects_to_frontend_after_storing_session(monkeypatch) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    class FakeKiteConnect:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.access_token = ""

        def set_access_token(self, access_token: str) -> None:
            self.access_token = access_token

        def generate_session(self, request_token: str, api_secret: str) -> dict:
            return {
                "access_token": f"access-{request_token}",
                "public_token": "public-token",
                "user_id": "AB1234",
                "user_name": "Test User",
            }

        def instruments(self, exchange: str = None) -> list:
            return [
                {
                    "instrument_token": 111,
                    "tradingsymbol": "NIFTY26MAY22000CE",
                    "exchange": exchange or "NFO",
                    "lot_size": 50,
                    "tick_size": 0.05,
                }
            ]

    def override_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    fake_module = types.SimpleNamespace(KiteConnect=FakeKiteConnect)
    monkeypatch.setitem(sys.modules, "kiteconnect", fake_module)
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_api_key", "test-key")
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_api_secret", "test-secret")
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_access_token", "")
    app.dependency_overrides[get_db] = override_db

    client = TestClient(app, follow_redirects=False)
    response = client.get("/zerodha/callback?request_token=req-token")

    app.dependency_overrides.clear()

    assert response.status_code == 307
    assert response.headers["location"] == "http://127.0.0.1:3000?zerodha=connected&sync=done"


def test_zerodha_stream_status_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/zerodha/stream/status")

    assert response.status_code == 200
    assert "running" in response.json()


def test_zerodha_ltp_fetches_and_caches_selected_instrument_price(monkeypatch) -> None:
    tick_cache._latest_ticks.clear()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    class FakeKiteConnect:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.access_token = ""

        def set_access_token(self, access_token: str) -> None:
            self.access_token = access_token

        def ltp(self, instruments: list) -> dict:
            assert instruments == ["MCX:CRUDEOIL26JUN9800CE"]
            return {"MCX:CRUDEOIL26JUN9800CE": {"last_price": 101.5}}

    db = TestingSessionLocal()
    instrument = Instrument(
        symbol="CRUDEOIL26JUN9800CE",
        exchange="MCX",
        instrument_type="CE",
        instrument_token=144911879,
        lot_size=1,
        tick_size=0.1,
    )
    db.add(instrument)
    db.flush()
    save_zerodha_session(
        db=db,
        access_token="access-token",
        public_token=None,
        user_id="AB1234",
        user_name="Test User",
        trading_day=date.today(),
    )
    instrument_id = instrument.id
    db.commit()
    db.close()

    def override_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setitem(sys.modules, "kiteconnect", types.SimpleNamespace(KiteConnect=FakeKiteConnect))
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_api_key", "test-key")
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    response = client.get(f"/zerodha/ltp?instrument_id={instrument_id}")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "CRUDEOIL26JUN9800CE"
    assert body["exchange"] == "MCX"
    assert body["instrument_type"] == "CE"
    assert body["last_price"] == 101.5
    assert body["timestamp_ist"].endswith("IST")
    assert tick_cache.latest()[instrument_id].last_price == 101.5
