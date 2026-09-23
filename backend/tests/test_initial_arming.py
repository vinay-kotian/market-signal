import pytest
from fastapi.testclient import TestClient

from app.database import connect, initialize_database
from app.main import create_app
from test_backtests import run, tick as historical_tick


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


@pytest.mark.parametrize('level_price,expected', [(23250, 'ACTIVE'), (23230, 'ACTIVE'),
    (23229, 'PENDING_ARM'), (23150, 'ACTIVE'), (23170, 'ACTIVE'), (23171, 'PENDING_ARM')])
def test_create_evaluates_distance_immediately(client, level_price, expected):
    tick(client, 23200)
    level = create(client, price=level_price)
    assert level['status'] == expected
    assert level['activation_reference_price'] == 23200  # Informational only.
    assert client.get('/signals').json() == []
    assert client.get('/simulation/events').json() == []
    assert client.get('/trades').json() == []


@pytest.mark.parametrize('direction', [-1, 1])
def test_pending_exact_boundary_and_later_touch(client, direction):
    tick(client, 23200)
    level = create(client, price=23220)
    assert level['status'] == 'PENDING_ARM'
    tick(client, 23220 + direction * 29)
    assert get(client, level)['status'] == 'PENDING_ARM'
    tick(client, 23220 + direction * 30)
    assert get(client, level)['status'] == 'ACTIVE'
    assert client.get('/signals').json() == []
    assert client.get('/simulation/events').json() == []
    assert client.get('/trades').json() == []
    tick(client, 23220)
    assert len(client.get('/signals').json()) == 1


def test_crossing_level_on_arming_tick_does_not_trigger(client):
    tick(client, 23200)
    level = create(client, price=23220)
    tick(client, 23250)  # Crosses the level AND arms it, with no signal.
    assert get(client, level)['status'] == 'ACTIVE'
    assert client.get('/signals').json() == []
    assert client.get('/simulation/events').json() == []
    tick(client, 23220)
    assert len(client.get('/signals').json()) == 1


def test_independent_indexes_and_live_changes(client):
    levels = {}
    for instrument, price, distance in [('NIFTY', 23200, 30), ('BANKNIFTY', 51000, 50), ('SENSEX', 80000, 70)]:
        update(client, instrument, distance)
        tick(client, price, instrument)
        levels[instrument] = create(client, instrument, price)
        tick(client, price + distance - 1, instrument)
        assert get(client, levels[instrument])['status'] == 'PENDING_ARM'
    before = [get(client, levels[name]) for name in ('BANKNIFTY', 'SENSEX')]
    update(client, 'NIFTY', 29)
    tick(client, 23229)  # Same price still reevaluates the new threshold.
    assert get(client, levels['NIFTY'])['status'] == 'ACTIVE'
    assert [get(client, levels[name]) for name in ('BANKNIFTY', 'SENSEX')] == before
    active = get(client, levels['NIFTY'])
    update(client, 'NIFTY', 100)
    tick(client, 23229)
    assert get(client, levels['NIFTY']) == active
    for instrument, price in [('BANKNIFTY', 51050), ('SENSEX', 80070)]:
        tick(client, price, instrument)
        assert get(client, levels[instrument])['status'] == 'ACTIVE'


@pytest.mark.parametrize('edited_price,expected', [(23250, 'ACTIVE'), (23230, 'ACTIVE'), (23220, 'PENDING_ARM')])
def test_edit_reevaluates_immediately(client, edited_price, expected):
    tick(client, 23100)
    level = create(client, price=23300)
    assert level['status'] == 'ACTIVE'
    tick(client, 23200)
    response = client.put(f"/levels/{level['id']}", json=dict(instrument='NIFTY', price=edited_price, enabled=True))
    assert response.status_code == 200
    assert response.json()['status'] == expected
    assert response.json()['activation_reference_price'] == 23200
    assert client.get('/signals').json() == []


def test_edit_uses_new_instruments_price_and_setting(client):
    tick(client, 23200)
    tick(client, 80000, 'SENSEX')
    update(client, 'SENSEX', 50)
    level = create(client, price=23250)
    edited = client.put(f"/levels/{level['id']}", json=dict(instrument='SENSEX', price=80040, enabled=True)).json()
    assert edited['status'] == 'PENDING_ARM'
    assert edited['activation_reference_price'] == 80000
    tick(client, 80090, 'SENSEX')
    assert get(client, level)['status'] == 'ACTIVE'


@pytest.mark.parametrize('price,expected', [(23249, 'PENDING_ARM'), (23250, 'ACTIVE'), (23190, 'ACTIVE'), (23300, 'ACTIVE')])
def test_missing_price_first_tick_evaluates_without_signal(client, price, expected):
    level = create(client, price=23220)
    assert level['status'] == 'PENDING_ARM'
    assert level['activation_reference_price'] is None
    tick(client, price)
    assert get(client, level)['status'] == expected
    assert get(client, level)['activation_reference_price'] == price
    assert client.get('/signals').json() == []
    assert client.get('/simulation/events').json() == []


