from datetime import time
from typing import Dict, List, Optional, Union

from backend.app.core.enums import RiskStatus, SignalType
from backend.app.dto.trading_dto import (
    ExecutionResult,
    LevelContext,
    PositionState,
    StrategySignal,
    Tick,
)
from backend.app.market.agent import MarketAgent
from backend.app.risk.agent import RiskAgent
from backend.app.strategy.level_strategy import LevelStrategy
from backend.app.trading.paper import PaperTradingAgent


class TickWorkflow:
    def __init__(
        self,
        market_agent: Optional[MarketAgent] = None,
        strategy: Optional[LevelStrategy] = None,
        risk_agent: Optional[RiskAgent] = None,
        paper_agent: Optional[PaperTradingAgent] = None,
    ) -> None:
        self.market_agent = market_agent or MarketAgent()
        self.strategy = strategy or LevelStrategy()
        self.risk_agent = risk_agent or RiskAgent()
        self.paper_agent = paper_agent or PaperTradingAgent()
        self.previous_ticks: Dict[int, Tick] = {}
        self.positions: Dict[int, PositionState] = {}

    def handle_tick(
        self, tick: Tick, levels: LevelContext, square_off_time: Optional[time] = None
    ) -> List[Union[StrategySignal, ExecutionResult]]:
        previous_tick = self.previous_ticks.get(tick.instrument_id)
        market = self.market_agent.build_context(tick, previous_tick)
        position = self.positions.get(tick.instrument_id)
        signals = self.strategy.evaluate(market, levels, position, square_off_time)

        results: List[Union[StrategySignal, ExecutionResult]] = []
        for signal in signals:
            decision = self.risk_agent.validate(signal, self.positions.get(tick.instrument_id))
            if decision.status != RiskStatus.APPROVED:
                results.append(signal)
                continue

            if signal.signal_type in {
                SignalType.TARGET_CHECKPOINT_REACHED,
                SignalType.UPDATE_TRAILING_STOPLOSS,
            }:
                self.paper_agent.apply_state_signal(signal, self.positions.get(tick.instrument_id))
                results.append(signal)
                continue

            execution = self.paper_agent.execute(
                signal, self.positions.get(tick.instrument_id), levels.trading_day
            )
            if execution.position:
                self.positions[tick.instrument_id] = execution.position
            results.append(execution)

        self.previous_ticks[tick.instrument_id] = tick
        return results
