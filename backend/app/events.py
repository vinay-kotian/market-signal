from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class LevelTriggered(BaseModel):
    id: int
    event_type: Literal["LEVEL_TRIGGERED"] = "LEVEL_TRIGGERED"
    level_id: int
    instrument: str
    level_price: float
    previous_price: Optional[float]
    current_price: float
    triggered_at: datetime
