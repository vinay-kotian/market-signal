from active_level_fixture import create_active_level, create_active_record
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.level_monitor import LevelMonitor
from app.signal_engine import SignalEngine


SYMBOL = 'SIM-NIFTY-2026-09-21-25050-PE'


def tick(time, instrument, price):
    return dict(timestamp=f'2026-09-14T{time}+05:30', instrument=instrument, price=price)


def dataset(option_ticks=()):
    return [tick('09:59:00', SYMBOL, 100), tick('09:59:30', 'NIFTY', 24930), tick('10:00:00', 'NIFTY', 24900),
            tick('10:01:00', 'NIFTY', 25000),
            *[tick(time, SYMBOL, price) for time, price in option_ticks]]


def run(client, rows=None, **settings):
    response = client.post('/backtests/run', json=dict(instrument='NIFTY', levels=[25000],
                           dataset=rows if rows is not None else dataset(), **settings))
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['status'] == 'COMPLETED', result
    return result


def test_replay_order_and_shared_services(client, monkeypatch):
    seen, analyses = [], []
    original_tick, original_analyze = LevelMonitor.on_tick, SignalEngine.analyze

    async def observe_tick(self, tick):
        seen.append((self._clock(), tick.price))
        return await original_tick(self, tick)

    def observe_analyze(self, trigger, history):
        analyses.append(trigger)
        return original_analyze(self, trigger, history)

    monkeypatch.setattr(LevelMonitor, 'on_tick', observe_tick)
    monkeypatch.setattr(SignalEngine, 'analyze', observe_analyze)
    result = run(client, list(reversed(dataset())))
    assert [price for _, price in seen] == [24930, 24900, 25000]
    assert seen[0][0] < seen[1][0]
    assert len(analyses) == 1
    assert result['signals'][0]['direction'] == 'FROM_BELOW'
    assert result['signals'][0]['approach_distance'] == 100
    assert result['trades'][0]['trade_mode'] == 'BACKTEST'
    assert result['open_trades'] == 1
    assert result['wins'] == result['losses'] == 0


@pytest.mark.parametrize('minimum,expected', [(50, 1), (101, 0)])
def test_signal_distance_rule(client, minimum, expected):
    result = run(client, minimum_approach_distance_enabled=True,
                 minimum_approach_distance_points=minimum)
    assert result['total_trades'] == expected
    assert result['signals'][0]['valid'] == bool(expected)


@pytest.mark.parametrize('price', [90, 85])
def test_initial_stop(client, price):
    result = run(client, dataset([('10:02:00', price)]))
    trade, = result['trades']
    assert trade['exit_reason'] == 'STOP_LOSS'
    assert trade['initial_stop_loss'] == 90
    assert trade['exit_price'] == price
    assert result['net_pnl'] == (price - 100) * 10
    assert result['losses'] == 1


def test_trailing_and_breakeven(client):
    result = run(client, dataset([('10:02:00', 105), ('10:03:00', 110),
                                 ('10:04:00', 120), ('10:05:00', 115), ('10:06:00', 108)]))
    trade, = result['trades']
    assert trade['highest_price'] == 120
    assert trade['current_stop_loss'] == 108
    assert trade['breakeven_activated'] is True
    assert trade['exit_price'] == 108
    assert result['net_pnl'] == 80
    kinds = [event['event_type'] for event in result['events'][str(trade['trade_id'])]]
    assert kinds.count('BREAKEVEN_PROTECTION_ACTIVATED') == 1
    assert kinds.count('TRAILING_STOP_UPDATED') == 2
    assert kinds.count('POSITION_CLOSED') == 1


def test_breakeven_entry_protection(client):
    result = run(client, dataset([('10:02:00', 110), ('10:03:00', 100)]))
    assert result['trades'][0]['current_stop_loss'] == 100
    assert result['breakeven'] == 1
    assert result['net_pnl'] == 0


