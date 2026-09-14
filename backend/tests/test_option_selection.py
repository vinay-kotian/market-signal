import asyncio
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.database import connect, initialize_database
from app.level_monitor import LevelMonitor
from app.level_repository import LevelRepository
from app.main import create_app
from app.market_data import PriceTick
from app.models import LevelInput
from app.option_instruments import SimulatedOptionInstrumentSource
from app.option_repository import OptionSelectionRepository
from app.option_selector import OptionSelector
from app.settings import OptionSettings, SignalSettings
from app.signal_repository import SignalRepository


TODAY = date(2026, 9, 14)


@pytest.mark.parametrize("instrument,price,direction,depth,atm,strike,kind", [
    ("NIFTY", 25005, "FROM_ABOVE", 1, 25000, 24950, "CE"),
    ("NIFTY", 25005, "FROM_BELOW", 1, 25000, 25050, "PE"),
    ("NIFTY", 25005, "FROM_ABOVE", 2, 25000, 24900, "CE"),
    ("NIFTY", 25005, "FROM_BELOW", 2, 25000, 25100, "PE"),
    ("NIFTY", 25024.99, "FROM_ABOVE", 1, 25000, 24950, "CE"),
    ("NIFTY", 25025, "FROM_ABOVE", 1, 25050, 25000, "CE"),
    ("NIFTY", 25025.01, "FROM_BELOW", 1, 25050, 25100, "PE"),
    ("BANKNIFTY", 51050, "FROM_BELOW", 2, 51100, 51300, "PE"),
    ("BANKNIFTY", 51049.99, "FROM_ABOVE", 2, 51000, 50800, "CE"),
])
def test_selection_and_atm_rounding(instrument, price, direction, depth, atm, strike, kind):
    selector = OptionSelector(SimulatedOptionInstrumentSource(TODAY))
    selection = selector.select(instrument, price, direction, depth, TODAY)
    assert selection.status == "SELECTED"
    assert selection.atm_strike == atm
    assert selection.itm_strike == strike
    assert selection.option_type == kind
    assert selection.expiry == TODAY + timedelta(days=7)
    assert selection.option_symbol == f"SIM-{instrument}-{selection.expiry}-{strike}-{kind}"


def test_nearest_unexpired_expiry():
    selector = OptionSelector(SimulatedOptionInstrumentSource(TODAY))
    assert selector.select("NIFTY", 25000, "FROM_ABOVE", 1, TODAY + timedelta(days=7)).expiry == TODAY + timedelta(days=7)
    assert selector.select("NIFTY", 25000, "FROM_ABOVE", 1, TODAY + timedelta(days=8)).expiry == TODAY + timedelta(days=14)
    result = selector.select("NIFTY", 25000, "FROM_ABOVE", 1, TODAY + timedelta(days=15))
    assert result.failure_reason == "NO_UNEXPIRED_CONTRACT"


def test_missing_contract_does_not_fall_back_to_later_expiry():
    source = SimulatedOptionInstrumentSource(TODAY)
    source._contracts = [c for c in source._contracts if not (
        c.instrument == "NIFTY" and c.strike == 24950 and c.option_type == "CE"
        and c.expiry == TODAY + timedelta(days=7))]
    result = OptionSelector(source).select("NIFTY", 25000, "FROM_ABOVE", 1, TODAY)
    assert result.status == "FAILED"
    assert result.failure_reason == "MISSING_OPTION_CONTRACT"
    assert result.option_symbol is None
    assert result.itm_strike == 24950
    assert result.expiry == TODAY + timedelta(days=7)


def add_level(client, price=25000, instrument="NIFTY"):
    response = client.post("/levels", json={"instrument": instrument, "price": price, "enabled": True})
    assert response.status_code == 201


def ticks(client, prices, instrument="NIFTY"):
    for price in prices:
        assert client.post("/simulation/tick", json={"instrument": instrument, "price": price}).status_code == 200
    response = client.get("/option-selections")
    assert response.status_code == 200
    return response.json()


def test_selection_persists_and_depth_setting_is_used(tmp_path):
    path = tmp_path / "options.sqlite3"
    with TestClient(create_app(path, option_settings=OptionSettings(itm_depth=2))) as client:
        add_level(client)
        selections = ticks(client, [24900, 25005, 25005])
        selected, = selections
        assert selected["itm_strike"] == 25100
        assert selected["signal_id"] == client.get("/signals").json()[0]["id"]
    assert OptionSelectionRepository(path).recent()[0].id == selected["id"]
    with TestClient(create_app(path)) as client:
        assert client.get("/option-selections").json() == selections
        selections = ticks(client, [25100, 24995])
        assert selections[0]["id"] > selected["id"]
        assert selections[0]["option_type"] == "CE"


