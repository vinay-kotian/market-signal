from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.option_instruments import OptionInstrumentSource
from app.option_models import OptionSelection


class OptionSelector:
    def __init__(self, source: OptionInstrumentSource):
        self.source = source

    def select(self, instrument: str, trigger_price: float, direction: str,
               itm_depth: int, as_of: date) -> OptionSelection:
        if direction not in ("FROM_ABOVE", "FROM_BELOW"):
            raise ValueError("Unknown signal direction")
        if isinstance(itm_depth, bool) or not isinstance(itm_depth, int) or itm_depth < 1:
            raise ValueError("ITM depth must be a positive integer")
        price = Decimal(str(trigger_price))
        if not price.is_finite():
            raise ValueError("Trigger price must be finite")
        option_type = "CE" if direction == "FROM_ABOVE" else "PE"
        result = dict(instrument=instrument, trigger_price=trigger_price,
                      direction=direction, option_type=option_type, itm_depth=itm_depth)
        step = self.source.strike_step(instrument)
        if step is None:
            return OptionSelection(**result, status="FAILED", failure_reason="UNSUPPORTED_INSTRUMENT")
        atm = int((price / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * step
        strike = atm - itm_depth * step if option_type == "CE" else atm + itm_depth * step
        result.update(atm_strike=atm, itm_strike=strike)
        contracts = [c for c in self.source.contracts(instrument) if c.expiry >= as_of]
        if not contracts:
            return OptionSelection(**result, status="FAILED", failure_reason="NO_UNEXPIRED_CONTRACT")
        expiry = min(c.expiry for c in contracts)
        result.update(expiry=expiry)
        contract = next((c for c in contracts if c.expiry == expiry
                         and c.strike == strike and c.option_type == option_type), None)
        if contract is None:
            return OptionSelection(**result, status="FAILED", failure_reason="MISSING_OPTION_CONTRACT")
        return OptionSelection(**result, status="SELECTED", option_symbol=contract.symbol)
