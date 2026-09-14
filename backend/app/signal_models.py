from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class SignalAnalysis(BaseModel):
    trigger_id: int
    level_id: int
    instrument: str
    level: float
    trigger_price: float
    direction: Optional[Literal["FROM_ABOVE", "FROM_BELOW"]]
    approach_distance: Optional[float]
    valid: bool
    rejection_reason: Optional[Literal["MINIMUM_DISTANCE_NOT_MET", "INSUFFICIENT_PRICE_HISTORY"]]
    timestamp: datetime


class SignalResult(SignalAnalysis):
    id: int
