from datetime import date, datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.core.enums import LevelSetStatus, OrderSide, PositionStatus, SignalType
from backend.app.dto.trading_dto import (
    ExecutionResult,
    LevelContext,
    LevelDTO,
    PositionState,
    StrategySignal,
    Tick,
)
from backend.app.models.tables import (
    AuditLog,
    DailyLevelSet,
    Instrument,
    Order,
    Position,
)


def get_instrument_by_token(db: Session, instrument_token: int) -> Optional[Instrument]:
    return db.scalar(select(Instrument).where(Instrument.instrument_token == instrument_token))


def get_active_instrument_token_map(db: Session, trading_day: date) -> Dict[int, int]:
    rows = db.execute(
        select(Instrument.instrument_token, Instrument.id)
        .join(DailyLevelSet, DailyLevelSet.instrument_id == Instrument.id)
        .where(
            DailyLevelSet.trading_day == trading_day,
            DailyLevelSet.status == LevelSetStatus.ACTIVE.value,
        )
    ).all()
    return {int(token): int(instrument_id) for token, instrument_id in rows}


def validate_active_level_sets(db: Session, trading_day: date) -> List[str]:
    errors: List[str] = []
    level_sets = db.scalars(
        select(DailyLevelSet)
        .options(selectinload(DailyLevelSet.levels), selectinload(DailyLevelSet.instrument))
        .where(
            DailyLevelSet.trading_day == trading_day,
            DailyLevelSet.status == LevelSetStatus.ACTIVE.value,
        )
    ).all()
    for level_set in level_sets:
        sorted_levels = sorted(level_set.levels, key=lambda item: item.sort_order)
        label = f"{level_set.instrument.symbol} {level_set.trading_day}"
        if len(sorted_levels) < 2:
            errors.append(f"{label}: at least L0 and L1 are required")
            continue
        if sorted_levels[0].level_name != "L0":
            errors.append(f"{label}: first level must be L0")
        if sorted_levels[1].level_name != "L1":
            errors.append(f"{label}: second level must be L1")
        if sorted_levels[0].price >= sorted_levels[1].price:
            errors.append(f"{label}: L0 must be below L1 for option buying strategy")
        for previous, current in zip(sorted_levels, sorted_levels[1:]):
            if current.price <= previous.price:
                errors.append(f"{label}: levels must be strictly increasing by price")
                break
    return errors


def get_active_level_context(
    db: Session, instrument_id: int, trading_day: date
) -> Optional[LevelContext]:
    level_set = db.scalar(
        select(DailyLevelSet)
        .options(selectinload(DailyLevelSet.levels))
        .where(
            DailyLevelSet.instrument_id == instrument_id,
            DailyLevelSet.trading_day == trading_day,
            DailyLevelSet.status == LevelSetStatus.ACTIVE.value,
        )
    )
    if not level_set:
        return None
    return LevelContext(
        instrument_id=instrument_id,
        trading_day=trading_day,
        levels=tuple(
            LevelDTO(
                name=level.level_name,
                price=level.price,
                sort_order=level.sort_order,
                role=level.role,
            )
            for level in sorted(level_set.levels, key=lambda item: item.sort_order)
        ),
    )


def get_open_position_state(
    db: Session, instrument_id: int, trading_day: date
) -> Optional[PositionState]:
    position = db.scalar(
        select(Position).where(
            Position.instrument_id == instrument_id,
            Position.trading_day == trading_day,
            Position.status == PositionStatus.OPEN.value,
        )
    )
    if not position:
        return None
    return PositionState(
        instrument_id=position.instrument_id,
        trading_day=position.trading_day,
        quantity=position.quantity,
        entry_price=position.entry_price,
        stoploss_price=position.stoploss_price,
        trailing_stoploss_price=position.trailing_stoploss_price,
        high_water_mark=position.high_water_mark,
        is_open=True,
    )


def list_open_positions(db: Session, trading_day: date) -> List[Position]:
    return list(
        db.scalars(
            select(Position).where(
                Position.trading_day == trading_day,
                Position.status == PositionStatus.OPEN.value,
            )
        ).all()
    )


def has_open_position(db: Session, instrument_id: int, trading_day: date) -> bool:
    return get_open_position_state(db, instrument_id, trading_day) is not None


def persist_workflow_results(
    db: Session,
    instrument_id: int,
    trading_day: date,
    results: List[object],
) -> None:
    for result in results:
        if isinstance(result, ExecutionResult):
            _persist_execution(db, trading_day, result)
            continue
        if isinstance(result, StrategySignal):
            _persist_signal(db, instrument_id, trading_day, result)
    db.commit()


def _persist_execution(db: Session, trading_day: date, result: ExecutionResult) -> None:
    action = result.action
    position_id = None
    if result.success and result.position and action.side == OrderSide.BUY:
        existing_position = _get_open_position_model(db, action.instrument_id, trading_day)
        if existing_position:
            db.add(
                AuditLog(
                    event_type="DUPLICATE_POSITION_BLOCKED",
                    instrument_id=action.instrument_id,
                    message="Skipped duplicate open paper position",
                )
            )
            return
        position = Position(
            instrument_id=action.instrument_id,
            trading_day=trading_day,
            quantity=result.position.quantity,
            entry_price=result.position.entry_price,
            stoploss_price=result.position.stoploss_price,
            trailing_stoploss_price=result.position.trailing_stoploss_price,
            high_water_mark=result.position.high_water_mark,
            status=PositionStatus.OPEN.value,
        )
        db.add(position)
        db.flush()
        position_id = position.id

    if result.success and result.position and action.side == OrderSide.SELL:
        position = _get_open_position_model(db, action.instrument_id, trading_day)
        if position:
            position.status = PositionStatus.CLOSED.value
            position.closed_at = datetime.utcnow()
            position.exit_price = result.position.exit_price
            position.realized_pnl = result.position.realized_pnl
            position_id = position.id

    db.add(
        Order(
            instrument_id=action.instrument_id,
            position_id=position_id,
            side=action.side.value,
            quantity=action.quantity,
            price=action.price,
            reason=action.reason,
        )
    )
    db.add(
        AuditLog(
            event_type="PAPER_EXECUTION" if result.success else "PAPER_EXECUTION_FAILED",
            instrument_id=action.instrument_id,
            message=f"{action.side.value} {action.quantity} at {action.price}: {result.message}",
        )
    )


def _persist_signal(
    db: Session, instrument_id: int, trading_day: date, signal: StrategySignal
) -> None:
    if signal.signal_type in {
        SignalType.TARGET_CHECKPOINT_REACHED,
        SignalType.UPDATE_TRAILING_STOPLOSS,
    }:
        position = _get_open_position_model(db, instrument_id, trading_day)
        if position:
            if signal.trailing_stoploss_price is not None:
                position.trailing_stoploss_price = max(
                    position.trailing_stoploss_price, signal.trailing_stoploss_price
                )
            position.high_water_mark = max(position.high_water_mark, signal.price)

    db.add(
        AuditLog(
            event_type=signal.signal_type.value,
            instrument_id=instrument_id,
            message=f"{signal.reason} at {signal.price}",
        )
    )


def _get_open_position_model(
    db: Session, instrument_id: int, trading_day: date
) -> Optional[Position]:
    return db.scalar(
        select(Position).where(
            Position.instrument_id == instrument_id,
            Position.trading_day == trading_day,
            Position.status == PositionStatus.OPEN.value,
        )
    )
