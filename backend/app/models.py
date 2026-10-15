from datetime import date, datetime
from typing import Literal, Optional

from app.timeframes import Timeframe

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class LevelInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    instrument: str = Field(min_length=1)
    price: float = Field(allow_inf_nan=False)
    enabled: bool
    level_date: Optional[date] = None
    timeframe: Optional[Timeframe] = None

    @field_validator('level_date', mode='before')
    @classmethod
    def calendar_date(cls, value):
        if value is None or (isinstance(value, date) and not isinstance(value, datetime)):
            return value
        if not isinstance(value, str):
            raise ValueError('Use a calendar date in YYYY-MM-DD format')
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError('Use a calendar date in YYYY-MM-DD format')
        return value


class Level(LevelInput):
    id: int
    level_date: date
    status: Literal["ACTIVE", "DISARMED", "EXPIRED", "PENDING_ARM"] = "ACTIVE"
    armed_from: Optional[Literal['ABOVE', 'BELOW']] = None

    @computed_field
    @property
    def armed(self) -> bool:
        return self.status == 'ACTIVE'

    activation_reference_price: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class LevelEvent(BaseModel):
    id: int
    level_id: int
    event_type: Literal['LEVEL_DISARMED', 'LEVEL_REARMED']
    underlying_price: float
    timestamp: datetime
    trade_id: Optional[int] = None
