from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import create_app
from app.settings import TradeSettings, TradingTimeConfiguration
from app.trading_time import TradingTimeRules
from test_trading_time import Clock, enter
from test_paper_trades import publish
from test_backtests import dataset, run, post, tick, DATE

DEFAULT = dict(market_open_time='09:15:00', market_close_time='15:30:00',
    entry_block_after_open_minutes=10, entry_block_before_close_minutes=10,
    mandatory_exit_before_close_minutes=3)


def config(client, **changes):
    response = client.put('/settings/trading-time', json={**DEFAULT, **changes})
    assert response.status_code == 200, response.text
    return response.json()


def test_defaults_and_persisted_settings_override_environment_after_restart(tmp_path, monkeypatch):
    path = tmp_path / 'time.sqlite3'
    with TestClient(create_app(path)) as client:
        initial = client.get('/settings/trading-time').json()
        assert initial['configuration'] == DEFAULT
        assert initial['timezone'] == 'Asia/Kolkata'
        assert initial['windows'] == dict(entry_allowed_from='09:25:00', entry_allowed_until='15:20:00', mandatory_exit_starts='15:27:00')
        saved = config(client, market_open_time='09:00', market_close_time='16:00',
                       entry_block_after_open_minutes=20, entry_block_before_close_minutes=15, mandatory_exit_before_close_minutes=5)
        assert saved['windows'] == dict(entry_allowed_from='09:20:00', entry_allowed_until='15:45:00', mandatory_exit_starts='15:55:00')
    monkeypatch.setenv('MARKET_OPEN_TIME', '08:00')
    with TestClient(create_app(path)) as client:
        assert client.get('/settings/trading-time').json() == saved
        executor = client.app.state.paper_executor
        assert executor.time_rules is client.app.state.position_monitor.time_rules is client.app.state.market_close.rules
        assert executor.time_rules.settings.trading_start_time.isoformat() == '09:20:00'


@pytest.mark.parametrize('changes,message', [
    ({'market_open_time': '15:30'}, 'opening time'),
    ({'market_close_time': '09:00'}, 'opening time'),
    ({'entry_block_after_open_minutes': -1}, 'greater than or equal'),
    ({'entry_block_before_close_minutes': -1}, 'greater than or equal'),
    ({'entry_block_after_open_minutes': 365}, 'positive entry window'),
    ({'mandatory_exit_before_close_minutes': 0}, 'greater than'),
    ({'mandatory_exit_before_close_minutes': 375}, 'after market open'),
    ({'mandatory_exit_before_close_minutes': 11}, 'entry cutoff'),
    ({'market_open_time': '09:15+05:30'}, 'without offsets'),
    ({'market_close_time': 'bad'}, 'valid time'),
    ({'entry_block_before_close_minutes': 'NaN'}, 'finite number'),
])
def test_invalid_configuration_cannot_change_saved_or_running_settings(client, changes, message):
    before = client.get('/settings/trading-time').json()
    response = client.put('/settings/trading-time', json={**DEFAULT, **changes})
    assert response.status_code == 422
    assert message in response.text
    assert client.get('/settings/trading-time').json() == before
    assert client.app.state.market_close.rules.settings.new_trade_cutoff_time.isoformat() == '15:20:00'


@pytest.mark.parametrize('timestamp,reason', [
    ('2026-09-14T03:54:59.999999+00:00', 'BEFORE_TRADING_START'),
    ('2026-09-14T03:55:00+00:00', None),
    ('2026-09-14T09:49:59.999999+00:00', None),
    ('2026-09-14T09:50:00+00:00', 'NEW_TRADE_CUTOFF_REACHED'),
])
def test_default_exact_ist_boundaries(timestamp, reason):
    assert TradingTimeRules(TradeSettings()).entry_rejection(datetime.fromisoformat(timestamp)) == reason


