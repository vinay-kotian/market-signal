from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.broker.zerodha_config import zerodha_settings
from backend.app.models.tables import AuditLog, BrokerConfig


ZERODHA_BROKER = "ZERODHA"


@dataclass(frozen=True)
class EffectiveZerodhaConfig:
    kite_api_key: str
    kite_api_secret: str
    kite_access_token: str
    kite_redirect_url: str
    source: str


def get_zerodha_broker_config(db: Session) -> Optional[BrokerConfig]:
    return db.scalar(select(BrokerConfig).where(BrokerConfig.broker == ZERODHA_BROKER))


def save_zerodha_broker_config(
    db: Session,
    api_key: str,
    api_secret: Optional[str],
    redirect_url: str,
    updated_by: str = "frontend",
) -> BrokerConfig:
    config = get_zerodha_broker_config(db)
    if config is None:
        config = BrokerConfig(broker=ZERODHA_BROKER)
        db.add(config)

    config.api_key = api_key.strip()
    if api_secret is not None:
        config.api_secret = api_secret.strip()
    config.redirect_url = redirect_url.strip()
    config.updated_by = updated_by
    db.add(
        AuditLog(
            event_type="ZERODHA_CONFIG_UPDATED",
            message="Zerodha broker configuration updated",
        )
    )
    db.commit()
    db.refresh(config)
    return config


def effective_zerodha_config(db: Optional[Session] = None) -> EffectiveZerodhaConfig:
    config = None
    if db is not None:
        config = get_zerodha_broker_config(db)
    else:
        try:
            from backend.app.db.session import SessionLocal

            session = SessionLocal()
            try:
                config = get_zerodha_broker_config(session)
            finally:
                session.close()
        except SQLAlchemyError:
            config = None

    if config is None:
        return EffectiveZerodhaConfig(
            kite_api_key=zerodha_settings.kite_api_key,
            kite_api_secret=zerodha_settings.kite_api_secret,
            kite_access_token=zerodha_settings.kite_access_token,
            kite_redirect_url=zerodha_settings.kite_redirect_url,
            source="env",
        )

    return EffectiveZerodhaConfig(
        kite_api_key=config.api_key or zerodha_settings.kite_api_key,
        kite_api_secret=config.api_secret or zerodha_settings.kite_api_secret,
        kite_access_token=zerodha_settings.kite_access_token,
        kite_redirect_url=config.redirect_url or zerodha_settings.kite_redirect_url,
        source="database",
    )
