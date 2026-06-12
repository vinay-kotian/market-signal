from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Set, Tuple

from backend.app.core.enums import EntryApproachDirection, OrderSide, RiskStatus, SignalType


@dataclass(frozen=True)
class Tick:
    instrument_token: int
    instrument_id: int
    symbol: str
    last_price: float
    timestamp: datetime
    volume: Optional[int] = None


@dataclass(frozen=True)
class MarketContext:
    tick: Tick
    previous_price: Optional[float]
    direction: str
    velocity_per_second: float


@dataclass(frozen=True)
class LevelDTO:
    name: str
    price: float
    sort_order: int
    role: str


@dataclass(frozen=True)
class LevelContext:
    instrument_id: int
    trading_day: date
    levels: Tuple[LevelDTO, ...]

    @property
    def l0(self) -> LevelDTO:
        return self.levels[0]

    @property
    def l1(self) -> LevelDTO:
        return self.levels[1]

    @property
    def upper_levels(self) -> Tuple[LevelDTO, ...]:
        return self.levels[2:]


@dataclass
class PositionState:
    instrument_id: int
    trading_day: date
    quantity: int
    entry_price: float
    stoploss_price: float
    trailing_stoploss_price: float
    high_water_mark: float
    reached_checkpoints: Set[str] = field(default_factory=set)
    is_open: bool = True
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None


@dataclass(frozen=True)
class StrategySignal:
    signal_type: SignalType
    instrument_id: int
    price: float
    reason: str
    quantity: int = 1
    entry_approach_direction: Optional[EntryApproachDirection] = None
    entry_velocity: Optional[float] = None
    stoploss_price: Optional[float] = None
    trailing_stoploss_price: Optional[float] = None
    checkpoint_name: Optional[str] = None


@dataclass(frozen=True)
class RiskDecision:
    status: RiskStatus
    signal: StrategySignal
    reason: str


@dataclass(frozen=True)
class TradeAction:
    side: OrderSide
    instrument_id: int
    quantity: int
    price: float
    reason: str
    stoploss_price: Optional[float] = None


@dataclass(frozen=True)
class ExecutionResult:
    action: TradeAction
    success: bool
    message: str
    position: Optional[PositionState] = None
