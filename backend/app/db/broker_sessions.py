from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.tables import AuditLog, BrokerSession


def save_zerodha_session(
    db: Session,
    access_token: str,
    public_token: Optional[str],
    user_id: Optional[str],
    user_name: Optional[str],
    trading_day: date,
) -> BrokerSession:
    existing_sessions = db.scalars(
        select(BrokerSession).where(
            BrokerSession.broker == "ZERODHA",
            BrokerSession.trading_day == trading_day,
            BrokerSession.is_active == 1,
        )
    ).all()
    for session in existing_sessions:
        session.is_active = 0

    broker_session = BrokerSession(
        broker="ZERODHA",
        access_token=access_token,
        public_token=public_token,
        user_id=user_id,
        user_name=user_name,
        trading_day=trading_day,
        is_active=1,
        expires_at=datetime.combine(trading_day, time(23, 59, 59)),
    )
    db.add(broker_session)
    db.add(
        AuditLog(
            event_type="ZERODHA_SESSION_CREATED",
            message=f"Zerodha session created for {trading_day}",
        )
    )
    db.commit()
    db.refresh(broker_session)
    return broker_session


def get_active_zerodha_session(db: Session, trading_day: date) -> Optional[BrokerSession]:
    return db.scalar(
        select(BrokerSession)
        .where(
            BrokerSession.broker == "ZERODHA",
            BrokerSession.trading_day == trading_day,
            BrokerSession.is_active == 1,
        )
        .order_by(BrokerSession.created_at.desc())
    )


def deactivate_zerodha_session(db: Session, trading_day: date) -> bool:
    session = get_active_zerodha_session(db, trading_day)
    if not session:
        return False
    session.is_active = 0
    db.add(
        AuditLog(
            event_type="ZERODHA_SESSION_DEACTIVATED",
            message=f"Zerodha session deactivated for {trading_day}",
        )
    )
    db.commit()
    return True
