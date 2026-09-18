from datetime import date
from typing import Optional

from fastapi import APIRouter, Request, Query

from app.signal_models import SignalResult


router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=list[SignalResult])
def list_signals(request: Request, signal_date: Optional[date] = None,
                 instrument: Optional[str] = Query(None, min_length=1, max_length=100),
                 valid: Optional[bool] = None):
    return request.app.state.signal_repository.recent(
        signal_date=signal_date, instrument=instrument, valid=valid)
