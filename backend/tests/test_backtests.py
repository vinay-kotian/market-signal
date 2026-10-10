"""Single-day fixtures validate shared strategy decisions and historical execution."""
from datetime import datetime
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.level_monitor import LevelMonitor
from app.signal_engine import SignalEngine
from app.paper_executor import PaperExecutor
from app.historical_market_data import LocalHistoricalDataSource

DATE = '2026-09-14'
SYMBOL = 'TEST-NIFTY-20260917-25050-PE'
CE = 'TEST-NIFTY-20260917-24950-CE'
CONTRACTS = [dict(instrument='NIFTY', expiry='2026-09-17', strike=25050,
                 option_type='PE', symbol=SYMBOL, lot_size=10, instrument_token=123),
             dict(instrument='NIFTY', expiry='2026-09-17', strike=24950,
                 option_type='CE', symbol=CE, lot_size=10, instrument_token=124)]


def tick(time, instrument, price):
    return dict(timestamp=f'{DATE}T{time}+05:30', instrument=instrument, price=price)


def dataset(option_ticks=(), *, close=True, entry=True):
    rows = [tick('09:59:00', SYMBOL, 999), tick('09:59:30', 'NIFTY', 24930),
            tick('10:00:00', 'NIFTY', 24900), tick('10:01:00', 'NIFTY', 25000)]
    if entry:
        rows.append(tick('10:01:01', SYMBOL, 100))
    rows.extend(tick(time, SYMBOL, price) for time, price in option_ticks)
    if close:
        rows.append(tick('15:27:05', SYMBOL, 100))
    return rows


def post(client, rows=None, **settings):
    return client.post('/backtests/run', json={**dict(trading_date=DATE, instrument='NIFTY', levels=[25000],
        contracts=CONTRACTS, dataset=rows if rows is not None else dataset()), **settings})


def run(client, rows=None, **settings):
    response = post(client, rows, **settings)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['status'] == 'COMPLETED', result
    return result


def test_replay_order_and_shared_services(client, monkeypatch):
    seen, analyses, executions = [], [], []
    original_tick, original_analyze, original_execute = LevelMonitor.on_tick, SignalEngine.analyze, PaperExecutor.execute

    async def observe_tick(self, tick):
        seen.append((self._clock(), tick.price))
        return await original_tick(self, tick)

    def observe_analyze(self, trigger, history):
        analyses.append(trigger)
        return original_analyze(self, trigger, history)

    def observe_execute(self, *args, **kwargs):
        executions.append(args[2])
        return original_execute(self, *args, **kwargs)

    monkeypatch.setattr(LevelMonitor, 'on_tick', observe_tick)
    monkeypatch.setattr(SignalEngine, 'analyze', observe_analyze)
    monkeypatch.setattr(PaperExecutor, 'execute', observe_execute)
    result = run(client, list(reversed(dataset())))
    assert [price for _, price in seen] == [24930, 24900, 25000]
    assert seen[0][0] < seen[1][0]
    assert len(analyses) == len(executions) == 1
    assert result['signals'][0]['direction'] == 'FROM_BELOW'
    assert result['signals'][0]['approach_distance'] == 100
    assert result['trades'][0]['trade_mode'] == 'BACKTEST'
    assert result['trades'][0]['entry_price'] == 100  # Not the previously observed 999.
    assert result['trades'][0]['entry_time'] == f'{DATE}T10:01:01+05:30'
    assert result['trades'][0]['instrument_token'] == 123
    assert result['open_trades'] == 0


def test_initial_arm_distance_and_touch_before_arming(client):
    rows = [tick(t, 'NIFTY', p) for t, p in [('10:00:00', 25000), ('10:00:10', 25030),
        ('10:00:20', 25000), ('10:00:30', 25060), ('10:00:40', 25085), ('10:00:50', 25000)]]
    rows += [tick('10:00:51', CE, 100), tick('10:01:00', CE, 90)]
    result = run(client, rows, index_settings={'NIFTY': {'initial_arm_distance_points': 80}})
    assert len(result['signals']) == len(result['trades']) == 1
    assert result['signals'][0]['timestamp'] == f'{DATE}T10:00:50+05:30'
    assert result['signals'][0]['direction'] == 'FROM_ABOVE'
    assert result['trades'][0]['option_type'] == 'CE'
    armed = [e for e in result['timeline'] if e['event_type'] == 'LEVEL_ARMED']
    assert armed[0]['timestamp'] == f'{DATE}T10:00:40+05:30'