def test_restart_preserves_pending_and_ignores_audit_reference(client):
    tick(client, 23200)
    update(client, 'NIFTY', 40)
    level = create(client, price=23220)
    # A legacy/reference value must never influence the new rule.
    with connect(client.app.state.database_path) as connection:
        connection.execute('UPDATE levels SET activation_reference_price = 90000 WHERE id = ?', (level['id'],))
    with TestClient(create_app(client.app.state.database_path)) as restarted:
        tick(restarted, 23259)
        assert get(restarted, level)['status'] == 'PENDING_ARM'
        assert get(restarted, level)['activation_reference_price'] == 90000
        tick(restarted, 23260)
        assert get(restarted, level)['status'] == 'ACTIVE'
        assert get(restarted, level)['activation_reference_price'] == 90000
        assert client.get('/settings/indexes').json()[0]['initial_arm_distance_points'] == 40


@pytest.mark.parametrize('price', [0, -100])
def test_invalid_price_does_not_create_or_arm_eligibility(client, price):
    tick(client, price)
    level = create(client, price=23220)
    assert level['status'] == 'PENDING_ARM'
    assert level['activation_reference_price'] is None
    tick(client, price - 10)
    assert get(client, level)['status'] == 'PENDING_ARM'
    edited = client.put(f"/levels/{level['id']}", json=dict(instrument='NIFTY', price=23250, enabled=True)).json()
    assert edited['status'] == 'PENDING_ARM'
    assert edited['activation_reference_price'] is None
    tick(client, 23200)
    assert get(client, level)['status'] == 'ACTIVE'
    assert client.get('/signals').json() == []


def test_zero_distance_arms_on_create_or_first_valid_tick(client):
    update(client, 'NIFTY', 0)
    missing = create(client, price=23200)
    assert missing['status'] == 'PENDING_ARM'
    tick(client, 23200)
    assert get(client, missing)['status'] == 'ACTIVE'
    assert client.get('/signals').json() == []
    assert create(client, price=23200)['status'] == 'ACTIVE'


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
    disabled = client.post('/levels', json=dict(instrument='NIFTY', price=23220, enabled=False)).json()
    future = client.post('/levels', json=dict(instrument='NIFTY', price=23220, enabled=True, level_date='2026-09-15')).json()
    tick(client, 23300)
    assert get(client, disabled)['status'] == get(client, future)['status'] == 'PENDING_ARM'


def test_setting_update_and_arming_publish_to_other_clients(client):
    tick(client, 23200)
    level = create(client, price=23220)
    with client.websocket_connect('/ws/market') as socket:
        update(client, 'NIFTY', 18)
        message = socket.receive_json()
        assert message['type'] == 'INDEX_SETTINGS_UPDATED'
        assert message['data']['initial_arm_distance_points'] == 18
        tick(client, 23238)
        message = socket.receive_json()
        assert message['type'] == 'LEVEL_UPDATED'
        assert message['data']['level']['status'] == 'ACTIVE'
        assert message['data']['level']['id'] == level['id']


def test_backtest_first_historical_tick_arms_then_return_can_trade(client):
    # No PAPER price/settings should leak into replay, and no future tick is needed to arm.
    tick(client, 25000)
    update(client, 'NIFTY', 500)
    rows = [historical_tick('09:59:00', 'SIM-NIFTY-2026-09-21-25050-PE', 100),
            historical_tick('10:00:00', 'NIFTY', 24970),
            historical_tick('10:01:00', 'NIFTY', 25000)]
    partial = run(client, rows[:2])
    assert partial['levels'][0]['status'] == 'ACTIVE'
    assert partial['signals'] == []
    full = run(client, rows)
    assert len(full['trades']) == 1
    assert full['trades'][0]['entry_time'] == '2026-09-14T10:01:00+05:30'
    assert full['levels'][0]['status'] == 'DISARMED'


@pytest.mark.parametrize('instrument,price,distance', [('NIFTY', 23200, 40), ('BANKNIFTY', 51000, 50), ('SENSEX', 80000, 60)])
def test_create_and_edit_use_each_index_setting(client, instrument, price, distance):
    update(client, instrument, distance)
    tick(client, price, instrument)
    assert create(client, instrument, price + distance - 1)['status'] == 'PENDING_ARM'
    active = create(client, instrument, price + distance)
    assert active['status'] == 'ACTIVE'
    result = client.put(f"/levels/{active['id']}", json=dict(instrument=instrument, price=price + distance - 1, enabled=True))
    assert result.json()['status'] == 'PENDING_ARM'


def test_edit_without_current_price_waits_for_valid_tick(client):
    tick(client, 23200)
    level = create(client, price=23250)
    result = client.put(f"/levels/{level['id']}", json=dict(instrument='SENSEX', price=80000, enabled=True)).json()
    assert result['status'] == 'PENDING_ARM'
    assert result['activation_reference_price'] is None
    tick(client, 80030, 'SENSEX')
    assert get(client, level)['status'] == 'ACTIVE'
    assert client.get('/signals').json() == []


def test_decimal_distance_boundary(client):
    tick(client, 23200.1)
    assert create(client, price=23230.1)['status'] == 'ACTIVE'
    level = create(client, price=23220.1)
    tick(client, 23250.09)
    assert get(client, level)['status'] == 'PENDING_ARM'
    tick(client, 23250.1)
    assert get(client, level)['status'] == 'ACTIVE'
