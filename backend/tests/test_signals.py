import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import initialize_database
from app.level_monitor import LevelMonitor
from app.level_repository import LevelRepository
from app.main import create_app
from app.market_data import PriceTick
from app.models import LevelInput
from app.settings import SignalSettings
from app.signal_engine import SignalEngine
from app.signal_repository import SignalRepository


def add_level(client, price=25000, instrument="NIFTY", enabled=True):
    return client.post("/levels", json={
        "instrument": instrument, "price": price, "enabled": enabled,
    }).json()


def ticks(client, prices, instrument="NIFTY"):
    for price in prices:
        assert client.post("/simulation/tick", json={
            "instrument": instrument, "price": price,
        }).status_code == 200
    response = client.get("/signals")
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("prices,direction,distance", [
    ([25100, 25060, 25020, 25000], "FROM_ABOVE", 100),
    ([24900, 24950, 24980, 25000], "FROM_BELOW", 100),
    ([24900, 24980, 25050], "FROM_BELOW", 100),
    ([25100, 25020, 24950], "FROM_ABOVE", 100),
    # A pullback on the same side must not shrink the approach to the last tick.
    ([24900, 24980, 24940, 25000], "FROM_BELOW", 100),
])
def test_approach_uses_history(client, prices, direction, distance):
    level = add_level(client)
    signal, = ticks(client, prices)
    assert signal["direction"] == direction
    assert signal["approach_distance"] == distance
    assert signal["valid"] is True
    assert signal["rejection_reason"] is None
    assert signal["instrument"] == "NIFTY"
    assert signal["level"] == 25000
    assert signal["level_id"] == level["id"]
    assert signal["trigger_price"] == prices[-1]
    trigger, = client.get("/simulation/events").json()
    assert signal["trigger_id"] == trigger["id"]
    assert signal["timestamp"] == trigger["triggered_at"]


@pytest.mark.parametrize("enabled,minimum,valid", [
    (True, 99, True), (True, 100, True), (True, 101, False), (False, 1000, True),
])
def test_minimum_distance(tmp_path, enabled, minimum, valid):
    settings = SignalSettings(minimum_approach_distance_enabled=enabled,
                              minimum_approach_distance_points=minimum)
    with TestClient(create_app(tmp_path / "signals.sqlite3", settings)) as client:
        add_level(client)
        signal, = ticks(client, [24900, 24990, 25000])
        assert signal["valid"] is valid
        assert signal["approach_distance"] == 100
        assert signal["rejection_reason"] == (None if valid else "MINIMUM_DISTANCE_NOT_MET")


def test_multiple_levels_and_instruments(client):
    add_level(client, price=25000)
    add_level(client, price=25100)
    add_level(client, price=25200, enabled=False)
    add_level(client, price=25000, instrument="BANKNIFTY")
    ticks(client, [1000], instrument="BANKNIFTY")
    signals = ticks(client, [24900, 24990, 25250])
    assert {(s["level"], s["approach_distance"]) for s in signals} == {(25000, 100), (25100, 200)}
    assert all(s["instrument"] == "NIFTY" for s in signals)


def test_insufficient_history(client):
    add_level(client)
    signal, = ticks(client, [25000])
    assert signal["valid"] is False
    assert signal["direction"] is None
    assert signal["approach_distance"] is None
    assert signal["rejection_reason"] == "INSUFFICIENT_PRICE_HISTORY"


def test_latest_approach_stops_at_opposite_side(client):
    add_level(client)
    signals = ticks(client, [24900, 25010, 25030, 24990, 25000])
    assert len(signals) == 3
    assert signals[0]["direction"] == "FROM_BELOW"
    assert signals[0]["approach_distance"] == 10
    assert signals[1]["direction"] == "FROM_ABOVE"
    assert signals[1]["approach_distance"] == 30


def test_previous_touch_resets_segment_and_duplicate_ticks_do_not_signal(client):
    add_level(client)
    signals = ticks(client, [24900, 25000, 25000, 24990, 25000, 25000])
    assert len(signals) == 2
    assert signals[0]["approach_distance"] == 10


@pytest.mark.parametrize("gap,expected_distance", [(15, 100), (16, None)])
def test_lookback_boundary_and_expired_previous_price(tmp_path, gap, expected_distance):
    path = tmp_path / "timed.sqlite3"
    initialize_database(path)
    repository = LevelRepository(path)
    repository.create(LevelInput(instrument="NIFTY", price=25000, enabled=True))
    engine = SignalEngine()
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)

    async def scenario():
        monitor = LevelMonitor(repository, engine, clock=lambda: now)
        await monitor.on_tick(PriceTick(instrument="NIFTY", price=24900))
        monitor._clock = lambda: now + timedelta(minutes=gap)
        await monitor.on_tick(PriceTick(instrument="NIFTY", price=25000))

    asyncio.run(scenario())
    signal, = SignalRepository(path).recent()
    assert signal.approach_distance == expected_distance
    assert signal.valid is (expected_distance is not None)


def test_expired_extreme_is_excluded(tmp_path):
    path = tmp_path / "extreme.sqlite3"
    initialize_database(path)
    repository = LevelRepository(path)
    repository.create(LevelInput(instrument="NIFTY", price=25000, enabled=True))
    engine = SignalEngine(SignalSettings(lookback_minutes=1))
    start = datetime(2026, 9, 14, tzinfo=timezone.utc)
    times = iter([start, start + timedelta(seconds=61), start + timedelta(seconds=62)])

    async def scenario():
        monitor = LevelMonitor(repository, engine, clock=lambda: next(times))
        for price in [24000, 24990, 25000]:
            await monitor.on_tick(PriceTick(instrument="NIFTY", price=price))

    asyncio.run(scenario())
    assert SignalRepository(path).recent()[0].approach_distance == 10


def test_signals_persist_and_recent_limit_does_not_delete_history(tmp_path):
    path = tmp_path / "restart.sqlite3"
    with TestClient(create_app(path)) as client:
        assert client.get("/signals").json() == []
        add_level(client)
        signals = ticks(client, [24990] + [25010 if i % 2 == 0 else 24990 for i in range(105)])
        assert len(signals) == 100
        assert [s["id"] for s in signals] == list(range(105, 5, -1))
    with TestClient(create_app(path)) as client:
        assert client.get("/signals").json() == signals
        assert len(SignalRepository(path).recent(limit=200)) == 105
        new_signals = ticks(client, [25000])
        assert new_signals[0]["id"] == 106
        assert new_signals[0]["rejection_reason"] == "INSUFFICIENT_PRICE_HISTORY"
        assert new_signals[1] == signals[0]