@pytest.mark.parametrize('minimum,expected', [(50, 1), (101, 0)])
def test_signal_distance_rule(client, minimum, expected):
    result = run(client, minimum_approach_distance_enabled=True, minimum_approach_distance_points=minimum)
    assert result['total_trades'] == expected
    assert result['signals'][0]['valid'] == bool(expected)


def test_historical_expiry_and_itm(client):
    deeper = {**CONTRACTS[0], 'strike': 25100, 'symbol': 'TEST-DEEP-PE'}
    expired = {**deeper, 'expiry': '2026-09-10', 'symbol': 'TEST-EXPIRED-PE'}
    later = {**deeper, 'expiry': '2026-09-24', 'symbol': 'TEST-LATER-PE'}
    response = client.post('/backtests/run', json=dict(trading_date=DATE, instrument='NIFTY', levels=[25000],
        itm_depth=2, contracts=[later, expired, deeper], dataset=[
            tick('10:00:00', 'NIFTY', 24900), tick('10:01:00', 'NIFTY', 25024),
            tick('10:01:02', deeper['symbol'], 200), tick('10:02:00', deeper['symbol'], 180)]))
    result = response.json()
    assert result['status'] == 'COMPLETED', result
    trade, = result['trades']
    assert trade['option_symbol'] == deeper['symbol']
    assert trade['strike'] == 25100
    assert trade['expiry'] == '2026-09-17'
    assert result['option_selections'][0]['atm_strike'] == 25000
    assert any(e['event_type'] == 'LEVEL_CROSS' for e in result['timeline'])


@pytest.mark.parametrize('price', [90, 85])
def test_initial_stop(client, price):
    result = run(client, dataset([('10:02:00', price)]))
    trade, = result['trades']
    assert trade['exit_reason'] == 'STOP_LOSS'
    assert trade['initial_stop_loss'] == 90
    assert trade['exit_price'] == price
    assert result['net_pnl'] == (price - 100) * 10
    assert result['losses'] == 1


def test_trailing_breakeven_and_monotonic_stops(client):
    result = run(client, dataset([('10:02:00', 105), ('10:03:00', 110),
        ('10:04:00', 120), ('10:05:00', 115), ('10:06:00', 108)]), stop_strategy='LEGACY')
    trade, = result['trades']
    assert trade['highest_price'] == 120
    assert trade['current_stop_loss'] == 108
    assert trade['breakeven_activated'] is True
    assert trade['exit_price'] == 108
    assert result['net_pnl'] == 80
    events = result['events'][str(trade['trade_id'])]
    assert [e['current_stop'] for e in events if e['current_stop'] is not None] == sorted(
        e['current_stop'] for e in events if e['current_stop'] is not None)
    kinds = [e['event_type'] for e in result['timeline']]
    for kind in ('MARKET_OPEN', 'LEVEL_OBSERVED', 'LEVEL_ARMED', 'LEVEL_TOUCH', 'SIGNAL_CREATED',
                 'OPTION_SELECTED', 'TRADE_ENTERED', 'STOP_UPDATED', 'BREAKEVEN_ACTIVATED',
                 'TRAILING_UPDATED', 'EXIT_TRIGGERED', 'TRADE_EXITED', 'MARKET_CLOSE'):
        assert kind in kinds
    stamps = [datetime.fromisoformat(e['timestamp']) for e in result['timeline']]
    assert stamps == sorted(stamps)
    assert result['timeline'][0]['timestamp'] == f'{DATE}T09:15:00+05:30'
    assert result['timeline'][-1]['timestamp'] == f'{DATE}T15:30:00+05:30'


def test_breakeven_locked_profit(client):
    result = run(client, dataset([('10:02:00', 110), ('10:03:00', 105)]), stop_strategy='LEGACY', breakeven_lock_percent=5)
    assert result['trades'][0]['current_stop_loss'] == 105
    assert result['net_pnl'] == 50
    assert result['wins'] == 1
    result = run(client, dataset([('10:02:00', 110), ('10:03:00', 100)]), stop_strategy='LEGACY')
    assert result['breakeven'] == 1