@pytest.mark.parametrize("prices", [[25000], [24990, 25000]])
def test_rejected_signals_do_not_select(tmp_path, prices):
    with TestClient(create_app(tmp_path / "reject.sqlite3", SignalSettings(
        minimum_approach_distance_enabled=True, minimum_approach_distance_points=100,
    ))) as client:
        add_level(client)
        assert ticks(client, prices) == []
        assert client.get("/signals").json()[0]["valid"] is False


def test_multiple_levels_each_get_a_selection(client):
    add_level(client)
    add_level(client, price=25100)
    selections = ticks(client, [24900, 25110])
    assert len(selections) == 2
    assert len({s["signal_id"] for s in selections}) == 2


@pytest.mark.parametrize("instrument,level,reason", [
    ("NIFTY", 27000, "MISSING_OPTION_CONTRACT"),
    ("UNKNOWN", 25000, "UNSUPPORTED_INSTRUMENT"),
])
def test_failed_selection_is_persisted(client, instrument, level, reason):
    add_level(client, level, instrument)
    selected, = ticks(client, [level - 100, level], instrument)
    assert selected["status"] == "FAILED"
    assert selected["failure_reason"] == reason
    assert selected["option_symbol"] is None
    assert client.get("/signals").json()[0]["valid"] is True


def test_option_write_failure_rolls_back_signals_and_can_retry(tmp_path):
    path = tmp_path / "atomic.sqlite3"
    initialize_database(path)
    levels = LevelRepository(path)
    levels.create(LevelInput(instrument="NIFTY", price=25000, enabled=True))
    with connect(path) as connection:
        connection.execute("""CREATE TRIGGER fail_option BEFORE INSERT ON option_selections
            BEGIN SELECT RAISE(ABORT, 'test failure'); END""")

    async def scenario():
        monitor = LevelMonitor(levels)
        await monitor.on_tick(PriceTick(instrument="NIFTY", price=24900))
        with pytest.raises(sqlite3.IntegrityError):
            await monitor.on_tick(PriceTick(instrument="NIFTY", price=25000))
        assert SignalRepository(path).recent() == []
        assert OptionSelectionRepository(path).recent() == []
        with connect(path) as connection:
            connection.execute("DROP TRIGGER fail_option")
        await monitor.on_tick(PriceTick(instrument="NIFTY", price=25000))
        assert len(SignalRepository(path).recent()) == 1
        assert len(OptionSelectionRepository(path).recent()) == 1

    asyncio.run(scenario())


def test_settings_from_environment(monkeypatch):
    monkeypatch.setenv("ITM_DEPTH", "2")
    monkeypatch.setenv("EXPIRY_STRATEGY", "NEAREST")
    assert OptionSettings.from_environment().itm_depth == 2
    with pytest.raises(ValidationError):
        OptionSettings(itm_depth=0)
    with pytest.raises(ValidationError):
        OptionSettings(expiry_strategy="FARTHEST")


@pytest.mark.parametrize("price", [25000, 27000])
def test_signal_id_is_idempotency_boundary_across_repository_reload(tmp_path, price):
    path = tmp_path / "idempotent.sqlite3"
    initialize_database(path)
    selector = OptionSelector(SimulatedOptionInstrumentSource(TODAY))
    selection = selector.select("NIFTY", price, "FROM_ABOVE", 1, TODAY)
    timestamp = datetime(2026, 9, 14, tzinfo=timezone.utc)
    repository = OptionSelectionRepository(path)
    first = repository.save(42, selection, timestamp)
    assert repository.save(42, selection, timestamp) == first

    # Reprocessing after restart/config changes must not overwrite the first result.
    reloaded = OptionSelectionRepository(path)
    different_selection = selector.select("NIFTY", 25000, "FROM_BELOW", 2, TODAY)
    with connect(path) as connection:
        retry = reloaded.save(42, different_selection, timestamp + timedelta(minutes=1),
                              connection=connection)
        assert retry == first
    assert reloaded.recent() == [first]
    assert first.status == ("SELECTED" if price == 25000 else "FAILED")

    # A distinct signal can legitimately select the same contract.
    second = reloaded.save(43, selection, timestamp)
    assert second.id != first.id
    assert len(reloaded.recent()) == 2
