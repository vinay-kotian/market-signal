from typing import Dict, Optional

from backend.app.dto.trading_dto import Tick


class TickCache:
    def __init__(self) -> None:
        self._latest_ticks: Dict[int, Tick] = {}

    def get_previous(self, instrument_id: int) -> Optional[Tick]:
        return self._latest_ticks.get(instrument_id)

    def update(self, tick: Tick) -> None:
        self._latest_ticks[tick.instrument_id] = tick

    def latest(self) -> Dict[int, Tick]:
        return dict(self._latest_ticks)


tick_cache = TickCache()
