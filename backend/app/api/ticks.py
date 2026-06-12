from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.ticks import MockTickRequest
from backend.app.services.tick_processor import process_tick

router = APIRouter(prefix="/ticks", tags=["ticks"])


@router.post("/mock")
def process_mock_tick(payload: MockTickRequest, db: Session = Depends(get_db)) -> dict:
    try:
        return process_tick(
            db=db,
            instrument_token=payload.instrument_token,
            last_price=payload.last_price,
            timestamp=payload.timestamp,
            volume=payload.volume,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
