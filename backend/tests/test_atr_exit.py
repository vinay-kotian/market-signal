"""ATR eligibility, shared PAPER/BACKTEST protection and selection regressions."""
import asyncio
import csv
import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.atr_data import AtrCandle, AtrData, ZerodhaAtrData, wilder_atr
from app.database import connect, initialize_database
from app.exit_settings import AtrSettings
from app.exit_strategies import AtrExit
from app.main import create_app
from test_position_monitor import enter, tick
from test_backtests import CONTRACTS, SYMBOL, dataset, run

NOW = datetime(2026, 9, 14, 4, 30, tzinfo=timezone.utc)


def candles(symbol, end=NOW, count=14, spread=4, available_at=None):
    return [AtrCandle(symbol=symbol, timestamp=end-timedelta(minutes=5*(count-i)),
        available_at=available_at, open=100, high=100+spread/2, low=100-spread/2, close=100) for i in range(count)]


def configure(client, **values):
    original = client.get('/settings/exit-strategy').json()['configuration']
    response = client.put('/settings/exit-strategy', json={**original, **values})
    assert response.status_code == 200, response.text
    return response.json()


def warmup(app):
    app.state.atr_data.cache([c for contract in app.state.paper_executor.instruments.contracts('NIFTY') for c in candles(contract.symbol)])
    app.state.atr_data.cache(candles('NIFTY', spread=20))


def test_wilder_true_range_and_smoothing():
    rows = [dict(high=12, low=8, close=10), dict(high=15, low=11, close=12), dict(high=13, low=11, close=12), dict(high=14, low=10, close=11)]
    assert wilder_atr(rows[:2], 3) is None
    assert wilder_atr(rows[:3], 3) == pytest.approx(11/3)
    assert wilder_atr(iter(rows), 3) == pytest.approx((11/3*2+4)/3)


def test_candle_completion_availability_and_source_isolation(tmp_path):
    path = tmp_path/'atr.sqlite3'; initialize_database(path)
    data = AtrData(path, 'BACKTEST'); data.cache(candles('OPTION'))
    assert data.value('OPTION', NOW-timedelta(microseconds=1), 14)['value'] is None
    assert data.value('OPTION', NOW, 14)['value'] == 4
    assert AtrData(path, 'ZERODHA').value('OPTION', NOW, 14)['value'] is None
    data.cache(candles('OPTION', end=NOW+timedelta(minutes=5), count=1, spread=100))
    assert data.value('OPTION', NOW, 14)['value'] == 4
    assert data.value('OPTION', NOW+timedelta(minutes=5), 14)['value'] == pytest.approx(76/7)
    data.cache(candles('LATE', available_at=NOW+timedelta(minutes=1)))
    assert data.value('LATE', NOW, 14)['value'] is None
    assert data.value('LATE', NOW+timedelta(minutes=1), 14)['value'] == 4
    data.observe('OPTION', 1000, NOW-timedelta(minutes=1))
    assert data.value('OPTION', NOW, 14)['value'] == 4


def test_recorded_tick_buckets_require_completed_candles(tmp_path):
    path = tmp_path/'ticks.sqlite3'; initialize_database(path)
    data = AtrData(path, 'SIMULATED')
    for c in candles('OPTION'):
        data.observe('OPTION', 98, c.timestamp)
        data.observe('OPTION', 102, c.timestamp+timedelta(minutes=4))
    assert data.value('OPTION', NOW, 14)['value'] == 4
    data.observe('OPTION', 500, NOW)
    assert data.value('OPTION', NOW, 14)['value'] == 4


@pytest.mark.parametrize('values', [dict(atr_period=0), dict(atr_period=1.5), dict(atr_timeframe='minute'), dict(atr_initial_multiplier=0),
    dict(atr_trailing_mode='OTHER'), dict(atr_max_sl_percent=100), dict(atr_breakeven_activation_mode='OTHER'),
    dict(atr_breakeven_activation_threshold=0), dict(atr_breakeven_activation_mode='PERCENTAGE', atr_breakeven_lock_percent=2)])
def test_invalid_configuration_rejected(client, values):
    original = client.get('/settings/exit-strategy').json()['configuration']
    assert client.put('/settings/exit-strategy', json={**original, **values}).status_code == 422


@pytest.mark.parametrize('atr,values,reason', [(None, {}, 'OPTION_ATR_UNAVAILABLE'), (0, {}, 'OPTION_ATR_UNAVAILABLE'),
    (80, {}, 'ATR_STOP_INVALID'), (11, {}, 'ATR_MAX_SL_EXCEEDED'),
    (1, dict(atr_breakeven_activation_mode='ATR', atr_breakeven_lock_percent=2), 'ATR_BREAKEVEN_CONFIGURATION_INVALID')])
