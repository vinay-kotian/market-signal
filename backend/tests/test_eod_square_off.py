from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.enums import PositionStatus
from backend.app.db.session import Base, get_db
from backend.app.dto.trading_dto import Tick
from backend.app.main import app
from backend.app.market.tick_cache import tick_cache
from backend.app.models.tables import AuditLog, Instrument, Order, Position


def test_eod_square_off_closes_open_position_at_latest_price() -> None:
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
    position = Position(
        instrument_id=instrument.id,
        trading_day=date.today(),
        quantity=1,
        entry_price=110,
        stoploss_price=100,
        trailing_stoploss_price=115,
        high_water_mark=120,
        status=PositionStatus.OPEN.value,
    )
    db.add(position)
    db.commit()
    tick_cache.update(
        Tick(
            instrument_token=1001,
            instrument_id=instrument.id,
            symbol="NIFTY_TEST_CE",
            last_price=118,
            timestamp=datetime.utcnow(),
        )
    )
    db.close()

    def override_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    response = client.post("/trading/eod-square-off")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["closed"][0]["exit_price"] == 118
    assert response.json()["closed"][0]["realized_pnl"] == 8

    verify = TestingSessionLocal()
    closed_position = verify.scalar(select(Position))
    order = verify.scalar(select(Order))
    verify.close()

    assert closed_position.status == PositionStatus.CLOSED.value
    assert closed_position.exit_price == 118
    assert order.side == "SELL"
    assert order.reason == "EOD square-off"


def test_eod_square_off_skips_when_latest_price_missing() -> None:
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
    db.add(
        Position(
            instrument_id=instrument.id,
            trading_day=date.today(),
            quantity=1,
            entry_price=110,
            stoploss_price=100,
            trailing_stoploss_price=115,
            high_water_mark=120,
            status=PositionStatus.OPEN.value,
        )
    )
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
    response = client.post("/trading/eod-square-off")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["closed"] == []
    assert response.json()["skipped"][0]["reason"] == "No latest price available"


def test_reset_today_paper_trades_deletes_positions_orders_and_trade_audit() -> None:
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
    position = Position(
        instrument_id=instrument.id,
        trading_day=date.today(),
        quantity=1,
        entry_price=110,
        stoploss_price=100,
        trailing_stoploss_price=115,
        high_water_mark=120,
        status=PositionStatus.CLOSED.value,
        exit_price=115,
        realized_pnl=5,
    )
    db.add(position)
    db.flush()
    db.add(
        Order(
            instrument_id=instrument.id,
            position_id=position.id,
            side="BUY",
            quantity=1,
            price=110,
            reason="L1 entry reached",
        )
    )
    db.add(
        AuditLog(
            event_type="PAPER_EXECUTION",
            instrument_id=instrument.id,
            message="BUY 1 at 110",
        )
    )
    db.add(
        AuditLog(
            event_type="LEVEL_SET_CREATED",
            instrument_id=instrument.id,
            message="Keep this non-trade audit event",
        )
    )
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
    response = client.post("/trading/paper-trades/reset-today")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["positions_deleted"] == 1
    assert response.json()["orders_deleted"] == 1
    assert response.json()["audit_events_deleted"] == 1

    verify = TestingSessionLocal()
    assert verify.scalars(select(Position)).all() == []
    assert verify.scalars(select(Order)).all() == []
    remaining_audit = verify.scalar(select(AuditLog))
    verify.close()

    assert remaining_audit.event_type == "LEVEL_SET_CREATED"


def test_reset_today_paper_trades_for_one_instrument_keeps_other_trades() -> None:
    tick_cache._latest_ticks.clear()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    first = Instrument(
        symbol="SENSEX_TEST_PE",
        exchange="BFO",
        instrument_token=1001,
        lot_size=1,
        tick_size=0.05,
    )
    second = Instrument(
        symbol="CRUDEOIL_TEST_CE",
        exchange="MCX",
        instrument_token=2002,
        lot_size=1,
        tick_size=0.1,
    )
    db.add_all([first, second])
    db.flush()
    for instrument in (first, second):
        position = Position(
            instrument_id=instrument.id,
            trading_day=date.today(),
            quantity=1,
            entry_price=110,
            stoploss_price=100,
            trailing_stoploss_price=115,
            high_water_mark=120,
            status=PositionStatus.CLOSED.value,
            exit_price=115,
            realized_pnl=5,
        )
        db.add(position)
        db.flush()
        db.add(
            Order(
                instrument_id=instrument.id,
                position_id=position.id,
                side="BUY",
                quantity=1,
                price=110,
                reason="L1 entry reached",
            )
        )
        db.add(
            AuditLog(
                event_type="PAPER_EXECUTION",
                instrument_id=instrument.id,
                message="BUY 1 at 110",
            )
        )
    first_id = first.id
    second_id = second.id
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
    response = client.post(f"/trading/paper-trades/reset-today/{first_id}")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["instrument_id"] == first_id
    assert response.json()["positions_deleted"] == 1
    assert response.json()["orders_deleted"] == 1
    assert response.json()["audit_events_deleted"] == 1

    verify = TestingSessionLocal()
    remaining_positions = verify.scalars(select(Position)).all()
    remaining_orders = verify.scalars(select(Order)).all()
    remaining_audits = verify.scalars(select(AuditLog)).all()
    verify.close()

    assert [position.instrument_id for position in remaining_positions] == [second_id]
    assert [order.instrument_id for order in remaining_orders] == [second_id]
    assert [audit.instrument_id for audit in remaining_audits] == [second_id]
