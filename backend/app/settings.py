import os

from pydantic import BaseModel, Field


class SignalSettings(BaseModel):
    lookback_minutes: float = Field(default=15, gt=0, allow_inf_nan=False)
    minimum_approach_distance_enabled: bool = False
    minimum_approach_distance_points: float = Field(default=0, ge=0, allow_inf_nan=False)

    @classmethod
    def from_environment(cls):
        names = cls.model_fields
        return cls(**{name: os.environ[name.upper()] for name in names if name.upper() in os.environ})
