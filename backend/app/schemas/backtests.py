from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ReplayLevel(BaseModel):
    name: str
    price: float = Field(gt=0)
    role: str


class ReplayTick(BaseModel):
    price: float = Field(gt=0)
    timestamp: Optional[datetime] = None
    volume: Optional[int] = None


class ReplayRequest(BaseModel):
    instrument_id: int = 1
    instrument_token: int = 1001
    symbol: str = "DEMO_OPTION"
    trading_day: date
    trailing_gap: float = 5.0
    levels: List[ReplayLevel]
    ticks: List[ReplayTick]

