from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LevelInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    instrument: str = Field(min_length=1)
    price: float = Field(allow_inf_nan=False)
    enabled: bool
    level_date: Optional[date] = None


class Level(LevelInput):
    id: int
    level_date: date
    status: Literal["ACTIVE", "DISARMED", "EXPIRED"] = "ACTIVE"
    created_at: datetime
    updated_at: datetime


class LevelEvent(BaseModel):
    id: int
    level_id: int
    event_type: Literal['LEVEL_DISARMED', 'LEVEL_REARMED']
    underlying_price: float
    timestamp: datetime
    trade_id: Optional[int] = None
