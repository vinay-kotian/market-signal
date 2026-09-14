from datetime import datetime, timedelta, timezone

from app.price_history import PriceHistory
from app.settings import SignalSettings


def test_history_is_bounded_by_age_count_and_instrument():
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    history = PriceHistory(15, max_samples=3)
    history.record("OLD", 100, now - timedelta(minutes=16))
    history.record("NIFTY", 99, now - timedelta(minutes=15))
    assert len(history.recent("NIFTY", now)) == 1
    for index in range(4):
        history.record("NIFTY", index, now)
    history.record("BANKNIFTY", 500, now)
    assert [s.price for s in history.recent("NIFTY", now)] == [1, 2, 3]
    assert history.recent("OLD", now) == []
    assert [s.price for s in history.recent("BANKNIFTY", now)] == [500]


def test_settings_from_environment(monkeypatch):
    monkeypatch.setenv("LOOKBACK_MINUTES", "5")
    monkeypatch.setenv("MINIMUM_APPROACH_DISTANCE_ENABLED", "true")
    monkeypatch.setenv("MINIMUM_APPROACH_DISTANCE_POINTS", "100")
    settings = SignalSettings.from_environment()
    assert settings.lookback_minutes == 5
    assert settings.minimum_approach_distance_enabled is True
    assert settings.minimum_approach_distance_points == 100