def test_invalid_risk_skips_instead_of_fallback(atr, values, reason):
    with pytest.raises(ValueError, match=reason): AtrExit().initial_stop(100, AtrSettings(**values).model_dump(), atr)


def test_initial_formula_and_optional_guard():
    assert AtrExit().initial_stop(100, AtrSettings().model_dump(), 10) == 85
    assert AtrExit().initial_stop(100, AtrSettings(atr_max_sl_percent=None).model_dump(), 20) == 70


def test_snapshot_filters_csv_and_disable_does_not_change_open_atr(tmp_path, monkeypatch):
    monkeypatch.setenv('EXTERNAL_LEVELS_API_KEY', 'test-secret')
    path = tmp_path/'paper.sqlite3'; app = create_app(path)
    with TestClient(app) as client:
        configure(client, default_exit_strategy='ATR'); warmup(app); trade = enter(client)
        assert trade['strategy_type'] == 'ATR'
        assert trade['option_atr_at_entry'] == 4 and trade['index_atr_at_entry'] == 20
        assert trade['initial_stop_loss'] == 94 and trade['initial_risk_per_unit'] == 6
        assert trade['initial_risk_amount'] == 60 and trade['initial_risk_percent'] == 6
        frozen = trade['strategy_config_snapshot']
        configure(client, atr_enabled=False, default_exit_strategy='LEGACY', atr_initial_multiplier=10)
        tick(client, trade['option_symbol'], 110)
        active = client.get('/trades').json()[0]
        assert active['current_stop_loss'] == 94 and active['strategy_config_snapshot'] == frozen
        assert client.get('/watchlist/options').json()[0]['strategy_type'] == 'ATR'
        assert client.get('/trades/history?strategy_type=ATR').json()['total'] == 1
        assert client.get('/trades/history?strategy_type=LEGACY').json()['total'] == 0
        assert client.get('/reports/paper-trading?strategy_type=LEGACY').json()['total_trades'] == 0
        assert client.get('/trades/history/ids?strategy_type=ATR').json() == [trade['trade_id']]
        tick(client, trade['option_symbol'], 93); closed = client.get('/trades').json()[0]
        assert closed['status'] == 'CLOSED' and closed['exit_reason'] == 'STOP_LOSS' and closed['realised_pnl'] == -70
        assert closed['strategy_config_snapshot'] == frozen
        response = client.get('/reports/export?from_date=2026-09-14&strategy_type=ATR', headers={'X-API-Key': 'test-secret'})
        assert response.status_code == 200, response.text
        row, = list(csv.DictReader(io.StringIO(response.text)))
        assert row['strategy_type'] == 'ATR' and float(row['option_atr_at_entry']) == 4
    with TestClient(create_app(path)) as client: assert client.get('/trades').json()[0]['strategy_config_snapshot'] == frozen


@pytest.mark.parametrize('mode,settings,stop', [('OFF', {}, 94), ('PERCENTAGE', {'atr_trailing_percentage': 5}, 114),
    ('ATR', {'atr_trailing_multiplier': 2}, 112),
    ('OFF', {'atr_breakeven_activation_mode': 'PERCENTAGE', 'atr_breakeven_activation_threshold': 10}, 100),
    ('OFF', {'atr_breakeven_activation_mode': 'ATR', 'atr_breakeven_activation_threshold': 2, 'atr_breakeven_lock_percent': 1}, 101),
    ('OFF', {'atr_breakeven_activation_mode': 'R', 'atr_breakeven_activation_threshold': 2}, 100)])
def test_independent_protection_monotonic_frozen_atr(tmp_path, mode, settings, stop):
    app = create_app(tmp_path/'protect.sqlite3')
    with TestClient(app) as client:
        configure(client, default_exit_strategy='ATR', atr_trailing_mode=mode, **settings); warmup(app); trade = enter(client)
        tick(client, trade['option_symbol'], 120)
        assert client.get('/trades').json()[0]['current_stop_loss'] == stop
        app.state.atr_data.cache(candles(trade['option_symbol'], spread=50))
        tick(client, trade['option_symbol'], max(stop+.1, 115))
        assert client.get('/trades').json()[0]['current_stop_loss'] == stop
        tick(client, trade['option_symbol'], stop)
        assert client.get('/trades').json()[0]['status'] == 'CLOSED'


def test_missing_atr_records_failure_keeps_override(client):
    from test_paper_trades import add_level, publish
    client.put('/settings/exit-strategy/next-trade/NIFTY', json={'strategy': 'ATR'})
    add_level(client); publish(client, [24900, 25000])
    assert client.get('/trades').json() == []
    assert client.get('/trade-entry-results').json()[0]['failure_reason'] == 'OPTION_ATR_UNAVAILABLE'
    assert client.get('/settings/exit-strategy').json()['next_trade_overrides']['NIFTY'] == 'ATR'