def test_mandatory_deadline_no_lookahead(client):
    rows = dataset([('10:02:00', 105), ('15:26:00', 200)])
    result = run(client, rows)
    trade, = result['trades']
    assert trade['exit_price'] == 105  # Never use the future 15:26 quote.
    assert trade['exit_time'] == '2026-09-14T15:25:00+05:30'
    assert trade['exit_reason'] == 'MARKET_CLOSING_EXIT'
    assert result['net_pnl'] == 50
    events = result['events'][str(trade['trade_id'])]
    assert [e['event_type'] for e in events][-2:] == ['MARKET_CLOSING_EXIT_TRIGGERED', 'POSITION_CLOSED']


def test_range_end_advances_timer(client):
    result = run(client, end_time='2026-09-14T15:30:00+05:30')
    assert result['trades'][0]['exit_reason'] == 'MARKET_CLOSING_EXIT'
    assert result['trades'][0]['exit_price'] == 100


def test_no_future_entry_quote(client):
    rows = dataset()[1:] + [tick('10:02:00', SYMBOL, 100)]
    result = run(client, rows)
    assert result['total_trades'] == 0
    assert result['entry_results'][0]['failure_reason'] == 'OPTION_PRICE_UNAVAILABLE'


def test_repeat_runs_and_paper_state_are_isolated(client):
    # Preserve existing app state while replaying multiple independent histories.
    create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
    client.post('/simulation/tick', json=dict(instrument='NIFTY', price=24900))
    paths = ['/levels', '/trades', '/reports/paper-trading', '/signals', '/simulation/events']
    before = {path: client.get(path).json() for path in paths}
    result1 = run(client, dataset([('10:02:00', 90)]))
    result2 = run(client, dataset([('10:02:00', 90)]))
    assert result1['id'] != result2['id']
    assert result1['trades'] == result2['trades']
    assert result1['signals'] == result2['signals']
    assert {path: client.get(path).json() for path in paths} == before
    client.post('/simulation/tick', json=dict(instrument='NIFTY', price=25000))
    assert client.get('/trades').json()[0]['entry_price'] == 100
    assert client.get('/trades').json()[0]['trade_mode'] == 'PAPER'
    assert client.get('/reports/paper-trading').json()['total_trades'] == 1


def test_persistence_demo_and_unknown_id(client):
    result = client.post('/backtests/run', json=dict(instrument='NIFTY', levels=[25000], fixture='nifty-demo')).json()
    assert result['status'] == 'COMPLETED'
    assert result['total_trades'] == 1
    with TestClient(create_app(client.app.state.database_path)) as restarted:
        assert restarted.get('/backtests/' + result['id']).json() == result
    assert client.get('/backtests/00000000-0000-0000-0000-000000000000').status_code == 404
    assert client.get('/backtests/not-a-uuid').status_code == 422


@pytest.mark.parametrize('updates', [
    {'trading_start_time': '10:02'}, {'new_trade_cutoff_time': '10:00'},
])
def test_entry_window_reused(client, updates):
    result = run(client, **updates)
    assert result['total_trades'] == 0
    assert result['entry_results'][0]['failure_reason'] in ('BEFORE_TRADING_START', 'NEW_TRADE_CUTOFF_REACHED')


@pytest.mark.parametrize('updates', [
    {'dataset': []}, {'dataset': [dict(timestamp='2026-09-14T10:00:00', instrument='NIFTY', price=25000)]},
    {'fixture': 'nifty-demo'}, {'trade_mode': 'LIVE'}, {'levels': [0]},
    {'dataset': [tick('10:00:00', 'UNKNOWN', 100)]},
])
def test_invalid_input(client, updates):
    payload = dict(instrument='NIFTY', levels=[25000], dataset=dataset())
    payload.update(updates)
    assert client.post('/backtests/run', json=payload).status_code == 422


def test_backtest_reuses_level_rearming(client):
    rows = dataset([('10:01:30', 90)]) + [
        tick('10:02:00', 'NIFTY', 24990), tick('10:03:00', 'NIFTY', 25000),
        tick('10:04:00', 'NIFTY', 24950), tick('10:05:00', 'NIFTY', 25000)]
    result = run(client, rows)
    assert len(result['signals']) == len(result['trades']) == 2
    assert result['trades'][0]['entry_time'].startswith('2026-09-14T10:05:00')
    # A different distance applies to this isolated run only.
    result = run(client, rows, level_rearm_distance_points=75)
    assert len(result['signals']) == len(result['trades']) == 1
