from datetime import datetime
from typing import Literal, Optional

from app.timeframes import Timeframe

import json
from pydantic import BaseModel, Field, field_validator


class SignalAnalysis(BaseModel):
    decision_context: dict = Field(default_factory=dict)

    @field_validator('decision_context', mode='before')
    @classmethod
    def decode_context(cls, value):
        return json.loads(value) if isinstance(value, str) else value

    trigger_id: int
    level_id: int
    instrument: str
    level: float
    timeframe: Optional[Timeframe] = None
    trigger_price: float
    direction: Optional[Literal["FROM_ABOVE", "FROM_BELOW"]]
    approach_distance: Optional[float]
    valid: bool
    rejection_reason: Optional[Literal["MINIMUM_DISTANCE_NOT_MET", "INSUFFICIENT_PRICE_HISTORY"]]
    timestamp: datetime


class SignalResult(SignalAnalysis):
    id: int
