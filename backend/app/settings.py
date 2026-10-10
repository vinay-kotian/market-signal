import os
from datetime import date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from app.progressive_stop import ProgressiveSettings


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


class TradingTimeConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    market_open_time: time = time(9, 15)
    market_close_time: time = time(15, 30)
    entry_block_after_open_minutes: float = Field(default=10, ge=0, allow_inf_nan=False)
    entry_block_before_close_minutes: float = Field(default=10, ge=0, allow_inf_nan=False)
    mandatory_exit_before_close_minutes: float = Field(default=3, gt=0, allow_inf_nan=False)

    @model_validator(mode='before')
    @classmethod
    def normalize_legacy_times(cls, values):
        # Keep existing absolute-time API/environment inputs usable. New snapshots
        # store the market session and buffers, rather than derived windows.
        if not isinstance(values, dict):
            return values
        values = dict(values)
        for legacy, buffer in LEGACY_TIME_BUFFERS.items():
            value = values.pop(legacy, None)
            if value is None or buffer in values:
                continue
            absolute = TypeAdapter(time).validate_python(value)
            if absolute.tzinfo is not None:
                raise ValueError('Trading times must be local Asia/Kolkata times without offsets')
            boundary = 'market_open_time' if legacy == 'trading_start_time' else 'market_close_time'
            session = TypeAdapter(time).validate_python(values.get(boundary, cls.model_fields[boundary].default))
            if session.tzinfo is not None:
                raise ValueError('Trading times must be local Asia/Kolkata times without offsets')
            anchor = datetime.combine(date(2000, 1, 1), session)
            target = datetime.combine(date(2000, 1, 1), absolute)
            values[buffer] = ((target - anchor) if legacy == 'trading_start_time' else (anchor - target)).total_seconds() / 60
        return values

    @model_validator(mode='after')
    def validate_trading_window(self):
        if any(value.tzinfo is not None for value in (self.market_open_time, self.market_close_time)):
            raise ValueError('Trading times must be local Asia/Kolkata times without offsets')
        opening = datetime.combine(date(2000, 1, 1), self.market_open_time)
        closing = datetime.combine(date(2000, 1, 1), self.market_close_time)
        if opening >= closing:
            raise ValueError('Market opening time must be earlier than closing time')
        duration = (closing - opening).total_seconds() / 60
        if self.entry_block_after_open_minutes + self.entry_block_before_close_minutes >= duration:
            raise ValueError('Entry buffers must leave a positive entry window')
        if self.mandatory_exit_before_close_minutes >= duration:
            raise ValueError('Mandatory exit must occur after market open and before market close')
        if self.mandatory_exit_before_close_minutes > self.entry_block_before_close_minutes:
            raise ValueError('Mandatory exit must not start before the entry cutoff')
        return self

    def shifted_time(self, value, minutes):
        return (datetime.combine(date(2000, 1, 1), value) + timedelta(minutes=minutes)).time()

    @property
    def trading_start_time(self):
        return self.shifted_time(self.market_open_time, self.entry_block_after_open_minutes)

    @property
    def new_trade_cutoff_time(self):
        return self.shifted_time(self.market_close_time, -self.entry_block_before_close_minutes)

    @property
    def mandatory_exit_time(self):
        return self.shifted_time(self.market_close_time, -self.mandatory_exit_before_close_minutes)


LEGACY_TIME_BUFFERS = {
    'trading_start_time': 'entry_block_after_open_minutes',
    'new_trade_cutoff_time': 'entry_block_before_close_minutes',
    'mandatory_exit_time': 'mandatory_exit_before_close_minutes',
}


class TradeSettings(ProgressiveSettings, TradingTimeConfiguration):
    stop_strategy: Literal["PROGRESSIVE", "LEGACY"] = "PROGRESSIVE"
    strategy_version: str = Field(default_factory=lambda: os.getenv("STRATEGY_VERSION", "1.3.0"), min_length=1, pattern=r"\S")
    trade_mode: Literal["PAPER", "LIVE", "BACKTEST"] = "PAPER"
    level_rearm_distance_points: float = Field(default=50, gt=0, allow_inf_nan=False)
    number_of_lots: int = Field(default=1, ge=1)
    stop_loss_percentage: float = Field(default=10, gt=0, lt=100, allow_inf_nan=False)
    trailing_stop_percentage: float = Field(default=10, gt=0, lt=100, allow_inf_nan=False)
    breakeven_protection_enabled: bool = True
    breakeven_activation_percent: float = Field(default=10, ge=0, allow_inf_nan=False)
    breakeven_lock_percent: float = Field(default=0, ge=0, allow_inf_nan=False)

    @model_validator(mode='before')
    @classmethod
    def preserve_legacy_configuration(cls, values):
        legacy = {'stop_loss_percentage', 'trailing_stop_percentage',
                  'breakeven_protection_enabled', 'breakeven_activation_percent', 'breakeven_lock_percent'}
        if isinstance(values, dict) and legacy.intersection(values) and not (
                {'stop_strategy', *ProgressiveSettings.model_fields}.intersection(values)):
            return {**values, 'stop_strategy': 'LEGACY'}
        return values

    @classmethod
    def from_environment(cls):
        values = {name: os.environ[name.upper()] for name in (*cls.model_fields, *LEGACY_TIME_BUFFERS)
                  if name.upper() in os.environ}
        execution_mode = os.getenv('EXECUTION_MODE')
        if execution_mode is not None:
            if execution_mode != 'PAPER':
                raise ValueError('EXECUTION_MODE must be PAPER')
            if values.get('trade_mode', 'PAPER') != execution_mode:
                raise ValueError('EXECUTION_MODE conflicts with TRADE_MODE')
            values['trade_mode'] = execution_mode
        return cls(**values)
