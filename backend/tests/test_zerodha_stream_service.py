from datetime import date, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.enums import LevelSetStatus, PositionStatus
from backend.app.core.config import TradingMode, settings
from backend.app.db.broker_sessions import save_zerodha_session
from backend.app.db.session import Base
from backend.app.dto.trading_dto import Tick
from backend.app.market.tick_cache import tick_cache
from backend.app.models.tables import DailyLevelSet, Instrument, Level, Position
from backend.app.services.zerodha_stream import ZerodhaStreamService


class FakeStreamClient:
    def __init__(self, token_map, access_token: str) -> None:
        self.token_map = token_map
        self.access_token = access_token
        self._ticker = None
        self.updated_token_maps = []

    def start(self, instrument_tokens, on_tick) -> None:
        token = instrument_tokens[0]
        on_tick(
            Tick(
                instrument_token=token,
                instrument_id=self.token_map[token],
                symbol="DEMO_NIFTY_CE",
                last_price=108,
                timestamp=datetime(2026, 5, 18, 9, 15),
            )
        )
        on_tick(
            Tick(
                instrument_token=token,
                instrument_id=self.token_map[token],
                symbol="DEMO_NIFTY_CE",
                last_price=110,
                timestamp=datetime(2026, 5, 18, 9, 16),
            )
        )

    def update_subscriptions(self, token_to_instrument_id) -> None:
        self.token_map = token_to_instrument_id
        self.updated_token_maps.append(token_to_instrument_id)


def test_zerodha_stream_start_processes_ticks_into_paper_position(monkeypatch) -> None:
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
        symbol="DEMO_NIFTY_CE",
        exchange="NFO",
        instrument_token=900001,
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
    save_zerodha_session(
        db=db,
        access_token="access-token",
        public_token=None,
        user_id="AB1234",
        user_name="Test User",
        trading_day=date.today(),
    )
    db.commit()
    db.close()

    monkeypatch.setattr("backend.app.services.zerodha_stream.SessionLocal", TestingSessionLocal)

    service = ZerodhaStreamService()
    session = TestingSessionLocal()
    status = service.start(session, client_factory=FakeStreamClient)
    session.close()

    verify = TestingSessionLocal()
    position = verify.scalar(select(Position))
    verify.close()

    assert status["running"] is True
    assert status["processed_ticks"] == 2
    assert position is not None
    assert position.status == PositionStatus.OPEN.value
    assert position.entry_price == 110


def test_zerodha_stream_refuses_when_live_trading_enabled(monkeypatch) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    monkeypatch.setattr(settings, "trading_mode", TradingMode.PAPER)
    monkeypatch.setattr(settings, "enable_live_trading", True)

    service = ZerodhaStreamService()
    try:
        service.start(db, client_factory=FakeStreamClient)
    except Exception as exc:
        assert "live trading is enabled" in str(exc)
    else:
        raise AssertionError("Stream should refuse to start when live trading is enabled")
    finally:
        db.close()


def test_zerodha_stream_refuses_malformed_levels(monkeypatch) -> None:
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
        symbol="BAD_LEVEL_CE",
        exchange="NFO",
        instrument_token=900002,
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
            Level(level_name="L0", price=120, sort_order=0, role="STOPLOSS"),
            Level(level_name="L1", price=110, sort_order=1, role="ENTRY"),
        ]
    )
    db.add(level_set)
    save_zerodha_session(
        db=db,
        access_token="access-token",
        public_token=None,
        user_id="AB1234",
        user_name="Test User",
        trading_day=date.today(),
    )
    db.commit()

    monkeypatch.setattr(settings, "trading_mode", TradingMode.PAPER)
    monkeypatch.setattr(settings, "enable_live_trading", False)

    service = ZerodhaStreamService()
    try:
        service.start(db, client_factory=FakeStreamClient)
    except Exception as exc:
        assert "L0 must be below L1" in str(exc)
    else:
        raise AssertionError("Stream should refuse malformed levels")
    finally:
        db.close()


def test_zerodha_stream_start_refreshes_running_subscriptions(monkeypatch) -> None:
    tick_cache._latest_ticks.clear()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    first_instrument = Instrument(
        symbol="SENSEX_TEST_CE",
        exchange="BFO",
        instrument_token=1001,
        lot_size=1,
        tick_size=0.05,
    )
    db.add(first_instrument)
    db.flush()
    first_level_set = DailyLevelSet(
        instrument_id=first_instrument.id,
        trading_day=date.today(),
        status=LevelSetStatus.ACTIVE.value,
        created_by="test",
        updated_by="test",
    )
    first_level_set.levels.extend(
        [
            Level(level_name="L0", price=100, sort_order=0, role="STOPLOSS"),
            Level(level_name="L1", price=110, sort_order=1, role="ENTRY"),
        ]
    )
    db.add(first_level_set)
    save_zerodha_session(
        db=db,
        access_token="access-token",
        public_token=None,
        user_id="AB1234",
        user_name="Test User",
        trading_day=date.today(),
    )
    db.commit()

    monkeypatch.setattr("backend.app.services.zerodha_stream.SessionLocal", TestingSessionLocal)
    service = ZerodhaStreamService()
    start_status = service.start(db, client_factory=FakeStreamClient)

    second_instrument = Instrument(
        symbol="CRUDEOIL26JUN9800CE",
        exchange="MCX",
        instrument_type="CE",
        instrument_token=2002,
        lot_size=1,
        tick_size=0.1,
    )
    db.add(second_instrument)
    db.flush()
    second_level_set = DailyLevelSet(
        instrument_id=second_instrument.id,
        trading_day=date.today(),
        status=LevelSetStatus.ACTIVE.value,
        created_by="test",
        updated_by="test",
    )
    second_level_set.levels.extend(
        [
            Level(level_name="L0", price=90, sort_order=0, role="STOPLOSS"),
            Level(level_name="L1", price=100, sort_order=1, role="ENTRY"),
        ]
    )
    db.add(second_level_set)
    db.commit()

    refresh_status = service.start(db, client_factory=FakeStreamClient)
    db.close()

    assert start_status["instrument_tokens"] == [1001]
    assert refresh_status["subscription_refreshed"] is True
    assert refresh_status["instrument_tokens"] == [1001, 2002]
    assert refresh_status["added_tokens"] == [2002]
    assert service.client.updated_token_maps[-1][2002] == second_instrument.id
