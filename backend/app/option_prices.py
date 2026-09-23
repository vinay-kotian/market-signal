from typing import Optional, Protocol

from app.option_instruments import OptionInstrumentSource


class OptionPriceSource(Protocol):
    def current_price(self, symbol: str) -> Optional[float]: ...


class SimulatedOptionPrices:
    """Latest manually supplied quotes; never infer premiums from underlying prices."""

    def __init__(self, prices=None):
        self._prices = dict(prices or {})

    @classmethod
    def seeded(cls, instruments: OptionInstrumentSource):
        return cls({contract.symbol: premium
                    for symbol, premium in [("NIFTY", 100.0), ("BANKNIFTY", 200.0), ("SENSEX", 200.0)]
                    for contract in instruments.contracts(symbol)})

    def current_price(self, symbol: str) -> Optional[float]:
        return self._prices.get(symbol)

    def set_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price
