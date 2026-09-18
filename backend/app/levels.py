from datetime import date
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status

from app.level_repository import LevelRepository
from app.models import Level, LevelInput, LevelEvent


router = APIRouter(prefix="/levels", tags=["levels"])
LevelId = Annotated[int, Path(ge=1, le=9223372036854775807)]


def get_repository(request: Request) -> LevelRepository:
    return request.app.state.level_repository


@router.post("", response_model=Level, status_code=status.HTTP_201_CREATED)
async def create_level(data: LevelInput, request: Request, repository: LevelRepository = Depends(get_repository)):
    level = repository.create(data)
    request.app.state.websocket_hub.publish('LEVEL_UPDATED', dict(level=level))
    return level


@router.get("", response_model=List[Level])
def list_levels(level_date: Optional[date] = None, repository: LevelRepository = Depends(get_repository)):
    return repository.list(level_date)


@router.get("/{id}", response_model=Level)
def get_level(id: LevelId, repository: LevelRepository = Depends(get_repository)):
    level = repository.get(id)
    if level is None:
        raise HTTPException(status_code=404, detail="Level not found")
    return level


@router.put("/{id}", response_model=Level)
async def update_level(
    id: LevelId, data: LevelInput, request: Request, repository: LevelRepository = Depends(get_repository)
):
    try:
        level = repository.update(id, data)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if level is None:
        raise HTTPException(status_code=404, detail="Level not found")
    request.app.state.websocket_hub.publish('LEVEL_UPDATED', dict(level=level))
    return level


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_level(id: LevelId, request: Request, repository: LevelRepository = Depends(get_repository)):
    try:
        deleted = repository.delete(id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not deleted:
        raise HTTPException(status_code=404, detail="Level not found")
    request.app.state.websocket_hub.publish('LEVEL_DELETED', dict(id=id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get('/{id}/events', response_model=List[LevelEvent])
def level_events(id: LevelId, repository: LevelRepository = Depends(get_repository)):
    if repository.get(id) is None:
        raise HTTPException(status_code=404, detail='Level not found')
    return repository.events(id)
