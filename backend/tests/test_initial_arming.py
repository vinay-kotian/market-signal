from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import connect, initialize_database
from app.main import create_app
from test_backtests import run, dataset


def tick(client, price, instrument='NIFTY'):
    response = client.post('/simulation/tick', json=dict(instrument=instrument, price=price))
    assert response.status_code == 200


def create(client, instrument='NIFTY', price=23231):
    response = client.post('/levels', json=dict(instrument=instrument, price=price, enabled=True))
    assert response.status_code == 201
    return response.json()


def get(client, level):
    return client.get(f"/levels/{level['id']}").json()


def update(client, instrument, distance):
    return client.put(f'/settings/indexes/{instrument}', json=dict(initial_arm_distance_points=distance))


def test_defaults_update_restart_and_independence(client):
    initial = client.get('/settings/indexes').json()
    assert {row['instrument']: row['initial_arm_distance_points'] for row in initial} == {'NIFTY': 30, 'BANKNIFTY': 30, 'SENSEX': 30}
    response = update(client, 'NIFTY', 40)
    assert response.status_code == 200
    saved = client.get('/settings/indexes').json()
    assert saved[0]['initial_arm_distance_points'] == 40
    assert saved[1] == initial[1]
    with TestClient(create_app(client.app.state.database_path)) as restarted:
        assert restarted.get('/settings/indexes').json() == saved


@pytest.mark.parametrize('value', [-1, 'hello', '30', None, True, float('inf')])
def test_validation(client, value):
    before = client.get('/settings/indexes').json()
    if value == float('inf'):
        response = client.put('/settings/indexes/NIFTY', content='{"initial_arm_distance_points":1e999}', headers={'Content-Type': 'application/json'})
    else:
        response = update(client, 'NIFTY', value)
    assert response.status_code == 422
    assert client.get('/settings/indexes').json() == before


def test_invalid_instrument_and_per_level_distance_rejected(client):
    assert update(client, 'UNKNOWN', 30).status_code == 422
    response = client.post('/levels', json=dict(instrument='NIFTY', price=23231, enabled=True, initial_arm_distance_points=30))
    assert response.status_code == 422
    assert update(client, 'BANKNIFTY', 0).status_code == 200


def test_reference_exact_boundary_and_no_signal_on_arming_tick(client):
    tick(client, 23200)
    level = create(client)
    assert level['status'] == 'PENDING_ARM'
    assert level['activation_reference_price'] == 23200
    tick(client, 23229)
    assert get(client, level)['status'] == 'PENDING_ARM'
    tick(client, 23230)
    assert get(client, level)['status'] == 'ACTIVE'
    assert client.get('/signals').json() == []
    tick(client, 23231)
    assert len(client.get('/signals').json()) == 1


def test_crossing_level_on_arming_tick_does_not_trigger(client):
    tick(client, 23200)
    level = create(client, price=23220)
    tick(client, 23230)
    assert get(client, level)['status'] == 'ACTIVE'
    assert client.get('/signals').json() == []
    tick(client, 23220)
    assert len(client.get('/signals').json()) == 1


def test_independent_indexes_and_live_changes(client):
    update(client, 'BANKNIFTY', 50)
    tick(client, 23200)
    tick(client, 51000, 'BANKNIFTY')
    nifty = create(client)
    bank = create(client, 'BANKNIFTY', 51031)
    tick(client, 23229)
    tick(client, 51030, 'BANKNIFTY')
    assert get(client, nifty)['status'] == get(client, bank)['status'] == 'PENDING_ARM'
    before = get(client, bank)
    assert update(client, 'NIFTY', 29).status_code == 200
    # Identical-price ticks still reevaluate a newly configured threshold.
    tick(client, 23229)
    assert get(client, nifty)['status'] == 'ACTIVE'
    assert get(client, bank) == before
    tick(client, 51049, 'BANKNIFTY')
    assert get(client, bank)['status'] == 'PENDING_ARM'
    tick(client, 51050, 'BANKNIFTY')
    assert get(client, bank)['status'] == 'ACTIVE'
    active = get(client, nifty)
    update(client, 'NIFTY', 100)
    assert get(client, nifty) == active


def test_edit_resets_reference_and_pending_uses_latest_setting(client):
    tick(client, 23200)
    level = create(client)
    tick(client, 23230)
    assert get(client, level)['status'] == 'ACTIVE'
    response = client.put(f"/levels/{level['id']}", json=dict(instrument='NIFTY', price=23300, enabled=True))
    assert response.json()['status'] == 'PENDING_ARM'
    assert response.json()['activation_reference_price'] == 23230
    update(client, 'NIFTY', 40)
    tick(client, 23200)  # 30 below reference, still pending with updated config.
    assert get(client, level)['status'] == 'PENDING_ARM'
    tick(client, 23190)
    assert get(client, level)['status'] == 'ACTIVE'


