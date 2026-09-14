from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Protocol


@dataclass(frozen=True)
class OptionContract:
    instrument: str
    expiry: date
    strike: int
    option_type: str
    symbol: str
    lot_size: Optional[int] = None


class OptionInstrumentSource(Protocol):
    def strike_step(self, instrument: str) -> Optional[int]: ...

    def contracts(self, instrument: str) -> list[OptionContract]: ...


class SimulatedOptionInstrumentSource:
    """Synthetic contracts, not exchange symbols or an exchange expiry calendar."""

    def __init__(self, seed_date: date):
        self._steps = {"NIFTY": 50, "BANKNIFTY": 100}
        self._contracts = []
        for instrument, center in [("NIFTY", 25000), ("BANKNIFTY", 51000)]:
            step = self._steps[instrument]
            for days in [7, 14]:
                expiry = seed_date + timedelta(days=days)
                for strike in range(center - 10 * step, center + 11 * step, step):
                    for option_type in ["CE", "PE"]:
                        self._contracts.append(OptionContract(
                            instrument, expiry, strike, option_type,
                            f"SIM-{instrument}-{expiry.isoformat()}-{strike}-{option_type}",
                            10 if instrument == "NIFTY" else 20,
                        ))

    def strike_step(self, instrument: str) -> Optional[int]:
        return self._steps.get(instrument)

    def contracts(self, instrument: str) -> list[OptionContract]:
        return [contract for contract in self._contracts if contract.instrument == instrument]
