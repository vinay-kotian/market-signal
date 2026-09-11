from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LevelInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    instrument: str = Field(min_length=1)
    price: float = Field(allow_inf_nan=False)
    enabled: bool


class Level(LevelInput):
    id: int
    created_at: datetime
    updated_at: datetime
