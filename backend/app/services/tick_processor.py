from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.app.core.timezone import as_utc, display_ist_time, iso_utc
from backend.app.db.trading_state import (
    get_active_level_context,
    get_instrument_by_token,
    get_open_position_state,
    persist_workflow_results,
)
from backend.app.dto.trading_dto import Tick
from backend.app.market.agent import MarketAgent
from backend.app.market.tick_cache import tick_cache
from backend.app.services.realtime import realtime_hub
from backend.app.strategy.level_strategy import LevelStrategy
from backend.app.workflows.tick_workflow import TickWorkflow


def process_tick(
    db: Session,
    instrument_token: int,
    last_price: float,
    timestamp: Optional[datetime] = None,
    volume: Optional[int] = None,
) -> dict:
    instrument = get_instrument_by_token(db, instrument_token)
    if not instrument:
        raise ValueError("Instrument token not found")

    trading_day = date.today()
    levels = get_active_level_context(db, instrument.id, trading_day)
    if not levels:
        raise ValueError("No active level set for instrument today")

    tick = Tick(
        instrument_token=instrument.instrument_token,
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        last_price=last_price,
        timestamp=as_utc(timestamp or datetime.utcnow()),
        volume=volume,
    )
    previous_tick = tick_cache.get_previous(instrument.id)
    position = get_open_position_state(db, instrument.id, trading_day)

    workflow = TickWorkflow(strategy=LevelStrategy(trailing_gap=5))
    if previous_tick:
        workflow.previous_ticks[instrument.id] = previous_tick
    if position:
        workflow.positions[instrument.id] = position

    market_context = MarketAgent().build_context(tick, previous_tick)
    results = workflow.handle_tick(tick, levels)
    persist_workflow_results(db, instrument.id, trading_day, results)
    tick_cache.update(tick)

    response = {
        "tick": _jsonable(tick),
        "direction": market_context.direction,
        "velocity_per_second": market_context.velocity_per_second,
        "results": _jsonable(results),
        "position": _jsonable(workflow.positions.get(instrument.id)),
    }
    response["tick"]["timestamp_ist"] = display_ist_time(tick.timestamp)
    realtime_hub.publish({"type": "tick", **response})
    return response


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime):
            return iso_utc(value)
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
