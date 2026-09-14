from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class PriceSample:
    price: float
    timestamp: datetime


class PriceHistory:
    """Receive-time history, bounded by both age and sample count."""

    def __init__(self, lookback_minutes: float, max_samples: int = 2000):
        self.window = timedelta(minutes=lookback_minutes)
        self.max_samples = max_samples
        self._samples: dict[str, deque[PriceSample]] = {}

    def record(self, instrument: str, price: float, timestamp: datetime) -> None:
        cutoff = timestamp - self.window
        # Also remove inactive instruments so they do not retain expired history.
        for symbol in list(self._samples):
            samples = self._samples[symbol]
            while samples and samples[0].timestamp < cutoff:
                samples.popleft()
            if not samples:
                del self._samples[symbol]
        self._samples.setdefault(instrument, deque(maxlen=self.max_samples)).append(
            PriceSample(price, timestamp)
        )

    def recent(self, instrument: str, timestamp: datetime) -> list[PriceSample]:
        cutoff = timestamp - self.window
        return [
            sample for sample in self._samples.get(instrument, ())
            if cutoff <= sample.timestamp <= timestamp
        ]
