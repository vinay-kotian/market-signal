from abc import ABC, abstractmethod
from typing import List

from backend.app.dto.trading_dto import Tick, TradeAction


class BrokerClient(ABC):
    @abstractmethod
    def place_order(self, action: TradeAction) -> str:
        raise NotImplementedError


class MarketDataClient(ABC):
    @abstractmethod
    def subscribe(self, instrument_tokens: List[int]) -> None:
        raise NotImplementedError

    @abstractmethod
    def normalize_tick(self, raw_tick: dict) -> Tick:
        raise NotImplementedError
