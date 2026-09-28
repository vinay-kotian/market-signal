"""Broker-independent progressive protection, using decimal price boundaries."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProgressiveSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    initial_stop_loss_pct: float = Field(default=10, gt=0, lt=100, allow_inf_nan=False)
    profit_lock_trigger_pct: float = Field(default=10, gt=0, allow_inf_nan=False)
    profit_lock_pct: float = Field(default=5, ge=0, allow_inf_nan=False)
    trailing_start_pct: float = Field(default=10, gt=0, lt=100, allow_inf_nan=False)
    trailing_reduction_step_points: float = Field(default=10, gt=0, allow_inf_nan=False)
    trailing_reduction_pct: float = Field(default=1, gt=0, allow_inf_nan=False)
    minimum_trailing_pct: float = Field(default=5, gt=0, lt=100, allow_inf_nan=False)

    @model_validator(mode='after')
    def validate_protection(self):
        if self.profit_lock_pct >= self.profit_lock_trigger_pct:
            raise ValueError('profit_lock_pct must be below profit_lock_trigger_pct')
        if self.minimum_trailing_pct > self.trailing_start_pct:
            raise ValueError('minimum_trailing_pct must not exceed trailing_start_pct')
        return self


@dataclass(frozen=True)
class Protection:
    highest: Decimal
    stop: Decimal
    activated: bool
    trailing_pct: Decimal | None
    step: int


def progressive_stop(entry, highest, current, previous_stop, activated, settings):
    entry, highest, current, previous_stop = map(lambda v: Decimal(str(v)),
                                               (entry, highest, current, previous_stop))
    values = {name: Decimal(str(getattr(settings, name))) for name in ProgressiveSettings.model_fields}
    highest = max(entry, highest, current)
    reference = entry * (1 + values['profit_lock_trigger_pct'] / 100)
    initial = entry * (1 - values['initial_stop_loss_pct'] / 100)
    activated = activated or highest >= reference
    if not activated:
        return Protection(highest, max(initial, previous_stop), False, None, 0)
    step = max(0, int(((highest - reference) / values['trailing_reduction_step_points']).to_integral_value(rounding=ROUND_FLOOR)))
    pct = max(values['minimum_trailing_pct'], values['trailing_start_pct'] - step * values['trailing_reduction_pct'])
    locked = entry * (1 + values['profit_lock_pct'] / 100)
    trailing = highest * (1 - pct / 100)
    return Protection(highest, max(initial, previous_stop, locked, trailing), True, pct, step)
