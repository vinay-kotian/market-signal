from typing import Optional

from app.events import LevelTriggered
from app.price_history import PriceSample
from app.settings import SignalSettings
from app.signal_models import SignalAnalysis


class SignalEngine:
    def __init__(self, settings: Optional[SignalSettings] = None):
        self.settings = settings or SignalSettings()

    def analyze(self, trigger: LevelTriggered, samples: list[PriceSample]) -> SignalAnalysis:
        # Samples contain only prior prices inside the configured lookback window.
        approach = []
        side = None
        for sample in reversed(samples):
            if sample.price == trigger.level_price:
                break
            sample_side = "FROM_ABOVE" if sample.price > trigger.level_price else "FROM_BELOW"
            if side is not None and sample_side != side:
                break
            side = sample_side
            approach.append(sample.price)

        distance = None
        reason = None
        if not approach:
            reason = "INSUFFICIENT_PRICE_HISTORY"
        else:
            distance = (
                max(approach) - trigger.level_price if side == "FROM_ABOVE"
                else trigger.level_price - min(approach)
            )
            if (self.settings.minimum_approach_distance_enabled
                    and distance < self.settings.minimum_approach_distance_points):
                reason = "MINIMUM_DISTANCE_NOT_MET"

        return SignalAnalysis(
            trigger_id=trigger.id,
            level_id=trigger.level_id,
            instrument=trigger.instrument,
            level=trigger.level_price,
            trigger_price=trigger.current_price,
            direction=side,
            approach_distance=distance,
            valid=reason is None,
            rejection_reason=reason,
            timestamp=trigger.triggered_at,
        )
