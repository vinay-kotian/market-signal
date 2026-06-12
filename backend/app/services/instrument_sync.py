from datetime import date
from typing import Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from backend.app.broker.zerodha_session import ZerodhaSessionClient
from backend.app.db.broker_sessions import get_active_zerodha_session
from backend.app.db.repositories import upsert_instrument
from backend.app.models.tables import AuditLog

DEFAULT_OPTION_EXCHANGES = ("NFO", "BFO")
DEFAULT_OPTION_INSTRUMENT_TYPES = ("CE", "PE", "FUT")
DEFAULT_MARKET_SYNC_PLAN = (
    ("NFO", ("CE", "PE")),
    ("BFO", ("CE", "PE")),
    ("MCX", ("FUT", "CE", "PE")),
)


def sync_zerodha_instruments(
    db: Session,
    exchange: Optional[str] = "NFO",
    limit: Optional[int] = None,
    instrument_types: Optional[Sequence[str]] = DEFAULT_OPTION_INSTRUMENT_TYPES,
) -> Dict[str, object]:
    session = get_active_zerodha_session(db, date.today())
    client = ZerodhaSessionClient(access_token=session.access_token if session else None)._client()
    rows: List[dict] = client.instruments(exchange=exchange) if exchange else client.instruments()
    allowed_types = {instrument_type.upper() for instrument_type in instrument_types or []}

    synced = 0
    for row in rows[:limit] if limit else rows:
        token = row.get("instrument_token")
        symbol = row.get("tradingsymbol") or row.get("name") or str(token)
        row_exchange = row.get("exchange") or exchange or ""
        instrument_type = str(row.get("instrument_type") or "").upper()
        if allowed_types and instrument_type and instrument_type not in allowed_types:
            continue
        if token is None or not row_exchange:
            continue
        upsert_instrument(
            db=db,
            symbol=symbol,
            exchange=row_exchange,
            instrument_token=int(token),
            lot_size=1,
            tick_size=float(row.get("tick_size") or 0.05),
            instrument_type=instrument_type,
        )
        synced += 1

    db.add(
        AuditLog(
            event_type="ZERODHA_INSTRUMENT_SYNC",
            message=f"Synced {synced} instruments from Zerodha {exchange or 'ALL'}",
        )
    )
    db.commit()
    return {"synced": synced, "exchange": exchange or "ALL"}


def sync_zerodha_option_exchanges(
    db: Session,
    exchanges: Sequence[str] = DEFAULT_OPTION_EXCHANGES,
    limit: Optional[int] = None,
    instrument_types: Sequence[str] = DEFAULT_OPTION_INSTRUMENT_TYPES,
) -> Dict[str, object]:
    results = [
        sync_zerodha_instruments(
            db=db,
            exchange=exchange,
            limit=limit,
            instrument_types=instrument_types,
        )
        for exchange in exchanges
    ]
    return {
        "synced": sum(int(result["synced"]) for result in results),
        "exchanges": results,
        "instrument_types": list(instrument_types),
    }


def sync_zerodha_market_universe(
    db: Session,
    limit: Optional[int] = None,
) -> Dict[str, object]:
    results = [
        {
            **sync_zerodha_instruments(
                db=db,
                exchange=exchange,
                limit=limit,
                instrument_types=instrument_types,
            ),
            "instrument_types": list(instrument_types),
        }
        for exchange, instrument_types in DEFAULT_MARKET_SYNC_PLAN
    ]
    return {
        "synced": sum(int(result["synced"]) for result in results),
        "exchanges": results,
    }