def test_dynamic_entry_and_exit_boundaries():
    settings = TradeSettings(market_open_time='10:00', market_close_time='14:00',
        entry_block_after_open_minutes=30, entry_block_before_close_minutes=20, mandatory_exit_before_close_minutes=5)
    rules = TradingTimeRules(settings)
    for value, rejection in [('10:29:59.999999', 'BEFORE_TRADING_START'), ('10:30:00', None),
                             ('13:39:59.999999', None), ('13:40:00', 'NEW_TRADE_CUTOFF_REACHED')]:
        timestamp = datetime.fromisoformat(f'2026-09-14T{value}+05:30')
        assert rules.entry_rejection(timestamp) == rejection
    class Trade:
        entry_time = datetime.fromisoformat('2026-09-14T10:30:00+05:30')
    assert not rules.exit_due(Trade(), datetime.fromisoformat('2026-09-14T13:54:59.999999+05:30'))
    assert rules.exit_due(Trade(), datetime.fromisoformat('2026-09-14T13:55:00+05:30'))


def test_saved_configuration_updates_entries_scheduler_and_monitor_without_changing_risk(tmp_path):
    clock = Clock()
    with TestClient(create_app(tmp_path / 'time.sqlite3', clock=clock)) as client:
        trade, = enter(client)
        risk = client.app.state.paper_executor.settings.initial_stop_loss_pct
        config(client, market_close_time='10:30', entry_block_before_close_minutes=10, mandatory_exit_before_close_minutes=3)
        assert client.app.state.paper_executor.settings.initial_stop_loss_pct == risk
        clock.set('2026-09-14T10:20:00')
        publish(client, [105], trade['option_symbol'])
        assert client.get('/trades').json()[0]['status'] == 'OPEN'
        clock.set('2026-09-14T10:27:00')
        publish(client, [106], trade['option_symbol'])
        closed = client.get('/trades').json()[0]
        assert closed['exit_reason'] == 'MARKET_CLOSE'
        assert closed['exit_price'] == 106
        events = client.get(f"/trades/{trade['trade_id']}/events").json()
        client.portal.call(client.app.state.market_close.check)
        publish(client, [80], trade['option_symbol'])
        assert client.get('/trades').json()[0] == closed
        assert client.get(f"/trades/{trade['trade_id']}/events").json() == events


def test_save_earlier_deadline_closes_existing_position_once(tmp_path):
    clock = Clock()
    with TestClient(create_app(tmp_path / 'time.sqlite3', clock=clock)) as client:
        trade, = enter(client)
        publish(client, [105], trade['option_symbol'])
        clock.set('2026-09-14T10:28:00')
        config(client, market_close_time='10:30')
        closed, = client.get('/trades').json()
        assert closed['exit_reason'] == 'MARKET_CLOSE'
        assert closed['exit_price'] == 105
        config(client, market_close_time='10:30')
        assert client.get('/trades').json() == [closed]
        kinds = [event['event_type'] for event in client.get(f"/trades/{trade['trade_id']}/events").json()]
        assert kinds.count('MARKET_CLOSING_EXIT_TRIGGERED') == kinds.count('POSITION_CLOSED') == 1


def test_blocked_signal_is_consumed_not_queued_and_monitoring_continues(tmp_path):
    clock = Clock('2026-09-14T09:24:59')
    with TestClient(create_app(tmp_path / 'time.sqlite3', clock=clock)) as client:
        assert enter(client) == []
        assert client.get('/trade-entry-results').json()[0]['failure_reason'] == 'BEFORE_TRADING_START'
        assert client.get('/signals').json()[0]['valid'] is True
        assert client.get('/option-selections').json()[0]['status'] == 'SELECTED'
        clock.set('2026-09-14T09:25:00')
        publish(client, [25000])
        assert client.get('/trades').json() == []
        # A fresh approach can rearm and create a new, independently evaluated signal.
        publish(client, [24900, 25000])
        assert len(client.get('/trades').json()) == 1


def test_quote_fetch_cannot_defer_an_early_signal_into_allowed_window(tmp_path):
    from app.option_prices import SimulatedOptionPrices
    from app.option_instruments import SimulatedOptionInstrumentSource
    clock = Clock('2026-09-14T09:24:59')
    instruments = SimulatedOptionInstrumentSource(clock().date())
    prices = SimulatedOptionPrices.seeded(instruments)
    async def prepare(symbol):
        clock.set('2026-09-14T09:25:00')
    prices.prepare = prepare
    with TestClient(create_app(tmp_path / 'time.sqlite3', clock=clock, option_source=instruments, option_prices=prices)) as client:
        assert enter(client) == []
        assert client.get('/trade-entry-results').json()[0]['failure_reason'] == 'BEFORE_TRADING_START'


