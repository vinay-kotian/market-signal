from active_level_fixture import create_active_level, create_active_record
from app.option_prices import SimulatedOptionPrices
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.database import initialize_database
from app.level_monitor import LevelMonitor
from app.level_repository import LevelRepository
from app.main import create_app
from app.market_data import MarketDataProvider, PriceTick, SimulatedMarketDataProvider
from app.models import LevelInput


def add_level(client, price=25000, instrument="NIFTY", enabled=True):
    response = create_active_level(client, json={"instrument": instrument, "price": price, "enabled": enabled}
    )
    assert response.status_code == 201
    return response.json()


def publish(client, price, instrument="NIFTY"):
    response = client.post(
        "/simulation/tick", json={"instrument": instrument, "price": price}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "processed"}


def events(client):
    response = client.get("/simulation/events")
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize(
    "previous,current", [(24990, 25005), (25010, 24995), (24990, 25000), (25010, 25000)]
)
def test_crossing_and_exact_touch(client, previous, current):
    level = add_level(client)
    publish(client, previous)
    publish(client, current)
    result = events(client)
    assert len(result) == 1
    event = result[0]
    assert event["event_type"] == "LEVEL_TRIGGERED"
    assert event["level_id"] == level["id"]
    assert event["instrument"] == "NIFTY"
    assert event["level_price"] == 25000
    assert event["previous_price"] == previous
    assert event["current_price"] == current
    assert event["triggered_at"]


@pytest.mark.parametrize("prices", [(24980, 24990), (25020, 25010)])
def test_no_crossing(client, prices):
    add_level(client)
    for price in prices:
        publish(client, price)
    assert events(client) == []


def test_disabled_level(client):
    add_level(client, enabled=False)
    for price in [24990, 25005, 25000]:
        publish(client, price)
    assert events(client) == []


def test_multiple_levels_and_instrument_filter(client):
    first = add_level(client, price=25000)
    second = add_level(client, price=25010)
    add_level(client, price=25020)
    add_level(client, price=25005, enabled=False)
    add_level(client, price=25005, instrument="BANKNIFTY")
    publish(client, 24990)
    publish(client, 25015)
    result = events(client)
    assert [event["level_id"] for event in result] == [second["id"], first["id"]]
    assert len({event["id"] for event in result}) == 2


def test_previous_price_initialization_and_instrument_isolation(client):
    add_level(client)
    add_level(client, instrument="BANKNIFTY")
    publish(client, 24990)
    publish(client, 25010, instrument="BANKNIFTY")
    assert events(client) == []
    publish(client, 25005)
    assert len(events(client)) == 1
    assert events(client)[0]["previous_price"] == 24990


def test_initial_exact_touch(client):
    add_level(client)
    publish(client, 25000)
    assert len(events(client)) == 1
    assert events(client)[0]["previous_price"] is None


def test_duplicates_are_suppressed_but_later_recross_triggers(client):
    # Test signal/trigger semantics without a successful entry disarming the level.
    client.app.state.paper_executor.prices = SimulatedOptionPrices()
    add_level(client)
    for price in [24990, 25000, 25000, 25000, 25005]:
        publish(client, price)
    assert len(events(client)) == 1
    publish(client, 24990)
    publish(client, 25000)
    assert len(events(client)) == 3


def test_levels_are_reloaded_and_prices_tracked_without_levels(client):
    publish(client, 24990)
    level = add_level(client, enabled=False)
    client.put(
        f"/levels/{level['id']}",
        json={"instrument": "NIFTY", "price": 25000, "enabled": True},
    )
    publish(client, 25005)  # Only 15 points from the edit reference: still pending.
    assert events(client) == []
    publish(client, 25020)  # Exactly 30 points arms without triggering.
    assert events(client) == []
    publish(client, 25000)
    assert len(events(client)) == 1
    client.delete(f"/levels/{level['id']}")
    publish(client, 24990)
    assert len(events(client)) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"instrument": " ", "price": 25000},
        {"instrument": "NIFTY", "price": "Infinity"},
        {"instrument": "NIFTY", "price": "bad"},
        {"instrument": "NIFTY"},
    ],
)
def test_invalid_tick_does_not_advance_previous_price(client, payload):
    add_level(client)
    publish(client, 24990)
    assert client.post("/simulation/tick", json=payload).status_code == 422
    assert events(client) == []
    publish(client, 25005)
    assert events(client)[0]["previous_price"] == 24990


def test_recent_events_are_bounded_and_newest_first(client):
    # Test signal/trigger semantics without a successful entry disarming the level.
    client.app.state.paper_executor.prices = SimulatedOptionPrices()
    add_level(client)
    publish(client, 24990)
    for index in range(105):
        publish(client, 25005 if index % 2 == 0 else 24990)
    result = events(client)
    assert len(result) == 100
    assert [event["id"] for event in result] == list(range(105, 5, -1))


def test_simulation_state_resets_on_restart(tmp_path):
    path = tmp_path / "restart.sqlite3"
    with TestClient(create_app(path)) as client:
        add_level(client)
        publish(client, 24990)
        publish(client, 25005)
        assert len(events(client)) == 1
    with TestClient(create_app(path)) as client:
        assert events(client) == []
        publish(client, 24990)
        assert events(client) == []


def test_concurrent_duplicate_publications(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    initialize_database(path)
    repository = LevelRepository(path)
    create_active_record(repository, LevelInput(instrument="NIFTY", price=25000, enabled=True))

    async def scenario():
        monitor = LevelMonitor(repository)
        provider: MarketDataProvider = SimulatedMarketDataProvider(monitor.on_tick)
        await provider.publish(PriceTick(instrument="NIFTY", price=24990))
        await asyncio.gather(
            *(provider.publish(PriceTick(instrument="NIFTY", price=25000)) for _ in range(5))
        )
        assert len(monitor.recent_events()) == 1

    asyncio.run(scenario())