def test_selection_priority_ist_rollover_disable_and_explicit_override(tmp_path):
    moment = [NOW]; path = tmp_path/'daily.sqlite3'; app = create_app(path, clock=lambda: moment[0])
    with TestClient(app) as client:
        client.put('/settings/exit-strategy/daily', json={'trading_date': '2026-09-14', 'default_exit_strategy': 'ATR'})
        assert client.get('/settings/exit-strategy').json()['effective']['NIFTY'] == 'ATR'
        configure(client, instrument_overrides={'NIFTY': 'LEGACY'})
        assert client.get('/settings/exit-strategy').json()['effective']['NIFTY'] == 'LEGACY'
        client.put('/settings/exit-strategy/daily', json={'trading_date': '2026-09-14', 'instrument_overrides': {'NIFTY': 'ATR'}})
        assert client.get('/settings/exit-strategy').json()['effective']['NIFTY'] == 'ATR'
        client.put('/settings/exit-strategy/next-trade/NIFTY', json={'strategy': 'LEGACY'})
        assert client.get('/settings/exit-strategy').json()['effective']['NIFTY'] == 'LEGACY'
        with connect(path) as connection: assert app.state.exit_settings.resolve('NIFTY', NOW, connection, 'ATR')[0] == 'ATR'
        moment[0] = datetime(2026, 9, 14, 18, 30, tzinfo=timezone.utc)
        rolled = client.get('/settings/exit-strategy').json()
        assert rolled['daily']['trading_date'] == '2026-09-15'
        assert rolled['effective']['NIFTY'] == 'LEGACY' and not rolled['next_trade_overrides']
        configure(client, atr_enabled=False)
        assert client.put('/settings/exit-strategy/daily', json={'trading_date': '2026-09-15', 'default_exit_strategy': 'ATR'}).status_code == 422
        assert client.put('/settings/exit-strategy/next-trade/NIFTY', json={'strategy': 'ATR'}).status_code == 422
        original = client.get('/settings/exit-strategy').json()['configuration']
        assert client.put('/settings/exit-strategy', json={**original, 'default_exit_strategy': 'ATR'}).status_code == 422


def test_success_consumes_override_and_current_configuration_persists(tmp_path):
    path = tmp_path/'once.sqlite3'; app = create_app(path)
    with TestClient(app) as client:
        warmup(app); client.put('/settings/exit-strategy/next-trade/NIFTY', json={'strategy': 'ATR'})
        assert enter(client)['strategy_type'] == 'ATR'
        assert client.get('/settings/exit-strategy').json()['next_trade_overrides'] == {}
        current = client.get('/settings/exit-strategy/legacy').json(); saved = {**current, 'stop_strategy': 'LEGACY', 'stop_loss_percentage': 12}
        assert client.put('/settings/exit-strategy/legacy', json=saved).status_code == 200
    with TestClient(create_app(path)) as client:
        assert client.get('/settings/exit-strategy/legacy').json() == saved
        current = client.get('/settings/protection').json(); client.put('/settings/protection', json={**current, 'initial_stop_loss_pct': 13})
    with TestClient(create_app(path)) as client:
        assert client.get('/settings/exit-strategy/legacy').json()['initial_stop_loss_pct'] == 13
        assert client.get('/settings/exit-strategy/legacy').json()['stop_strategy'] == 'PROGRESSIVE'


def test_atr_mandatory_time_exit(tmp_path):
    moment = [NOW]; app = create_app(tmp_path/'time.sqlite3', clock=lambda: moment[0])
    with TestClient(app) as client:
        warmup(app); configure(client, default_exit_strategy='ATR'); trade = enter(client)
        moment[0] = datetime(2026, 9, 14, 9, 57, tzinfo=timezone.utc); tick(client, trade['option_symbol'], 100)
        closed = client.get('/trades').json()[0]
        assert closed['status'] == 'CLOSED' and closed['exit_reason'] == 'MARKET_CLOSE'


