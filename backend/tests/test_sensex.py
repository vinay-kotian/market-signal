import pytest
from fastapi.testclient import TestClient

from app.database import connect, initialize_database
from app.main import create_app
from test_initial_arming import create, get, tick, update
from test_daily_levels import Clock
from test_backtests import tick as historical_tick


def test_settings_migrate_without_reset_and_survive_restart(tmp_path):
    path = tmp_path / 'old.sqlite3'
    with connect(path) as connection:
        connection.execute("""CREATE TABLE index_settings (
            instrument TEXT PRIMARY KEY CHECK(instrument IN ('NIFTY', 'BANKNIFTY')),
            initial_arm_distance_points REAL NOT NULL CHECK(initial_arm_distance_points >= 0),
            updated_at TEXT NOT NULL)""")
        connection.executemany('INSERT INTO index_settings VALUES (?, ?, ?)',
            [('NIFTY', 41, '2026-09-13T00:00:00+00:00'), ('BANKNIFTY', 52, '2026-09-13T00:00:00+00:00')])
    initialize_database(path)
    initialize_database(path)
    with TestClient(create_app(path)) as client:
        before = client.get('/settings/indexes').json()
        assert [(r['instrument'], r['initial_arm_distance_points']) for r in before] == [
            ('NIFTY', 41), ('BANKNIFTY', 52), ('SENSEX', 30)]
        assert before[0]['updated_at'] == before[1]['updated_at'] == '2026-09-13T00:00:00Z'
        assert update(client, 'SENSEX', 73).status_code == 200
        after = client.get('/settings/indexes').json()
        assert after[:2] == before[:2]
        assert after[2]['initial_arm_distance_points'] == 73
    with TestClient(create_app(path)) as client:
        assert client.get('/settings/indexes').json() == after


@pytest.mark.parametrize('direction', [-1, 1])
def test_sensex_initial_arming_is_independent_and_edit_resets(client, direction):
    tick(client, 80000, 'SENSEX')
    level = create(client, 'SENSEX', 80020)
    assert level['status'] == 'PENDING_ARM'
    assert level['activation_reference_price'] == 80000
    update(client, 'NIFTY', 0)
    update(client, 'BANKNIFTY', 0)
    tick(client, 80000 + direction * 29, 'SENSEX')
    assert get(client, level)['status'] == 'PENDING_ARM'
    update(client, 'SENSEX', 40)
    tick(client, 80000 + direction * 30, 'SENSEX')
    assert get(client, level)['status'] == 'PENDING_ARM'
    tick(client, 80000 + direction * 40, 'SENSEX')
    assert get(client, level)['status'] == 'ACTIVE'
    assert client.get('/signals').json() == []
    response = client.put(f"/levels/{level['id']}", json=dict(instrument='SENSEX', price=80100, enabled=True))
    assert response.status_code == 200
    assert response.json()['status'] == 'PENDING_ARM'
    assert response.json()['activation_reference_price'] == 80000 + direction * 40


def test_sensex_full_paper_lifecycle_and_reporting(tmp_path):
    clock = Clock()
    with TestClient(create_app(tmp_path / 'paper.sqlite3', clock=clock)) as client:
        assert 'SENSEX' in client.get('/connection').json()['available_instruments']
        level = create(client, 'SENSEX', 80000)
        assert level['activation_reference_price'] is None
        tick(client, 79900, 'SENSEX')
        assert get(client, level)['status'] == 'PENDING_ARM'
        assert get(client, level)['activation_reference_price'] == 79900
        tick(client, 79930, 'SENSEX')
        assert get(client, level)['status'] == 'ACTIVE'
        assert client.get('/signals').json() == []
        tick(client, 80000, 'SENSEX')
        assert get(client, level)['status'] == 'DISARMED'
        trade, = client.get('/trades').json()
        assert trade['instrument'] == 'SENSEX'
        assert trade['trade_mode'] == 'PAPER'
        assert trade['strike'] == 80100
        tick(client, trade['initial_stop_loss'], trade['option_symbol'])
        assert client.get('/trades').json()[0]['status'] == 'CLOSED'
        history = client.get('/trades/history', params={'instrument': 'SENSEX'})
        assert history.status_code == 200
        assert history.json()['items'][0]['instrument'] == 'SENSEX'
        update(client, 'SENSEX', 500)
        tick(client, 80049, 'SENSEX')
        assert get(client, level)['status'] == 'DISARMED'
        tick(client, 80050, 'SENSEX')
        assert get(client, level)['status'] == 'ACTIVE'
        assert len(client.get('/signals').json()) == 1
        clock.set('2026-09-15T10:00:00+05:30')
        tick(client, 80000, 'SENSEX')
        assert get(client, level)['status'] == 'EXPIRED'
        assert len(client.get('/signals').json()) == 1


@pytest.mark.parametrize('distance, expected_trades', [(30, 1), (200, 0)])
def test_sensex_backtest_uses_historical_reference_and_isolated_settings(client, distance, expected_trades):
    symbol = 'SIM-SENSEX-2026-09-21-80100-PE'
    rows = [historical_tick('09:59:00', symbol, 100),
            historical_tick('09:59:30', 'SENSEX', 79900),
            historical_tick('10:00:00', 'SENSEX', 79930),
            historical_tick('10:01:00', 'SENSEX', 80000),
            historical_tick('10:02:00', symbol, 90)]
    tick(client, 90000, 'SENSEX')
    update(client, 'SENSEX', 500)
    response = client.post('/backtests/run', json=dict(instrument='SENSEX', levels=[80000], dataset=rows,
        index_settings={'SENSEX': {'initial_arm_distance_points': distance}}))
    assert response.status_code == 201
    result = response.json()
    assert result['status'] == 'COMPLETED'
    assert result['levels'][0]['activation_reference_price'] == 79900
    assert len(result['trades']) == expected_trades
    assert client.get('/trades').json() == []
    assert client.get('/settings/indexes').json()[2]['initial_arm_distance_points'] == 500
    if expected_trades:
        trade = result['trades'][0]
        assert trade['trade_mode'] == 'BACKTEST'
        assert trade['entry_time'] == '2026-09-14T10:01:00+05:30'
        assert trade['status'] == 'CLOSED'
        assert trade['exit_reason'] == 'STOP_LOSS'
    else:
        assert result['levels'][0]['status'] == 'PENDING_ARM'
