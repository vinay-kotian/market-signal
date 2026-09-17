from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status

from app.level_repository import LevelRepository
from app.models import Level, LevelInput, LevelEvent


router = APIRouter(prefix="/levels", tags=["levels"])
LevelId = Annotated[int, Path(ge=1, le=9223372036854775807)]


def get_repository(request: Request) -> LevelRepository:
    return LevelRepository(request.app.state.database_path)


@router.post("", response_model=Level, status_code=status.HTTP_201_CREATED)
def create_level(data: LevelInput, repository: LevelRepository = Depends(get_repository)):
    return repository.create(data)


@router.get("", response_model=List[Level])
def list_levels(repository: LevelRepository = Depends(get_repository)):
    return repository.list()


@router.get("/{id}", response_model=Level)
def get_level(id: LevelId, repository: LevelRepository = Depends(get_repository)):
    level = repository.get(id)
    if level is None:
        raise HTTPException(status_code=404, detail="Level not found")
    return level


@router.put("/{id}", response_model=Level)
def update_level(
    id: LevelId, data: LevelInput, repository: LevelRepository = Depends(get_repository)
):
    level = repository.update(id, data)
    if level is None:
        raise HTTPException(status_code=404, detail="Level not found")
    return level


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_level(id: LevelId, repository: LevelRepository = Depends(get_repository)):
    if not repository.delete(id):
        raise HTTPException(status_code=404, detail="Level not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get('/{id}/events', response_model=List[LevelEvent])
def level_events(id: LevelId, repository: LevelRepository = Depends(get_repository)):
    if repository.get(id) is None:
        raise HTTPException(status_code=404, detail='Level not found')
    return repository.events(id)
