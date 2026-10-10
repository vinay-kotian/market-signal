from app.date_range import date_filters
from fastapi import APIRouter, Request, Depends, Query

from app.option_models import StoredOptionSelection


router = APIRouter(prefix="/option-selections", tags=["option selections"])


@router.get("", response_model=list[StoredOptionSelection])
def list_option_selections(request: Request, filters: dict = Depends(date_filters)):
    return request.app.state.option_repository.recent(**filters)


@router.get('/history')
def option_history(request: Request, page: int = Query(1, ge=1),
                   page_size: int = Query(20, ge=1, le=100),
                   filters: dict = Depends(date_filters)):
    return request.app.state.option_repository.history(page, page_size, **filters)
