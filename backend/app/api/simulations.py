from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.dashboard import dashboard_summary
from backend.app.db.repositories import ensure_demo_level_set
from backend.app.db.session import get_db
from backend.app.market.tick_cache import tick_cache
from backend.app.services.tick_processor import process_tick

router = APIRouter(prefix="/simulations", tags=["simulations"])


@router.post("/demo")
def run_demo_simulation(db: Session = Depends(get_db)) -> dict:
    instrument = ensure_demo_level_set(db, trading_day=date.today())
    tick_cache._latest_ticks.pop(instrument.id, None)

    prices = [108, 110, 118, 120, 126, 130, 124]
    timeline = [
        process_tick(db=db, instrument_token=instrument.instrument_token, last_price=price)
        for price in prices
    ]

    return {
        "instrument": {
            "id": instrument.id,
            "symbol": instrument.symbol,
            "instrument_token": instrument.instrument_token,
        },
        "levels": {"L0": 100, "L1": 110, "L2": 120, "L3": 130},
        "prices": prices,
        "timeline": timeline,
        "dashboard": dashboard_summary(db),
    }
