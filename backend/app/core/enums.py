from enum import Enum


class LevelSetStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class LevelRole(str, Enum):
    STOPLOSS = "STOPLOSS"
    ENTRY = "ENTRY"
    CHECKPOINT = "CHECKPOINT"


class EntryApproachDirection(str, Enum):
    BELOW_TO_L1 = "BELOW_TO_L1"
    ABOVE_TO_L1 = "ABOVE_TO_L1"
    UNKNOWN_AT_LEVEL = "UNKNOWN_AT_LEVEL"


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    TARGET_CHECKPOINT_REACHED = "TARGET_CHECKPOINT_REACHED"
    UPDATE_TRAILING_STOPLOSS = "UPDATE_TRAILING_STOPLOSS"
    EOD_EXIT = "EOD_EXIT"


class RiskStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"