def test_progressive_dynamic_trailing_step(client):
    result = run(client, dataset([('10:02:00', 110), ('10:03:00', 120), ('10:04:00', 140),
        ('10:05:00', 150), ('10:06:00', 145), ('10:07:00', 141)]))
    trade, = result['trades']
    assert trade['profit_lock_activated']
    assert trade['trailing_step'] == 4
    assert trade['trailing_pct'] == 6
    assert trade['current_stop_loss'] == 141
    assert trade['highest_price'] == 150
    assert trade['exit_price'] == 141
    assert trade['exit_reason'] == 'TRAILING_STOP_LOSS'
    assert sum(e['event_type'] == 'TRAILING_STEP_CHANGED' for e in result['timeline']) == 3


def test_mandatory_exit_uses_first_post_deadline_quote(client):
    result = run(client, dataset([('10:02:00', 105), ('15:26:59', 109), ('15:28:00', 200)], close=False))
    trade, = result['trades']
    assert trade['exit_price'] == 200
    assert trade['exit_time'] == f'{DATE}T15:28:00+05:30'
    assert trade['exit_reason'] == 'MARKET_CLOSE'
    event, = [e for e in result['timeline'] if e['event_type'] == 'MANDATORY_EXIT']
    assert event['timestamp'] == f'{DATE}T15:27:00+05:30'
    assert event['payload'].get('option_price') is None  # Not the earlier 109 or future 200.


def test_entry_first_quote_equal_timestamp_and_stable_ties(client):
    rows = dataset(entry=False)
    rows += [tick('10:01:00', SYMBOL, 100), tick('10:01:00', SYMBOL, 90)]
    result = run(client, rows)
    assert result['trades'][0]['entry_price'] == 100
    assert result['trades'][0]['exit_price'] == 90
    # An equal-time quote preceding the signal is also available at that timestamp.
    rows = [tick('10:01:00', SYMBOL, 100)] + dataset(entry=False)
    result = run(client, rows)
    assert result['trades'][0]['entry_price'] == 100


def test_future_quote_enters_at_actual_observation(client):
    rows = dataset(entry=False) + [tick('10:02:00', SYMBOL, 123)]
    result = run(client, rows)
    assert result['trades'][0]['entry_price'] == 123
    assert result['trades'][0]['entry_time'] == f'{DATE}T10:02:00+05:30'
    assert result['trades'][0]['signal_timestamp'] == f'{DATE}T10:01:00+05:30'


@pytest.mark.parametrize('rows', [dataset(close=False), dataset(close=False, entry=False)])
def test_missing_quotes_fail_transparently_and_persist_partial_results(client, rows):
    response = post(client, rows)
    assert response.status_code == 201
    result = response.json()
    assert result['status'] == 'FAILED'
    assert 'Historical option data incomplete' in result['error_message']
    assert client.get('/backtests/' + result['id']).json() == result
    assert result['timeline']


def test_zero_quote_cannot_fill_entry(client):
    rows = dataset(entry=False) + [tick('10:01:01', SYMBOL, 0), tick('10:01:02', SYMBOL, 100)]
    result = run(client, rows)
    assert result['trades'][0]['entry_time'] == f'{DATE}T10:01:02+05:30'
    assert any(e['event_type'] == 'ZERO_OPTION_QUOTE' for e in result['timeline'])


@pytest.mark.parametrize('timestamp,reason', [('10:02:00', 'STOP_LOSS'), ('15:27:00', 'MARKET_CLOSE')])
def test_zero_option_quote_closes_like_paper(client, timestamp, reason):
    result = run(client, dataset([(timestamp, 0)]))
    assert result['trades'][0]['exit_price'] == 0
    assert result['trades'][0]['exit_reason'] == reason
    assert result['trades'][0]['realised_pnl_percentage'] == -100


def test_repeat_runs_and_paper_state_are_isolated(client):
    paths = ['/levels', '/trades', '/reports/paper-trading', '/signals', '/simulation/events']
    before = {path: client.get(path).json() for path in paths}
    result1 = run(client, dataset([('10:02:00', 90)]))
    result2 = run(client, dataset([('10:02:00', 90)]))
    assert result1['id'] != result2['id']
    assert result1['trades'] == result2['trades']
    assert result1['signals'] == result2['signals']
    assert result1['dataset_hash'] == result2['dataset_hash']
    assert {path: client.get(path).json() for path in paths} == before
    assert client.get('/reports/paper-trading').json()['total_trades'] == 0
    assert len(client.get('/backtests').json()) == 2


