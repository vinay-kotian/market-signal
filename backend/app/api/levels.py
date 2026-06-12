from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db.repositories import (
    DuplicateLevelSetError,
    LockedLevelSetError,
    cancel_daily_level_set,
    create_daily_level_set,
    delete_daily_level_set,
    get_daily_level_set,
    list_daily_level_sets_filtered,
    archive_past_level_sets,
    update_daily_level_set,
)
from backend.app.db.session import get_db
from backend.app.schemas.instruments import (
    DailyLevelSetCreate,
    DailyLevelSetRead,
    DailyLevelSetUpdate,
)

router = APIRouter(prefix="/level-sets", tags=["level-sets"])


@router.post("", response_model=DailyLevelSetRead)
def add_level_set(payload: DailyLevelSetCreate, db: Session = Depends(get_db)):
    levels = [level.model_dump() for level in payload.levels]
    try:
        return create_daily_level_set(
            db=db,
            instrument_id=payload.instrument_id,
            trading_day=payload.trading_day,
            created_by=payload.created_by or "system",
            levels=levels,
        )
    except LockedLevelSetError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except DuplicateLevelSetError:
        raise HTTPException(
            status_code=409,
            detail="Levels already exist for this instrument today. Use Edit to update them.",
        )


@router.get("", response_model=List[DailyLevelSetRead])
def get_level_sets(
    trading_day: Optional[date] = None,
    instrument_id: Optional[int] = None,
    include_cancelled: bool = False,
    db: Session = Depends(get_db),
):
    archive_past_level_sets(db, today=date.today())
    return list_daily_level_sets_filtered(
        db,
        trading_day=trading_day,
        instrument_id=instrument_id,
        include_cancelled=include_cancelled,
    )


@router.get("/{level_set_id}", response_model=DailyLevelSetRead)
def get_level_set(level_set_id: int, db: Session = Depends(get_db)):
    try:
        return get_daily_level_set(db, level_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/{level_set_id}", response_model=DailyLevelSetRead)
def update_level_set(
    level_set_id: int,
    payload: DailyLevelSetUpdate,
    db: Session = Depends(get_db),
):
    try:
        return update_daily_level_set(
            db=db,
            level_set_id=level_set_id,
            updated_by=payload.updated_by or "system",
            levels=[level.model_dump() for level in payload.levels],
        )
    except LockedLevelSetError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{level_set_id}/cancel", response_model=DailyLevelSetRead)
def cancel_level_set(level_set_id: int, db: Session = Depends(get_db)):
    try:
        return cancel_daily_level_set(db=db, level_set_id=level_set_id, updated_by="system")
    except LockedLevelSetError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{level_set_id}")
def delete_level_set(level_set_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        delete_daily_level_set(db=db, level_set_id=level_set_id)
        return {"deleted": True, "level_set_id": level_set_id}
    except LockedLevelSetError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
