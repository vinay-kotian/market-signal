from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import create_app
from app.trade_models import TradeEntry
from app.settings import SignalSettings, OptionSettings, TradeSettings


NOW = datetime(2026, 9, 14, 4, 30, tzinfo=timezone.utc)


def add_trade(client, index=1, pnl=None, instrument='NIFTY', entered=None):
    repository = client.app.state.trade_repository
    entry = TradeEntry(
        settings_snapshot={**SignalSettings().model_dump(mode="json"),
                           **OptionSettings().model_dump(mode="json"),
                           **TradeSettings().model_dump(mode="json")},
        signal_id=index, option_selection_id=index, instrument=instrument,
        trigger_level=25000, direction='FROM_BELOW', option_symbol=f'SIM{index}PE',
        option_type='PE', strike=25050, expiry='2026-09-17', lot_size=10,
        number_of_lots=1, quantity=10, entry_price=100, entry_time=entered or NOW,
        stop_loss_percentage=10, initial_stop_loss=90, highest_price=100,
        current_stop_loss=90, trailing_stop_percentage=10,
        breakeven_protection_enabled=True, breakeven_activation_percent=10,
        breakeven_lock_percent=0,
    )
    trade = repository.save(entry)
    if pnl is not None:
        with connect(repository.database_path) as connection:
            repository.close(trade, 100 + pnl / 10, NOW + timedelta(minutes=1),
                             'MARKET_CLOSING_EXIT', connection)
    return trade


def test_empty_report(client):
    response = client.get('/reports/paper-trading')
    assert response.status_code == 200
    report = response.json()
    assert report.pop('view') == 'STRATEGY'
    assert report.pop('profit_factor') is None
    assert all(value == 0 for value in report.values())


@pytest.mark.parametrize('pnl,wins,losses,gross_profit,gross_loss,factor', [
    (100, 1, 0, 100, 0, None), (-50, 0, 1, 0, 50, 0), (0, 0, 0, 0, 0, None),
])
def test_single_trade(client, pnl, wins, losses, gross_profit, gross_loss, factor):
    add_trade(client, pnl=pnl)
    report = client.get('/reports/paper-trading').json()
    assert report['total_trades'] == report['closed_trades'] == 1
    assert report['winning_trades'] == wins
    assert report['losing_trades'] == losses
    assert report['win_rate'] == wins * 100
    assert report['gross_profit'] == report['average_profit'] == report['maximum_profit'] == gross_profit
    assert report['gross_loss'] == report['average_loss'] == report['maximum_loss'] == gross_loss
    assert report['net_pnl'] == pnl
    assert report['profit_factor'] == factor


def test_mixed_and_open_trades(client):
    for index, pnl in enumerate([200, 100, -50, -100, 0, None], 1):
        add_trade(client, index, pnl)
    report = client.get('/reports/paper-trading').json()
    assert report == dict(view='STRATEGY', recorded_trades=6, included_trades=6, excluded_trades=0, total_trades=6, open_trades=1, closed_trades=5,
        winning_trades=2, losing_trades=2, breakeven_trades=1, win_rate=50,
        gross_profit=300, gross_loss=150, net_pnl=150, average_profit=150,
        average_loss=75, maximum_profit=200, maximum_loss=100, profit_factor=2)


def test_open_only_report(client):
    add_trade(client)
    report = client.get('/reports/paper-trading').json()
    assert report['total_trades'] == report['open_trades'] == 1
    assert report['closed_trades'] == report['winning_trades'] == report['losing_trades'] == 0
    assert report['net_pnl'] == report['win_rate'] == 0
    assert report['profit_factor'] is None
    assert client.get('/trades/history').json()['items'][0]['status'] == 'OPEN'


def test_paper_only(client):
    add_trade(client, 1, 100)
    other = add_trade(client, 2, 500)
    # Production schema forbids LIVE. Simulate a future mixed-mode DB without
    # introducing any live execution, to verify the read-side scope explicitly.
    with connect(client.app.state.database_path) as connection:
        connection.execute('PRAGMA ignore_check_constraints = ON')
        connection.execute("UPDATE trades SET trade_mode = 'LIVE' WHERE trade_id = ?", (other.trade_id,))
    report = client.get('/reports/paper-trading').json()
    assert report['total_trades'] == 1
    assert report['net_pnl'] == 100
    assert client.get('/trades/history').json()['total'] == 1
    assert client.get(f'/trades/{other.trade_id}').status_code == 404


def test_filters_pagination_and_newest_first(client):
    oldest = add_trade(client, 1, entered=NOW - timedelta(minutes=5))
    newest = add_trade(client, 2, 100, 'BANKNIFTY', NOW)
    middle = add_trade(client, 3, -50, 'NIFTY', NOW - timedelta(minutes=2))
    first = client.get('/trades/history?page_size=2').json()
    assert first['total'] == 3
    assert [t['trade_id'] for t in first['items']] == [newest.trade_id, middle.trade_id]
    second = client.get('/trades/history?page=2&page_size=2').json()
    assert [t['trade_id'] for t in second['items']] == [oldest.trade_id]
    assert client.get('/trades/history?page=3&page_size=2').json()['items'] == []
    filtered = client.get('/trades/history?status=CLOSED&instrument=nifty').json()
    assert filtered['total'] == 1
    assert filtered['items'][0]['trade_id'] == middle.trade_id
    assert client.get('/trades/history?status=OPEN').json()['total'] == 1
    assert client.get('/trades/history?instrument=UNKNOWN').json()['total'] == 0
    # Existing list contract remains compatible.
    assert len(client.get('/trades').json()) == 3


@pytest.mark.parametrize('query', ['page=0', 'page_size=0', 'page_size=101', 'status=BAD'])
def test_invalid_history_parameters(client, query):
    assert client.get('/trades/history?' + query).status_code == 422


def test_complete_timeline_ordering_and_reload(client):
    trade = add_trade(client, pnl=100)
    events = client.app.state.trade_events
    with connect(client.app.state.database_path) as connection:
        # Insert a historical event after closure; ordering must use time, then id.
        events.record(trade.trade_id, 'TRAILING_STOP_UPDATED', 105,
                      NOW + timedelta(seconds=30), connection, 90, 94.5)
    response = client.get(f'/trades/{trade.trade_id}')
    assert response.status_code == 200
    detail = response.json()
    assert detail['trade']['realised_pnl'] == 100
    assert [e['event_type'] for e in detail['events']] == [
        'POSITION_OPENED', 'TRAILING_STOP_UPDATED', 'MARKET_CLOSING_EXIT_TRIGGERED', 'POSITION_CLOSED']
    assert client.get(f'/trades/{trade.trade_id}/events').json() == detail['events']
    with TestClient(create_app(client.app.state.database_path)) as reloaded:
        assert reloaded.get(f'/trades/{trade.trade_id}').json() == detail
        assert reloaded.get('/reports/paper-trading').json()['net_pnl'] == 100
    assert client.get('/trades/99999').status_code == 404


def test_report_not_limited_to_latest_hundred(client):
    for index in range(1, 103):
        add_trade(client, index, 10)
    assert client.get('/reports/paper-trading').json()['net_pnl'] == 1020
    assert client.get('/trades/history').json()['total'] == 102