def test_missing_price_waits_then_captures_once_and_survives_restart(client):
    level = create(client)
    assert level['activation_reference_price'] is None
    tick(client, 23200)
    assert get(client, level)['activation_reference_price'] == 23200
    tick(client, 23210)
    assert get(client, level)['activation_reference_price'] == 23200
    with TestClient(create_app(client.app.state.database_path)) as restarted:
        assert get(restarted, level)['activation_reference_price'] == 23200
        tick(restarted, 23230)
        assert get(restarted, level)['status'] == 'ACTIVE'
        new = create(restarted, price=23300)
        assert new['activation_reference_price'] == 23230


def test_zero_distance_arms_on_next_evaluation_not_on_create(client):
    update(client, 'NIFTY', 0)
    tick(client, 23200)
    level = create(client)
    assert level['status'] == 'PENDING_ARM'
    tick(client, 23200)
    assert get(client, level)['status'] == 'ACTIVE'
    assert client.get('/signals').json() == []


def test_setting_change_does_not_touch_any_level_or_post_trade_rearm(client):
    tick(client, 24900)
    level = create(client, price=25000)
    tick(client, 24930)
    tick(client, 25000)
    assert get(client, level)['status'] == 'DISARMED'
    expired = client.post('/levels', json=dict(instrument='NIFTY', price=25000, enabled=True, level_date='2026-09-13')).json()
    before = client.get('/levels').json()
    update(client, 'NIFTY', 500)
    assert client.get('/levels').json() == before
    tick(client, 25049)
    assert get(client, level)['status'] == 'DISARMED'
    tick(client, 25050)
    assert get(client, level)['status'] == 'ACTIVE'
    assert get(client, expired)['status'] == 'EXPIRED'


def test_backtest_index_settings_are_isolated(client):
    update(client, 'NIFTY', 500)
    result = run(client)
    assert len(result['trades']) == 1  # Isolated default 30.
    result = run(client, index_settings={'NIFTY': {'initial_arm_distance_points': 200}})
    assert len(result['trades']) == 0
    assert result['levels'][0]['status'] == 'PENDING_ARM'
    assert client.get('/settings/indexes').json()[0]['initial_arm_distance_points'] == 500


def test_migration_preserves_existing_states_and_reference(client):
    tick(client, 23200)
    levels = [create(client, price=23300 + i) for i in range(3)]
    with connect(client.app.state.database_path) as connection:
        for level, state in zip(levels, ('ACTIVE', 'DISARMED', 'EXPIRED')):
            connection.execute('UPDATE levels SET status = ? WHERE id = ?', (state, level['id']))
        connection.execute('ALTER TABLE levels DROP COLUMN activation_reference_price')
        before = [dict(row) for row in connection.execute('SELECT * FROM levels ORDER BY id')]
    initialize_database(client.app.state.database_path)
    initialize_database(client.app.state.database_path)
    after = client.get('/levels').json()
    assert [row['status'] for row in after] == ['ACTIVE', 'DISARMED', 'EXPIRED']
    assert [row['id'] for row in after] == [row['id'] for row in before]
    assert all(row['activation_reference_price'] is None for row in after)
    update(client, 'NIFTY', 100)
    assert client.get('/levels').json() == after


def test_disabled_and_future_pending_levels_do_not_arm(client):
    tick(client, 23200)
    disabled = client.post('/levels', json=dict(instrument='NIFTY', price=23231, enabled=False)).json()
    future = client.post('/levels', json=dict(instrument='NIFTY', price=23231, enabled=True, level_date='2026-09-15')).json()
    tick(client, 23300)
    assert get(client, disabled)['status'] == get(client, future)['status'] == 'PENDING_ARM'


def test_setting_update_and_arming_publish_to_other_clients(client):
    tick(client, 23200)
    level = create(client)
    with client.websocket_connect('/ws/market') as socket:
        update(client, 'NIFTY', 18)
        message = socket.receive_json()
        assert message['type'] == 'INDEX_SETTINGS_UPDATED'
        assert message['data']['initial_arm_distance_points'] == 18
        tick(client, 23218)
        message = socket.receive_json()
        assert message['type'] == 'LEVEL_UPDATED'
        assert message['data']['level']['status'] == 'ACTIVE'
        assert message['data']['level']['id'] == level['id']
