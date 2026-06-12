from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class InstrumentCreate(BaseModel):
    symbol: str
    exchange: str
    instrument_type: str = ""
    instrument_token: int
    lot_size: int = 1
    tick_size: float = 0.05


class InstrumentRead(InstrumentCreate):
    id: int

    model_config = {"from_attributes": True}


class LevelCreate(BaseModel):
    level_name: str
    price: float = Field(gt=0)
    sort_order: int = Field(ge=0)
    role: str


class DailyLevelSetCreate(BaseModel):
    instrument_id: int
    trading_day: date
    created_by: Optional[str] = None
    levels: List[LevelCreate]


class DailyLevelSetUpdate(BaseModel):
    updated_by: Optional[str] = None
    levels: List[LevelCreate]


class LevelRead(LevelCreate):
    id: int

    model_config = {"from_attributes": True}


class DailyLevelSetRead(BaseModel):
    id: int
    instrument_id: int
    instrument: InstrumentRead
    trading_day: date
    status: str
    execution_status: str
    levels: List[LevelRead]

    model_config = {"from_attributes": True}
