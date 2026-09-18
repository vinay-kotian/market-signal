from datetime import date, datetime
from typing import Literal, Optional

import json

from pydantic import BaseModel, Field, field_validator, ConfigDict
from app.settings import TradeSettings


ValidityStatus = Literal["VALID", "INVALID_STRATEGY_BUG", "INVALID_DATA_ISSUE",
                         "INVALID_EXECUTION_ISSUE", "MANUAL_REVIEW"]


class TradeClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    validity_status: ValidityStatus
    reason: str = Field(max_length=4000)
    exclude_from_strategy_metrics: bool


class TradeEntry(BaseModel):
    strategy_version: str = Field(default_factory=lambda: TradeSettings().strategy_version)
    validity_status: ValidityStatus = "VALID"
    validity_reason: Optional[str] = None
    exclude_from_strategy_metrics: bool = False
    settings_snapshot: dict

    @field_validator("settings_snapshot", mode="before")
    @classmethod
    def decode_snapshot(cls, value):
        return json.loads(value) if isinstance(value, str) else value

    signal_id: int
    option_selection_id: int
    instrument: str
    trigger_level: float
    direction: Literal["FROM_ABOVE", "FROM_BELOW"]
    option_symbol: str
    option_type: Literal["CE", "PE"]
    strike: int
    expiry: date
    lot_size: int
    number_of_lots: int
    quantity: int
    entry_price: float
    entry_time: datetime
    stop_loss_percentage: float
    initial_stop_loss: float
    highest_price: float
    current_stop_loss: float
    trailing_stop_percentage: float
    breakeven_protection_enabled: bool
    breakeven_activation_percent: float
    breakeven_lock_percent: float
    breakeven_activated: bool = False
    trade_mode: Literal["PAPER", "BACKTEST"] = "PAPER"
    status: Literal["OPEN"] = "OPEN"


class Trade(TradeEntry):
    trade_id: int
    status: Literal['OPEN', 'CLOSED'] = 'OPEN'
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[Literal['STOP_LOSS', 'MARKET_CLOSING_EXIT']] = None
    realised_pnl: Optional[float] = None
    realised_pnl_percentage: Optional[float] = None


class TradeEntryResult(BaseModel):
    option_selection_id: int
    trade_id: Optional[int]
    status: Literal["OPEN", "CLOSED", "FAILED"]
    failure_reason: Optional[str]
    timestamp: datetime
