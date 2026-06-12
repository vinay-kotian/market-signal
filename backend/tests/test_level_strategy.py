from datetime import date, datetime, timedelta

from backend.app.core.enums import EntryApproachDirection, SignalType
from backend.app.dto.trading_dto import LevelContext, LevelDTO, PositionState, Tick
from backend.app.market.agent import MarketAgent
from backend.app.strategy.level_strategy import LevelStrategy
from backend.app.workflows.tick_workflow import TickWorkflow


def levels() -> LevelContext:
    return LevelContext(
        instrument_id=1,
        trading_day=date(2026, 5, 17),
        levels=(
            LevelDTO(name="L0", price=100, sort_order=0, role="STOPLOSS"),
            LevelDTO(name="L1", price=110, sort_order=1, role="ENTRY"),
            LevelDTO(name="L2", price=120, sort_order=2, role="CHECKPOINT"),
            LevelDTO(name="L3", price=130, sort_order=3, role="CHECKPOINT"),
        ),
    )


def tick(price: float, seconds: int = 0) -> Tick:
    return Tick(
        instrument_token=1001,
        instrument_id=1,
        symbol="NIFTY_TEST_CE",
        last_price=price,
        timestamp=datetime(2026, 5, 17, 9, 15) + timedelta(seconds=seconds),
    )


def test_l1_reached_from_below_emits_buy_with_direction() -> None:
    strategy = LevelStrategy()
    market = MarketAgent()
    context = market.build_context(tick(110, 1), tick(108, 0))

    signals = strategy.evaluate(context, levels(), position=None)

    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.BUY
    assert signals[0].entry_approach_direction == EntryApproachDirection.BELOW_TO_L1
    assert signals[0].stoploss_price == 100


def test_l1_reached_from_above_emits_buy_with_direction() -> None:
    strategy = LevelStrategy()
    market = MarketAgent()
    context = market.build_context(tick(110, 1), tick(115, 0))

    signals = strategy.evaluate(context, levels(), position=None)

    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.BUY
    assert signals[0].entry_approach_direction == EntryApproachDirection.ABOVE_TO_L1
    assert signals[0].stoploss_price == 100


def test_trailing_stoploss_does_not_activate_before_entry() -> None:
    strategy = LevelStrategy()
    market = MarketAgent()
    context = market.build_context(tick(108, 1), tick(106, 0))

    signals = strategy.evaluate(context, levels(), position=None)

    assert signals == []


def test_trailing_stoploss_stays_at_l0_until_l2_is_reached() -> None:
    strategy = LevelStrategy(trailing_gap=5)
    market = MarketAgent()
    position = PositionState(
        instrument_id=1,
        trading_day=date(2026, 5, 17),
        quantity=1,
        entry_price=110,
        stoploss_price=100,
        trailing_stoploss_price=100,
        high_water_mark=110,
    )
    context = market.build_context(tick(118, 1), tick(116, 0))

    signals = strategy.evaluate(context, levels(), position=position)

    assert signals == []


def test_upper_checkpoint_tightens_trailing_without_selling() -> None:
    strategy = LevelStrategy(trailing_gap=5)
    market = MarketAgent()
    position = PositionState(
        instrument_id=1,
        trading_day=date(2026, 5, 17),
        quantity=1,
        entry_price=110,
        stoploss_price=100,
        trailing_stoploss_price=100,
        high_water_mark=110,
    )
    context = market.build_context(tick(120, 1), tick(118, 0))

    signals = strategy.evaluate(context, levels(), position=position)

    assert [signal.signal_type for signal in signals] == [
        SignalType.TARGET_CHECKPOINT_REACHED,
        SignalType.UPDATE_TRAILING_STOPLOSS,
    ]
    assert signals[0].checkpoint_name == "L2"
    assert signals[0].trailing_stoploss_price == 115
    assert all(signal.signal_type != SignalType.SELL for signal in signals)


def test_tick_workflow_keeps_state_per_instrument() -> None:
    workflow = TickWorkflow(strategy=LevelStrategy(trailing_gap=5))

    workflow.handle_tick(tick(108, 0), levels())
    entry_results = workflow.handle_tick(tick(110, 1), levels())
    checkpoint_results = workflow.handle_tick(tick(120, 2), levels())

    assert len(entry_results) == 1
    assert workflow.positions[1].entry_price == 110
    assert workflow.positions[1].stoploss_price == 100
    assert workflow.positions[1].trailing_stoploss_price == 115
    assert "L2" in workflow.positions[1].reached_checkpoints
    assert any(
        getattr(result, "signal_type", None) == SignalType.TARGET_CHECKPOINT_REACHED
        for result in checkpoint_results
    )
