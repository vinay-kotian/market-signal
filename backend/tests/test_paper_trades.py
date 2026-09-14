from datetime import datetime, timezone
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.database import connect
from app.main import create_app
from app.option_models import StoredOptionSelection
from app.option_instruments import SimulatedOptionInstrumentSource
from app.option_prices import SimulatedOptionPrices
from app.settings import TradeSettings
from app.signal_models import SignalResult
from app.trade_repository import TradeRepository


def add_level(client, instrument="NIFTY", price=25000):
    assert client.post('/levels', json={"instrument": instrument, "price": price, "enabled": True}).status_code == 201


def publish(client, prices, instrument="NIFTY"):
    for price in prices:
        assert client.post('/simulation/tick', json={"instrument": instrument, "price": price}).status_code == 200


@pytest.mark.parametrize("instrument,level,lot_size", [("NIFTY", 25000, 10), ("BANKNIFTY", 51000, 20)])
def test_successful_entry_quantity_and_get_trades(tmp_path, instrument, level, lot_size):
    app = create_app(tmp_path / 'trades.sqlite3', trade_settings=TradeSettings(number_of_lots=3))
    with TestClient(app) as client:
        assert client.get('/trades').json() == []
        add_level(client, instrument, level)
        publish(client, [level - 100, level], instrument)
        response = client.get('/trades')
        assert response.status_code == 200
        trade, = response.json()
        assert trade['quantity'] == lot_size * 3
        assert trade['lot_size'] == lot_size
        assert trade['number_of_lots'] == 3
        assert trade['trade_mode'] == 'PAPER'
        assert trade['status'] == 'OPEN'
        assert trade['trigger_level'] == level
        assert trade['direction'] == 'FROM_BELOW'
        assert trade['option_type'] == 'PE'
        assert trade['entry_price'] == (100 if instrument == 'NIFTY' else 200)
        signal, = client.get('/signals').json()
        selection, = client.get('/option-selections').json()
        assert trade['signal_id'] == signal['id']
        assert trade['option_selection_id'] == selection['id']
        assert trade['option_symbol'] == selection['option_symbol']
        assert trade['strike'] == selection['itm_strike']
        assert trade['expiry'] == selection['expiry']
        assert trade['entry_time'] == signal['timestamp']


def test_idempotent_execution_survives_restart(tmp_path):
    path = tmp_path / 'restart.sqlite3'
    with TestClient(create_app(path)) as client:
        add_level(client)
        publish(client, [25100, 25000, 25000])
        original, = client.get('/trades').json()
        signal = SignalResult(**client.get('/signals').json()[0])
        selection = StoredOptionSelection(**client.get('/option-selections').json()[0])
    assert TradeRepository(path).recent()[0].trade_id == original['trade_id']
    app = create_app(path, trade_settings=TradeSettings(number_of_lots=5), option_prices=SimulatedOptionPrices())
    with TestClient(app) as client:
        # Same selection returns its original trade even with no quote and changed quantity settings.
        result = app.state.paper_executor.execute(signal, selection, datetime.now(timezone.utc))
        assert result.trade_id == original['trade_id']
        assert client.get('/trades').json() == [original]


@pytest.mark.parametrize('quote', [None, 0, -1, float('nan'), float('inf')])
def test_missing_or_invalid_quote_stores_failure_not_trade(tmp_path, quote):
    prices = SimulatedOptionPrices()
    app = create_app(tmp_path / 'missing.sqlite3', option_prices=prices)
    with TestClient(app) as client:
        for c in app.state.paper_executor.instruments.contracts('NIFTY'):
            if quote is not None:
                prices.set_price(c.symbol, quote)
        add_level(client)
        publish(client, [24900, 25000])
        assert client.get('/trades').json() == []
        result, = client.get('/trade-entry-results').json()
        assert result['status'] == 'FAILED'
        assert result['failure_reason'] == 'OPTION_PRICE_UNAVAILABLE'
        assert result['trade_id'] is None
        assert result['option_selection_id'] == client.get('/option-selections').json()[0]['id']
    with TestClient(create_app(tmp_path / 'missing.sqlite3')) as client:
        assert client.get('/trade-entry-results').json() == [result]
        assert client.get('/trades').json() == []


def test_failed_selection_and_rejected_signal_never_enter(client):
    add_level(client, price=27000)
    publish(client, [27000])
    assert client.get('/trades').json() == []
    publish(client, [26900, 27000])
    assert client.get('/option-selections').json()[0]['status'] == 'FAILED'
    assert client.get('/trades').json() == []
    assert client.get('/trade-entry-results').json() == []


def test_live_mode_cannot_create_trade(tmp_path):
    with TestClient(create_app(tmp_path / 'live.sqlite3', trade_settings=TradeSettings(trade_mode='LIVE'))) as client:
        add_level(client)
        publish(client, [24900, 25000])
        assert client.get('/trades').json() == []
        assert client.get('/trade-entry-results').json()[0]['failure_reason'] == 'LIVE_MODE_NOT_SUPPORTED'


def test_quote_can_be_updated_and_failed_entry_retried(tmp_path):
    prices = SimulatedOptionPrices()
    app = create_app(tmp_path / 'retry.sqlite3', option_prices=prices)
    with TestClient(app) as client:
        add_level(client)
        publish(client, [24900, 25000])
        signal = SignalResult(**client.get('/signals').json()[0])
        selection = StoredOptionSelection(**client.get('/option-selections').json()[0])
        prices.set_price(selection.option_symbol, 123.45)
        result = app.state.paper_executor.execute(signal, selection, datetime.now(timezone.utc))
        assert result.status == 'OPEN'
        assert client.get('/trades').json()[0]['entry_price'] == 123.45
        assert client.get('/trade-entry-results').json()[0]['failure_reason'] is None


def test_trade_write_failure_rolls_back_entire_transition(tmp_path):
    path = tmp_path / 'atomic.sqlite3'
    with TestClient(create_app(path), raise_server_exceptions=False) as client:
        add_level(client)
        publish(client, [24900])
        with connect(path) as connection:
            connection.execute("""CREATE TRIGGER fail_trade BEFORE INSERT ON trades
                BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        assert client.post('/simulation/tick', json={'instrument': 'NIFTY', 'price': 25000}).status_code == 500
        assert client.get('/signals').json() == []
        assert client.get('/option-selections').json() == []
        assert client.get('/trades').json() == []
        with connect(path) as connection:
            connection.execute('DROP TRIGGER fail_trade')
        publish(client, [25000, 25000])
        assert len(client.get('/trades').json()) == 1


def test_trade_settings(monkeypatch):
    monkeypatch.setenv('NUMBER_OF_LOTS', '2')
    monkeypatch.setenv('TRADE_MODE', 'PAPER')
    assert TradeSettings.from_environment().number_of_lots == 2
    for value in [0, -1, 1.5]:
        with pytest.raises(ValidationError):
            TradeSettings(number_of_lots=value)


def test_unknown_lot_size_cannot_create_trade(tmp_path):
    source = SimulatedOptionInstrumentSource(datetime.now(timezone.utc).date())
    source._contracts = [replace(contract, lot_size=None) for contract in source._contracts]
    with TestClient(create_app(tmp_path / 'lot.sqlite3', option_source=source)) as client:
        add_level(client)
        publish(client, [24900, 25000])
        assert client.get('/trades').json() == []
        assert client.get('/trade-entry-results').json()[0]['failure_reason'] == 'INVALID_LOT_SIZE'