def test_settings_snapshot_inherits_current_and_never_changes(client):
    settings = client.get('/settings/protection').json()
    client.put('/settings/protection', json={**settings, 'initial_stop_loss_pct': 20})
    client.put('/settings/indexes/NIFTY', json={'initial_arm_distance_points': 80})
    result = run(client, dataset([('10:02:00', 85), ('10:03:00', 80)]))
    assert result['trades'][0]['initial_stop_loss'] == 80
    assert result['settings_snapshot']['initial_stop_loss_pct'] == 20
    assert result['settings_snapshot']['index_settings']['NIFTY']['initial_arm_distance_points'] == 80
    client.put('/settings/protection', json={**settings, 'initial_stop_loss_pct': 5})
    client.put('/settings/indexes/NIFTY', json={'initial_arm_distance_points': 10})
    assert client.get('/backtests/' + result['id']).json() == result
    overridden = run(client, dataset([('10:02:00', 85)]), initial_stop_loss_pct=15)
    assert overridden['trades'][0]['initial_stop_loss'] == 85


def test_persistence_demo_and_unknown_id(client):
    result = client.post('/backtests/run', json=dict(trading_date=DATE, instrument='NIFTY', levels=[25000], fixture='nifty-demo')).json()
    assert result['status'] == 'COMPLETED', result
    assert result['data_source'] == 'SYNTHETIC_DEMO'
    assert result['total_trades'] == 1
    with TestClient(create_app(client.app.state.database_path)) as restarted:
        assert restarted.get('/backtests/' + result['id']).json() == result
    assert client.get('/backtests/00000000-0000-0000-0000-000000000000').status_code == 404
    assert client.get('/backtests/not-a-uuid').status_code == 422


@pytest.mark.parametrize('updates', [{'trading_start_time': '10:02'}, {'new_trade_cutoff_time': '10:00'}])
def test_entry_window_reused(client, updates):
    result = run(client, **updates)
    assert result['total_trades'] == 0
    assert result['entry_results'][0]['failure_reason'] in ('BEFORE_TRADING_START', 'NEW_TRADE_CUTOFF_REACHED')


def test_delayed_entry_after_cutoff_rejected(client):
    result = run(client, dataset(entry=False), new_trade_cutoff_time='10:01:30')
    assert result['total_trades'] == 0
    assert result['entry_results'][0]['failure_reason'] == 'NEW_TRADE_CUTOFF_REACHED'


@pytest.mark.parametrize('updates', [
    {'dataset': []}, {'dataset': [dict(timestamp=f'{DATE}T10:00:00', instrument='NIFTY', price=25000)]},
    {'fixture': 'nifty-demo'}, {'trade_mode': 'LIVE'}, {'levels': [0]}, {'contracts': []},
    {'contracts': [CONTRACTS[0], CONTRACTS[0]]}, {'instrument': 'UNKNOWN'},
    {'dataset': [tick('10:00:00', 'UNKNOWN', 100)]}, {'trading_date': '2026-09-15'},
    {'contracts': [{**CONTRACTS[0], 'lot_size': 0}]}, {'mandatory_exit_time': '15:45'},
])
def test_invalid_input(client, updates):
    payload = dict(trading_date=DATE, instrument='NIFTY', levels=[25000], contracts=CONTRACTS, dataset=dataset())
    payload.update(updates)
    assert client.post('/backtests/run', json=payload).status_code == 422


def test_multiple_levels_active_restriction_reservation_and_dedup(client):
    rows = dataset() + [tick('10:01:00', 'NIFTY', 25000), tick('10:02:00', 'NIFTY', 24900),
                       tick('10:03:00', 'NIFTY', 25000)]
    result = run(client, rows, levels=[25000, 24950, 25000])
    assert len(result['levels']) == 2
    assert result['total_trades'] == 1
    assert any(r['failure_reason'] == 'ACTIVE_TRADE_EXISTS' for r in result['entry_results'])
    assert len([t for t in result['trades'] if t['signal_id'] == result['trades'][0]['signal_id']]) == 1


def test_rearming_after_exit_uses_existing_monitor(client):
    rows = dataset([('10:01:30', 90)]) + [tick('10:02:00', 'NIFTY', 24990),
        tick('10:03:00', 'NIFTY', 25000), tick('10:04:00', 'NIFTY', 24950),
        tick('10:05:00', 'NIFTY', 25000), tick('10:05:01', SYMBOL, 100)]
    result = run(client, rows)
    assert len(result['signals']) == len(result['trades']) == 2
    assert result['trades'][0]['entry_time'].startswith(f'{DATE}T10:05:01')
    result = run(client, rows, index_settings={'NIFTY': {'initial_arm_distance_points': 75}})
    assert len(result['signals']) == len(result['trades']) == 1


