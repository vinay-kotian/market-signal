import os
from typing import Literal

from pydantic import BaseModel, Field


class SignalSettings(BaseModel):
    lookback_minutes: float = Field(default=15, gt=0, allow_inf_nan=False)
    minimum_approach_distance_enabled: bool = False
    minimum_approach_distance_points: float = Field(default=0, ge=0, allow_inf_nan=False)

    @classmethod
    def from_environment(cls):
        names = cls.model_fields
        return cls(**{name: os.environ[name.upper()] for name in names if name.upper() in os.environ})


class OptionSettings(BaseModel):
    itm_depth: int = Field(default=1, ge=1)
    expiry_strategy: Literal["NEAREST"] = "NEAREST"

    @classmethod
    def from_environment(cls):
        return cls(**{name: os.environ[name.upper()] for name in cls.model_fields
                      if name.upper() in os.environ})


class TradeSettings(BaseModel):
    trade_mode: Literal["PAPER", "LIVE"] = "PAPER"
    number_of_lots: int = Field(default=1, ge=1)
    stop_loss_percentage: float = Field(default=10, gt=0, lt=100, allow_inf_nan=False)
    trailing_stop_percentage: float = Field(default=10, gt=0, lt=100, allow_inf_nan=False)
    breakeven_protection_enabled: bool = True
    breakeven_activation_percent: float = Field(default=10, ge=0, allow_inf_nan=False)
    breakeven_lock_percent: float = Field(default=0, ge=0, allow_inf_nan=False)

    @classmethod
    def from_environment(cls):
        return cls(**{name: os.environ[name.upper()] for name in cls.model_fields
                      if name.upper() in os.environ})
