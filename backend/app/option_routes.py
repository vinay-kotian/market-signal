from fastapi import APIRouter, Request

from app.option_models import StoredOptionSelection


router = APIRouter(prefix="/option-selections", tags=["option selections"])


@router.get("", response_model=list[StoredOptionSelection])
def list_option_selections(request: Request):
    return request.app.state.option_repository.recent()
