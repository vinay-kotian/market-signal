from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel


class OptionSelection(BaseModel):
    instrument: str
    trigger_price: float
    direction: Literal["FROM_ABOVE", "FROM_BELOW"]
    option_type: Literal["CE", "PE"]
    itm_depth: int
    expiry: Optional[date] = None
    atm_strike: Optional[int] = None
    itm_strike: Optional[int] = None
    option_symbol: Optional[str] = None
    status: Literal["SELECTED", "FAILED"]
    failure_reason: Optional[Literal[
        "UNSUPPORTED_INSTRUMENT", "NO_UNEXPIRED_CONTRACT", "MISSING_OPTION_CONTRACT"
    ]] = None


class StoredOptionSelection(OptionSelection):
    id: int
    signal_id: int
    timestamp: datetime
