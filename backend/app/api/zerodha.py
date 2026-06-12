from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.broker.zerodha_market_data import ZerodhaNotConfiguredError
from backend.app.broker.zerodha_session import ZerodhaSessionClient
from backend.app.core.config import settings
from backend.app.core.timezone import as_utc, display_ist_time, iso_utc
from backend.app.db.broker_sessions import (
    deactivate_zerodha_session,
    get_active_zerodha_session,
    save_zerodha_session,
)
from backend.app.db.session import get_db
from backend.app.dto.trading_dto import Tick
from backend.app.market.tick_cache import tick_cache
from backend.app.models.tables import Instrument
from backend.app.schemas.zerodha import ZerodhaSessionRequest
from backend.app.services.instrument_sync import sync_zerodha_market_universe
from backend.app.services.realtime import realtime_hub
from backend.app.services.zerodha_stream import zerodha_stream_service

router = APIRouter(prefix="/zerodha", tags=["zerodha"])


@router.get("/status")
def zerodha_status(db: Session = Depends(get_db)) -> dict:
    trading_day = ZerodhaSessionClient.trading_day()
    active_session = get_active_zerodha_session(db, trading_day)
    status = ZerodhaSessionClient().status(
        active_token=active_session.access_token if active_session else None
    )
    status["trading_day"] = trading_day.isoformat()
    status["session_user"] = active_session.user_name if active_session else None
    return status


@router.get("/login-url")
def zerodha_login_url() -> dict:
    try:
        return {"login_url": ZerodhaSessionClient().login_url()}
    except ZerodhaNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/login")
def zerodha_login():
    try:
        return RedirectResponse(ZerodhaSessionClient().login_url())
    except ZerodhaNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/callback")
def zerodha_callback(request_token: str, db: Session = Depends(get_db)):
    try:
        session = ZerodhaSessionClient().generate_session(request_token)
    except ZerodhaNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    broker_session = save_zerodha_session(
        db=db,
        access_token=session["access_token"],
        public_token=session.get("public_token"),
        user_id=session.get("user_id"),
        user_name=session.get("user_name"),
        trading_day=ZerodhaSessionClient.trading_day(),
    )
    try:
        sync_zerodha_market_universe(db=db)
        return RedirectResponse(f"{settings.frontend_url}?zerodha=connected&sync=done")
    except Exception:
        return RedirectResponse(f"{settings.frontend_url}?zerodha=connected&sync=failed")


@router.post("/session")
def zerodha_session(payload: ZerodhaSessionRequest, db: Session = Depends(get_db)) -> dict:
    try:
        session = ZerodhaSessionClient().generate_session(payload.request_token)
    except ZerodhaNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    broker_session = save_zerodha_session(
        db=db,
        access_token=session["access_token"],
        public_token=session.get("public_token"),
        user_id=session.get("user_id"),
        user_name=session.get("user_name"),
        trading_day=ZerodhaSessionClient.trading_day(),
    )
    sync_result = None
    try:
        sync_result = sync_zerodha_market_universe(db=db)
    except Exception as exc:
        sync_result = {"synced": 0, "error": str(exc)}
    return {
        "message": "Zerodha connected. Access token stored for today's trading session.",
        "session_id": broker_session.id,
        "trading_day": broker_session.trading_day.isoformat(),
        "user_id": session.get("user_id"),
        "user_name": session.get("user_name"),
        "instrument_sync": sync_result,
    }


@router.post("/logout")
def zerodha_logout(db: Session = Depends(get_db)) -> dict:
    deactivated = deactivate_zerodha_session(db, date.today())
    return {"deactivated": deactivated}


@router.get("/ltp")
def zerodha_ltp(instrument_id: int, db: Session = Depends(get_db)) -> dict:
    instrument = db.scalar(select(Instrument).where(Instrument.id == instrument_id))
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found")

    active_session = get_active_zerodha_session(db, ZerodhaSessionClient.trading_day())
    if not active_session:
        raise HTTPException(status_code=409, detail="Connect Zerodha before fetching live price")

    try:
        client = ZerodhaSessionClient(access_token=active_session.access_token)._client()
        quote_key = f"{instrument.exchange}:{instrument.symbol}"
        ltp_payload = client.ltp([quote_key])
    except ZerodhaNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Unable to fetch Zerodha LTP: {exc}")

    quote = ltp_payload.get(quote_key)
    if not quote or quote.get("last_price") is None:
        raise HTTPException(status_code=404, detail="Zerodha did not return a price")

    timestamp = as_utc(datetime.utcnow())
    tick = Tick(
        instrument_token=instrument.instrument_token,
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        last_price=float(quote["last_price"]),
        timestamp=timestamp,
    )
    tick_cache.update(tick)
    response = {
        "instrument_id": instrument.id,
        "instrument_token": instrument.instrument_token,
        "symbol": instrument.symbol,
        "exchange": instrument.exchange,
        "instrument_type": instrument.instrument_type,
        "last_price": tick.last_price,
        "timestamp": iso_utc(timestamp),
        "timestamp_ist": display_ist_time(timestamp),
    }
    realtime_hub.publish({"type": "ltp", "tick": response})
    return response


@router.post("/stream/start")
def zerodha_stream_start(db: Session = Depends(get_db)) -> dict:
    try:
        return zerodha_stream_service.start(db)
    except ZerodhaNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/stream/stop")
def zerodha_stream_stop() -> dict:
    return zerodha_stream_service.stop()


@router.get("/stream/status")
def zerodha_stream_status() -> dict:
    return zerodha_stream_service.status()