def test_backtest_uses_saved_time_snapshot_and_results_keep_it(client):
    saved = config(client, market_close_time='16:00', entry_block_after_open_minutes=20,
                   entry_block_before_close_minutes=15, mandatory_exit_before_close_minutes=5)
    result = run(client, dataset([('15:55:00', 105)], close=False))
    for key, value in saved['configuration'].items():
        assert result['settings_snapshot'][key] == value
        assert result['trades'][0]['settings_snapshot'][key] == value
    assert result['trades'][0]['exit_reason'] == 'MARKET_CLOSE'
    assert result['trades'][0]['exit_time'] == f'{DATE}T15:55:00+05:30'
    config(client, market_close_time='15:30')
    assert client.get('/backtests/' + result['id']).json() == result


def test_running_backtest_is_isolated_from_settings_change(client, monkeypatch):
    from app.historical_market_data import HistoricalMarketDataProvider
    original = HistoricalMarketDataProvider.replay
    captured = {}
    async def change_settings(self, records, advance):
        state = client.app.state
        captured['before'] = state.paper_executor.settings
        # Simulate another settings request while a replay has already captured its config.
        with connect(state.database_path) as connection:
            data = TradingTimeConfiguration(market_close_time='14:00')
            connection.execute('INSERT INTO trading_time_settings VALUES (1, ?)', (data.model_dump_json(),))
        state.paper_executor.settings = state.paper_executor.settings.model_copy(update=data.model_dump())
        state.paper_executor.time_rules.settings = state.paper_executor.settings
        return await original(self, records, advance)
    monkeypatch.setattr(HistoricalMarketDataProvider, 'replay', change_settings)
    result = run(client)
    assert client.get('/settings/trading-time').json()['windows']['mandatory_exit_starts'] == '13:57:00'
    assert result['settings_snapshot']['market_close_time'] == '15:30:00'
    assert result['trades'][0]['exit_time'] == f'{DATE}T15:27:05+05:30'
    assert result['trades'][0]['exit_reason'] == 'MARKET_CLOSE'


def test_backtest_does_not_queue_early_signal_and_expires_delayed_fill_at_cutoff(client):
    result = run(client, dataset(entry=False), entry_block_after_open_minutes=47)
    assert result['total_trades'] == 0
    assert result['entry_results'][0]['failure_reason'] == 'BEFORE_TRADING_START'
    # The signal is valid at 10:01, but its first option quote is at the exclusive cutoff.
    result = run(client, dataset(entry=False), entry_block_before_close_minutes=328.98333333333335)
    assert result['total_trades'] == 0
    assert result['entry_results'][0]['failure_reason'] == 'NEW_TRADE_CUTOFF_REACHED'


def test_partial_backtest_overrides_validate_against_saved_market_session(client):
    config(client, market_open_time='08:00', market_close_time='16:00')
    # 09:00 would be before the default opening time, but is valid with saved 08:00.
    result = run(client, [tick('08:30:00', 'NIFTY', 24900)], market_close_time='09:00')
    assert result['settings_snapshot']['market_open_time'] == '08:00:00'
    assert result['settings_snapshot']['market_close_time'] == '09:00:00'
    assert result['total_trades'] == 0
    # Legacy absolute overrides are converted relative to the captured session.
    result = run(client, dataset([('15:57:00', 100)]), new_trade_cutoff_time='15:40')
    assert result['settings_snapshot']['entry_block_before_close_minutes'] == 20
    assert result['settings_snapshot']['market_close_time'] == '16:00:00'


@pytest.mark.parametrize('index_settings', [None, [], 'invalid'])
def test_backtest_overrides_are_validated_before_replay(client, index_settings):
    response = post(client, index_settings=index_settings)
    assert response.status_code == 422
    assert 'index_settings' in response.text
