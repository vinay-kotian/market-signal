from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel


class TradeEntry(BaseModel):
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
    trade_mode: Literal["PAPER"] = "PAPER"
    status: Literal["OPEN"] = "OPEN"


class Trade(TradeEntry):
    trade_id: int


class TradeEntryResult(BaseModel):
    option_selection_id: int
    trade_id: Optional[int]
    status: Literal["OPEN", "FAILED"]
    failure_reason: Optional[str]
    timestamp: datetime