def test_local_archive_adapter_and_unavailable_data(client, tmp_path):
    payload = dict(trading_date=DATE, instrument='NIFTY', levels=[25000])
    assert client.post('/backtests/run', json=payload).status_code == 422
    (tmp_path / f'{DATE}-NIFTY.json').write_text(json.dumps(dict(contracts=CONTRACTS, ticks=dataset(), source='TEST_ARCHIVE')))
    client.app.state.backtest_runner.data_source = LocalHistoricalDataSource(tmp_path)
    result = client.post('/backtests/run', json=payload).json()
    assert result['status'] == 'COMPLETED', result
    assert result['data_source'] == 'TEST_ARCHIVE'


def test_banknifty_date_levels_contract_and_lot_size(client):
    symbol = 'TEST-BANKNIFTY-59900-CE'
    result = client.post('/backtests/run', json=dict(trading_date=DATE, instrument='BANKNIFTY', levels=[60000],
        contracts=[dict(instrument='BANKNIFTY', expiry='2026-09-30', strike=59900, option_type='CE', symbol=symbol, lot_size=30)],
        dataset=[tick('10:00:00', 'BANKNIFTY', 60100), tick('10:01:00', 'BANKNIFTY', 60000),
                 tick('10:01:01', symbol, 200), tick('10:02:00', symbol, 180)])).json()
    assert result['status'] == 'COMPLETED', result
    assert result['trades'][0]['quantity'] == 30
    assert result['trades'][0]['strike'] == 59900
    assert result['gross_pnl'] == -600
    assert result['max_drawdown'] == 600
    assert result['total_return_percent'] == -10
    assert result['average_return_percent'] == -10
    assert result['best_trade'] == result['worst_trade'] == -600


def test_entry_cutoff_boundary_is_shared(client):
    result = run(client, dataset(), new_trade_cutoff_time='10:01:02')
    assert result['trades'][0]['entry_time'] == f'{DATE}T10:01:01+05:30'
    result = run(client, dataset(), new_trade_cutoff_time='10:01:00')
    assert result['total_trades'] == 0
    assert result['entry_results'][0]['failure_reason'] == 'NEW_TRADE_CUTOFF_REACHED'


def test_utc_timestamps_use_historical_kolkata_date(client):
    from datetime import timezone
    rows = [{**row, 'timestamp': datetime.fromisoformat(row['timestamp']).astimezone(timezone.utc).isoformat()}
            for row in dataset([('10:02:00', 90)])]
    result = run(client, rows)
    assert result['trades'][0]['expiry'] == '2026-09-17'
    assert result['trades'][0]['entry_price'] == 100
    assert result['levels'][0]['level_date'] == DATE


def test_summary_realised_equity_drawdown_and_breakeven_denominator():
    from types import SimpleNamespace
    from app.backtest_summary import backtest_summary
    trades = [SimpleNamespace(trade_id=i, status='CLOSED', realised_pnl=pnl,
        realised_pnl_percentage=pnl / 10, entry_price=100, quantity=10,
        exit_time=datetime.fromisoformat(f'{DATE}T10:{i:02d}:00+05:30'))
        for i, pnl in enumerate([100, -60, -50, 0, 200], 1)]
    summary = backtest_summary(list(reversed(trades)))
    assert summary['win_rate'] == 40
    assert summary['gross_pnl'] == summary['net_pnl'] == 190
    assert summary['max_drawdown'] == 110
    assert summary['total_return_percent'] == 3.8
    assert summary['average_return_percent'] == 3.8
    assert summary['average_pnl'] == 38
    assert summary['profit_factor'] == pytest.approx(300 / 110)
    assert summary['best_trade'] == 200
    assert summary['worst_trade'] == -60


def test_exits_pass_through_backtest_execution_model(client, monkeypatch):
    from app.backtest_executor import BacktestExecutor
    seen = []
    original = BacktestExecutor.exit_price

    def observe(self, trade, price, timestamp, reason):
        seen.append((price, timestamp.isoformat(), reason))
        return original(self, trade, price, timestamp, reason)

    monkeypatch.setattr(BacktestExecutor, 'exit_price', observe)
    result = run(client, dataset([('10:02:00', 85)]))
    assert seen == [(85, f'{DATE}T10:02:00+05:30', 'STOP_LOSS')]
    assert result['trades'][0]['exit_price'] == 85
