from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class MockTickRequest(BaseModel):
    instrument_token: int
    last_price: float = Field(gt=0)
    timestamp: Optional[datetime] = None
    volume: Optional[int] = None

