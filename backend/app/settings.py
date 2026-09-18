import os
from datetime import time
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    strategy_version: str = Field(default_factory=lambda: os.getenv("STRATEGY_VERSION", "1.0.0"), min_length=1, pattern=r"\S")
    trade_mode: Literal["PAPER", "LIVE", "BACKTEST"] = "PAPER"
    level_rearm_distance_points: float = Field(default=50, gt=0, allow_inf_nan=False)
    number_of_lots: int = Field(default=1, ge=1)
    stop_loss_percentage: float = Field(default=10, gt=0, lt=100, allow_inf_nan=False)
    trailing_stop_percentage: float = Field(default=10, gt=0, lt=100, allow_inf_nan=False)
    breakeven_protection_enabled: bool = True
    breakeven_activation_percent: float = Field(default=10, ge=0, allow_inf_nan=False)
    breakeven_lock_percent: float = Field(default=0, ge=0, allow_inf_nan=False)
    trading_start_time: time = time(9, 15)
    new_trade_cutoff_time: time = time(15, 15)
    mandatory_exit_time: time = time(15, 25)

    @model_validator(mode='after')
    def validate_times(self):
        times = (self.trading_start_time, self.new_trade_cutoff_time, self.mandatory_exit_time)
        if any(value.tzinfo is not None for value in times):
            raise ValueError('Trading times must be local Asia/Kolkata times without offsets')
        if not times[0] <= times[1] < times[2]:
            raise ValueError('Require trading_start_time <= new_trade_cutoff_time < mandatory_exit_time')
        return self

    @classmethod
    def from_environment(cls):
        values = {name: os.environ[name.upper()] for name in cls.model_fields
                  if name.upper() in os.environ}
        execution_mode = os.getenv('EXECUTION_MODE')
        if execution_mode is not None:
            if execution_mode != 'PAPER':
                raise ValueError('EXECUTION_MODE must be PAPER')
            if values.get('trade_mode', 'PAPER') != execution_mode:
                raise ValueError('EXECUTION_MODE conflicts with TRADE_MODE')
            values['trade_mode'] = execution_mode
        return cls(**values)
