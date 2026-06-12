from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.dto.trading_dto import LevelContext, LevelDTO, Tick
from backend.app.schemas.backtests import ReplayRequest
from backend.app.strategy.level_strategy import LevelStrategy
from backend.app.workflows.tick_workflow import TickWorkflow

router = APIRouter(prefix="/backtests", tags=["backtests"])


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


@router.post("/replay")
def replay_ticks(payload: ReplayRequest) -> dict:
    if len(payload.levels) < 2:
        raise HTTPException(status_code=422, detail="At least L0 and L1 are required")

    level_context = LevelContext(
        instrument_id=payload.instrument_id,
        trading_day=payload.trading_day,
        levels=tuple(
            LevelDTO(
                name=level.name,
                price=level.price,
                sort_order=index,
                role=level.role,
            )
            for index, level in enumerate(payload.levels)
        ),
    )
    workflow = TickWorkflow(strategy=LevelStrategy(trailing_gap=payload.trailing_gap))

    started_at = datetime.combine(payload.trading_day, datetime.min.time())
    timeline = []
    for index, replay_tick in enumerate(payload.ticks):
        tick = Tick(
            instrument_token=payload.instrument_token,
            instrument_id=payload.instrument_id,
            symbol=payload.symbol,
            last_price=replay_tick.price,
            timestamp=replay_tick.timestamp or started_at + timedelta(seconds=index),
            volume=replay_tick.volume,
        )
        results = workflow.handle_tick(tick, level_context)
        timeline.append(
            {
                "tick": _jsonable(tick),
                "results": _jsonable(results),
                "position": _jsonable(workflow.positions.get(payload.instrument_id)),
            }
        )

    return {"timeline": timeline}