def test_backtest_same_data_comparison_and_costs(client):
    warm = [c.model_dump(mode='json') for c in candles(SYMBOL)]
    warm += [c.model_dump(mode='json') for c in candles(SYMBOL, end=NOW+timedelta(minutes=5), count=1, spread=100)]
    result = run(client, dataset([('10:02:00', 92)]), exit_strategy='ATR', candles=warm, transaction_cost_per_order=2)
    trade, = result['trades']
    assert trade['strategy_type'] == 'ATR' and trade['initial_stop_loss'] == 94 and trade['option_atr_at_entry'] == 4
    assert result['gross_pnl'] == -80 and result['net_pnl'] == -84 and result['transaction_costs'] == 4
    assert result['sl_hits'] == 1 and result['average_r'] == pytest.approx(-1.4) and result['max_drawdown'] == 84
    response = client.post('/backtests/compare', json=dict(trading_date='2026-09-14', instrument='NIFTY', levels=[25000], contracts=CONTRACTS, dataset=dataset([('10:02:00', 92)]), candles=warm))
    assert response.status_code == 201, response.text
    comparison = response.json()['runs']
    assert len(comparison) == 7 and len({r['dataset_hash'] for r in comparison}) == 1
    assert [r['multiplier'] for r in comparison[1:]] == [1, 1.25, 1.5, 1.75, 2, 2.5]
    assert all(r['status'] == 'COMPLETED' for r in comparison)
    assert [r['sl_hits'] for r in comparison] == [0, 1, 1, 1, 1, 1, 0]
    for row in comparison:
        saved = client.get(f"/backtests/{row['id']}").json()
        assert saved['settings_snapshot']['exit_strategy'] == row['strategy']
        expected = 100-4*row['multiplier'] if row['strategy'] == 'ATR' else 90
        assert saved['trades'][0]['initial_stop_loss'] == expected
    assert client.get('/trades').json() == []


def test_backtest_missing_history(client):
    result = run(client, exit_strategy='ATR')
    assert result['total_trades'] == 0 and result['entry_results'][0]['failure_reason'] == 'OPTION_ATR_UNAVAILABLE'


def test_zerodha_read_only_completed_option_index_atr(tmp_path):
    path = tmp_path/'kite.sqlite3'; initialize_database(path); calls = []
    class Connector:
        async def historical_candles(self, token, start, end, interval):
            assert end.hour == 10 and end.utcoffset() == timedelta(hours=5, minutes=30)
            assert start == end-timedelta(days=10)
            calls.append((token, interval))
            return [[c.timestamp.isoformat(), c.open, c.high, c.low, c.close] for c in candles('ANY', count=15, end=NOW+timedelta(minutes=5), spread=4 if token == 1 else 20)]
    instruments = SimpleNamespace(option=lambda _: SimpleNamespace(instrument_token=1), index=lambda _: SimpleNamespace(instrument_token=2))
    data = ZerodhaAtrData(path, instruments, Connector(), lambda: NOW)
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(data.prepare('OPTION', 'NIFTY'))
        loop.run_until_complete(data.prepare('OPTION', 'NIFTY'))
    finally:
        loop.close()
    assert calls == [(1, '5minute'), (2, '5minute')]
    assert data.value('OPTION', NOW, 14)['value'] == 4 and data.value('NIFTY', NOW, 14)['value'] == 20


@pytest.mark.parametrize('changes', [{'atr_initial_multiplier': 20}, {'atr_enabled': False}])
def test_atr_risk_rejection_is_recorded_at_entry(tmp_path, changes):
    from test_paper_trades import add_level, publish
    app = create_app(tmp_path/'reject.sqlite3')
    with TestClient(app) as client:
        warmup(app)
        configure(client, default_exit_strategy='ATR')
        configure(client, **changes)
        add_level(client); publish(client, [24900, 25000])
        assert client.get('/trades').json() == []
        reason = 'ATR_STRATEGY_DISABLED' if 'atr_enabled' in changes else 'ATR_MAX_SL_EXCEEDED'
        assert client.get('/trade-entry-results').json()[0]['failure_reason'] == reason


def test_explicit_trade_override_precedes_instrument_and_daily(client, monkeypatch):
    app = client.app
    warmup(app)
    configure(client, default_exit_strategy='ATR', instrument_overrides={'NIFTY': 'ATR'})
    execute = app.state.paper_executor.execute
    monkeypatch.setattr(app.state.paper_executor, 'execute', lambda *args, **kwargs:
        execute(*args, **kwargs, exit_strategy_override='LEGACY'))
    trade = enter(client)
    assert trade['strategy_type'] == 'LEGACY' and trade['initial_stop_loss'] == 90
    configure(client, atr_initial_multiplier=20, default_exit_strategy='ATR')
    tick(client, trade['option_symbol'], 110)
    updated = client.get('/trades').json()[0]
    assert updated['strategy_type'] == 'LEGACY' and updated['profit_lock_activated']
    assert updated['strategy_config_snapshot'] == trade['strategy_config_snapshot']


def test_current_cross_field_validation_returns_422(client):
    current = client.get('/settings/exit-strategy/legacy').json()
    response = client.put('/settings/exit-strategy/legacy', json={**current, 'profit_lock_pct': 20})
    assert response.status_code == 422
    assert client.get('/settings/exit-strategy/legacy').json() == current
