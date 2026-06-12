from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.services.eod_square_off import square_off_open_positions
from backend.app.services.paper_trade_reset import reset_paper_trades_for_day

router = APIRouter(prefix="/trading", tags=["trading"])


@router.post("/eod-square-off")
def eod_square_off(db: Session = Depends(get_db)) -> dict:
    return square_off_open_positions(db, trading_day=date.today())


@router.post("/paper-trades/reset-today")
def reset_today_paper_trades(db: Session = Depends(get_db)) -> dict:
    trading_day = date.today()
    deleted = reset_paper_trades_for_day(db, trading_day=trading_day)
    return {"trading_day": trading_day.isoformat(), **deleted}


@router.post("/paper-trades/reset-today/{instrument_id}")
def reset_today_paper_trades_for_instrument(
    instrument_id: int, db: Session = Depends(get_db)
) -> dict:
    trading_day = date.today()
    deleted = reset_paper_trades_for_day(
        db, trading_day=trading_day, instrument_id=instrument_id
    )
    return {
        "trading_day": trading_day.isoformat(),
        "instrument_id": instrument_id,
        **deleted,
    }
