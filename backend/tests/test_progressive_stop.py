import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.database import connect, initialize_database
from app.main import create_app
from app.progressive_stop import ProgressiveSettings, progressive_stop
from app.settings import TradeSettings
from test_trailing_stop import enter, send, events
from test_backtests import dataset, run


@pytest.mark.parametrize('price,pct,stop', [
    (95, None, 90), (100, None, 90), (105, None, 90), (109, None, 90),
    (109.99, None, 90), (110, 10, 105), (115, 10, 105),
    (119.99, 10, 107.991), (120, 9, 109.2), (130, 8, 119.6),
    (140, 7, 130.2), (145, 7, 134.85), (150, 6, 141), (160, 5, 152),
    (170, 5, 161.5), (200, 5, 190),
])
def test_requested_examples(price, pct, stop):
    state = progressive_stop(100, 100, price, 90, False, ProgressiveSettings())
    assert state.stop == Decimal(str(stop))
    assert state.trailing_pct == (Decimal(str(pct)) if pct is not None else None)


def test_monotonic_and_custom_reference():
    settings = ProgressiveSettings()
    highest, stop, active = 100, 90, False
    for price in [100, 110, 130, 125, 140, 132]:
        state = progressive_stop(100, highest, price, stop, active, settings)
        assert state.stop >= stop
        highest, stop, active = state.highest, state.stop, state.activated
    assert highest == 140 and stop == Decimal('130.2')
    settings = ProgressiveSettings(profit_lock_trigger_pct=20, profit_lock_pct=8,
        trailing_start_pct=12, trailing_reduction_step_points=2.5,
        trailing_reduction_pct=0.5, minimum_trailing_pct=3)
    state = progressive_stop(50, 50, 65, 45, False, settings)
    assert state.step == 2 and state.trailing_pct == 11
    assert state.stop == Decimal('57.85')


@pytest.mark.parametrize('changes', [
    {'initial_stop_loss_pct': 0}, {'initial_stop_loss_pct': 100},
    {'profit_lock_trigger_pct': 0}, {'profit_lock_pct': -1}, {'profit_lock_pct': 10},
    {'trailing_start_pct': 0}, {'trailing_reduction_step_points': 0},
    {'trailing_reduction_pct': 0}, {'minimum_trailing_pct': 0}, {'minimum_trailing_pct': 11},
    {'trailing_start_pct': float('inf')},
])
def test_validation(changes):
    with pytest.raises(ValidationError):
        TradeSettings(**changes)


@pytest.mark.parametrize('prices,reason,stop', [
    ([95, 90], 'STOP_LOSS', 90), ([110, 105], 'TRAILING_STOP_LOSS', 105),
    ([150, 140], 'TRAILING_STOP_LOSS', 141), ([200, 185], 'TRAILING_STOP_LOSS', 190),
    ([100, 110, 130, 125, 140, 132, 130.2], 'TRAILING_STOP_LOSS', 130.2),
])
def test_paper_backtest_parity(client, prices, reason, stop):
    trade = enter(client)
    for price in prices:
        current = send(client, trade, price)
    assert current['status'] == 'CLOSED'
    assert current['exit_reason'] == reason
    assert current['current_stop_loss'] == stop
    history = events(client, trade)
    assert send(client, trade, 999) == current
    assert events(client, trade) == history
    result = run(client, dataset([(f'10:{i+2:02d}:00', p) for i, p in enumerate(prices)]))
    replay, = result['trades']
    for field in ['highest_price', 'current_stop_loss', 'trailing_pct', 'trailing_step',
                  'profit_lock_activated', 'exit_price', 'exit_reason', 'realised_pnl']:
        assert replay[field] == current[field]
    assert [e['event_type'] for e in result['events'][str(replay['trade_id'])]] == [e['event_type'] for e in history]


def test_settings_restart_snapshot_and_history(tmp_path):
    path = tmp_path / 'settings.db'
    with TestClient(create_app(path)) as client:
        trade = enter(client)
        state = send(client, trade, 120)
        history = events(client, trade)
        assert send(client, trade, 120) == state
        assert events(client, trade) == history
        assert state['stop_updated_at'] is not None
        assert sum(e['event_type'] == 'PROFIT_LOCK_ACTIVATED' for e in history) == 1
        step = next(e for e in history if e['event_type'] == 'TRAILING_STEP_CHANGED')
        assert (step['trailing_step'], step['trailing_pct'], step['highest_price']) == (1, 9, 120)
        saved = client.get('/settings/protection').json()
        saved.update(profit_lock_pct=2, initial_stop_loss_pct=20)
        assert client.put('/settings/protection', json=saved).status_code == 200
        assert client.put('/settings/protection', json={**saved, 'profit_lock_pct': 11}).status_code == 422
    with TestClient(create_app(path)) as client:
        assert client.get('/settings/protection').json() == saved
        assert send(client, trade, 115) == state
        assert events(client, trade) == history
        assert send(client, trade, 109.2)['exit_reason'] == 'TRAILING_STOP_LOSS'
        new = enter(client)
        assert new['initial_stop_loss'] == pytest.approx(109.2 * .8)
        assert new['settings_snapshot']['profit_lock_pct'] == 2


def test_legacy_snapshot_remains_legacy_and_migration_is_repeatable(tmp_path):
    path = tmp_path / 'legacy.db'
    with TestClient(create_app(path, trade_settings=TradeSettings(stop_strategy='LEGACY'))) as client:
        trade = enter(client)
        state = send(client, trade, 105)
        with connect(path) as connection:
            snapshot = dict(state['settings_snapshot'])
            for key in ['stop_strategy', *ProgressiveSettings.model_fields]:
                snapshot.pop(key, None)
            connection.execute('UPDATE trades SET settings_snapshot = ?', (json.dumps(snapshot),))
            for name in ['profit_lock_activated', 'trailing_pct', 'trailing_step', 'stop_updated_at']:
                connection.execute(f'ALTER TABLE trades DROP COLUMN {name}')
    initialize_database(path)
    initialize_database(path)
    with TestClient(create_app(path)) as client:
        current = send(client, trade, 106)
        assert current['current_stop_loss'] == 95.4
        assert current['highest_price'] == 106
        assert current['profit_lock_activated'] is False
        assert current['trailing_pct'] is None


def test_activation_event_failure_rolls_back_state(client):
    trade = enter(client)
    with connect(client.app.state.database_path) as connection:
        connection.execute("""CREATE TRIGGER reject_profit_lock BEFORE INSERT ON trade_events
            WHEN NEW.event_type = 'PROFIT_LOCK_ACTIVATED'
            BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    with pytest.raises(Exception, match='test failure'):
        send(client, trade, 120)
    assert client.get('/trades').json()[0] == trade
    assert len(events(client, trade)) == 1


def test_defaults_environment_and_legacy_settings(monkeypatch):
    assert TradeSettings().stop_strategy == 'PROGRESSIVE'
    assert TradeSettings(stop_loss_percentage=15).stop_strategy == 'LEGACY'
    monkeypatch.setenv('PROFIT_LOCK_PCT', '3')
    assert TradeSettings.from_environment().profit_lock_pct == 3
    assert TradeSettings.from_environment().stop_strategy == 'PROGRESSIVE'
