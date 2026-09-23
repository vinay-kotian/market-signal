import asyncio
from collections import deque
from datetime import datetime, timezone

from app.trading_date import trading_date
from app.index_settings import IndexSettingsRepository
from app.events import LevelTriggered
from app.level_repository import LevelRepository
from app.market_data import PriceTick
from app.signal_engine import SignalEngine
from app.price_history import PriceHistory
from app.signal_repository import SignalRepository
from app.database import connect
from app.option_instruments import SimulatedOptionInstrumentSource
from app.option_repository import OptionSelectionRepository
from app.option_selector import OptionSelector
from app.settings import OptionSettings, TradeSettings


def utc_now():
    return datetime.now(timezone.utc)


class LevelMonitor:
    def __init__(self, repository: LevelRepository, signal_engine=None, clock=utc_now,
                 signal_repository=None, option_selector=None, option_settings=None,
                 option_repository=None, paper_executor=None):
        self._repository = repository
        self.signal_engine = signal_engine or SignalEngine()
        self._signal_repository = signal_repository or SignalRepository(repository.database_path)
        self._history = PriceHistory(self.signal_engine.settings.lookback_minutes)
        self._clock = clock
        self._option_selector = option_selector or OptionSelector(
            SimulatedOptionInstrumentSource(utc_now().date())
        )
        self._option_settings = option_settings or OptionSettings()
        self._option_repository = option_repository or OptionSelectionRepository(repository.database_path)
        self._paper_executor = paper_executor
        self._previous_prices: dict[str, float] = {}
        self._events: deque[LevelTriggered] = deque(maxlen=100)
        self._next_event_id = 1
        self._lock = asyncio.Lock()
        self.on_expired = None
        self.on_armed = None

    def _expire(self, timestamp):
        changed = self._repository.expire_before(timestamp)
        if changed and self.on_expired:
            self.on_expired(changed)
        return changed

    async def reconcile(self):
        async with self._lock:
            return self._expire(self._clock())

    async def run_expiry_checks(self):
        while True:
            try:
                await self.reconcile()
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Level expiry check failed; retrying')
            await asyncio.sleep(1)

    async def on_tick(self, tick: PriceTick) -> None:
        # Keep reading the baseline, evaluating levels, and updating state together.
        async with self._lock:
            previous = self._previous_prices.get(tick.instrument)
            current = tick.price
            timestamp = self._clock()
            self._repository.record_price(tick.instrument, current, timestamp)
            self._expire(timestamp)
            levels = self._repository.list_enabled(tick.instrument, timestamp)
            active_levels = []
            distance = (self._paper_executor.settings.level_rearm_distance_points
                        if self._paper_executor else TradeSettings().level_rearm_distance_points)
            initial_distance = IndexSettingsRepository(self._repository.database_path).distance(tick.instrument)
            for level in levels:
                if level.status == 'PENDING_ARM':
                    if self._repository.initial_arm(level, current, initial_distance, timestamp) and self.on_armed:
                        self.on_armed([self._repository.get(level.id)])
                    # Initial arming is a state transition only, never an entry tick.
                elif level.status == 'DISARMED':
                    self._repository.rearm(level, current, distance, timestamp)
                    # Re-arming is not a trigger: require a later return/crossing.
                elif level.status == 'ACTIVE':
                    active_levels.append(level)
            if previous == current:
                self._history.record(tick.instrument, current, timestamp)
                return

            history = self._history.recent(tick.instrument, timestamp)
            triggers = []
            signals = []
            for level in active_levels:
                touched = current == level.price
                crossed = previous is not None and (
                    previous < level.price <= current
                    or previous > level.price >= current
                )
                # One event even when both the touch and crossing conditions match.
                if touched or crossed:
                    trigger = LevelTriggered(
                        id=self._next_event_id + len(triggers),
                        level_id=level.id,
                        instrument=tick.instrument,
                        level_price=level.price,
                        previous_price=previous,
                        current_price=current,
                        triggered_at=timestamp,
                    )
                    signals.append(self.signal_engine.analyze(trigger, history))
                    triggers.append(trigger)

            selections = {}
            for index, signal in enumerate(signals):
                if signal.valid:
                    selection = self._option_selector.select(
                        signal.instrument, signal.trigger_price, signal.direction,
                        self._option_settings.itm_depth, signal.timestamp.date())
                    selections[index] = selection
                    if self._paper_executor is not None:
                        await self._paper_executor.prepare(selection)

            # A quote fetch may straddle midnight. Do not persist stale-day signals.
            if selections and self._paper_executor is not None:
                execution_time = self._clock()
                if trading_date(execution_time) != trading_date(timestamp):
                    self._expire(execution_time)
                    return

            # A failed write leaves the transition retryable, without partial results.
            if signals:
                with connect(self._repository.database_path) as connection:
                    saved = self._signal_repository.save_many(signals, connection=connection)
                    for index, signal in enumerate(saved):
                        if signal.valid:
                            selection = selections[index]
                            stored_selection = self._option_repository.save(
                                signal.id, selection, signal.timestamp, connection=connection,
                            )
                            if self._paper_executor is not None:
                                self._paper_executor.execute(signal, stored_selection, self._clock(),
                                                             connection=connection)
            self._events.extend(triggers)
            self._next_event_id += len(triggers)
            self._history.record(tick.instrument, current, timestamp)
            self._previous_prices[tick.instrument] = current

    def recent_events(self) -> list[LevelTriggered]:
        return list(reversed(self._events))
