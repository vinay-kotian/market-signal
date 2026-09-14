from fastapi import APIRouter, Request

from app.signal_models import SignalResult


router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=list[SignalResult])
def list_signals(request: Request):
    return request.app.state.signal_repository.recent()
