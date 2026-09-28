import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.external_levels import ExternalLevelsInput, ingest
from app.main import create_app
from test_daily_levels import Clock

URL = '/external/levels'  # Nginx and Vite remove the public /api prefix.
BODY = dict(instrument='NIFTY', levels=[23231, 23300], level_date='2026-09-14', source='external-app')
HEADERS = {'X-API-Key': 'test-external-secret'}


@pytest.fixture(autouse=True)
def external_key(monkeypatch):
    monkeypatch.setenv('EXTERNAL_LEVELS_API_KEY', HEADERS['X-API-Key'])


def post(client, body=None, key=None):
    headers = {**HEADERS, **({'Idempotency-Key': key} if key is not None else {})}
    return client.post(URL, json=BODY if body is None else body, headers=headers)


@pytest.mark.parametrize('instrument', ['NIFTY', 'BANKNIFTY', 'SENSEX'])
def test_supported_indices_and_audit(client, instrument):
    body = {**BODY, 'instrument': instrument}
    response = post(client, body, 'batch-1')
    assert response.status_code == 200
    assert [r['status'] for r in response.json()['results']] == ['CREATED', 'CREATED']
    assert {r['level_state'] for r in response.json()['results']} == {'PENDING_ARM'}
    rows = client.get(URL, headers=HEADERS, params={'instrument': instrument,
        'level_date': BODY['level_date'], 'status': 'PENDING_ARM'}).json()
    assert len(rows) == 2
    assert all(r['source'] == 'external-app' and r['created_by'] == 'EXTERNAL_API'
               and r['idempotency_key'] == 'batch-1' and r['created_at'] for r in rows)
    assert rows[0]['request_id'] == rows[1]['request_id']
    assert client.get('/signals').json() == client.get('/trades').json() == []
    assert client.get(URL, headers=HEADERS, params={'status': 'ACTIVE'}).json() == []


@pytest.mark.parametrize('headers', [{}, {'X-API-Key': 'wrong'}])
def test_auth_required_for_both_endpoints(client, headers):
    assert client.post(URL, json=BODY, headers=headers).status_code == 401
    assert client.get(URL, headers=headers).status_code == 401
    assert client.get('/levels').json() == []


def test_unconfigured_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv('EXTERNAL_LEVELS_API_KEY')
    with TestClient(create_app(tmp_path / 'disabled.db')) as client:
        assert post(client).status_code == 503
        assert client.get(URL, headers=HEADERS).status_code == 503
        assert client.post('/levels', json={'instrument': 'NIFTY', 'price': 23231, 'enabled': True}).status_code == 201


@pytest.mark.parametrize('change', [
    {'instrument': 'OTHER'}, {'levels': []}, {'levels': [0]}, {'levels': [-1]},
    {'levels': ['23231']}, {'levels': [True]}, {'levels': [None]},
    {'levels': [23231, -1]}, {'level_date': 'not-date'}, {'level_date': '2026-02-30'},
    {'level_date': '2026-09-13'}, {'level_date': 1789344000}, {'source': ' '},
    {'enabled': False}, {'levels': [1] * 1001},
])
def test_invalid_batch_is_atomic(client, change):
    assert post(client, {**BODY, **change}).status_code == 422
    assert client.get('/levels').json() == []


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_price_validation(client, value):
    response = client.post(URL, content=json.dumps({**BODY, 'levels': [value]}),
        headers={**HEADERS, 'Content-Type': 'application/json'})
    assert response.status_code == 422


def test_duplicate_existing_ui_and_repeated_prices(client):
    ui = client.post('/levels', json={'instrument': 'NIFTY', 'price': 23231, 'enabled': False}).json()
    body = {**BODY, 'levels': [23231, 23300, 23300]}
    result = post(client, body).json()['results']
    assert [r['status'] for r in result] == ['DUPLICATE', 'CREATED', 'DUPLICATE']
    assert result[0]['level_id'] == ui['id']
    assert result[1]['level_id'] == result[2]['level_id']
    assert client.get(f"/levels/{ui['id']}").json() == ui
    assert all(r['status'] == 'DUPLICATE' for r in post(client, body).json()['results'])
    assert len(client.get('/levels').json()) == 2
    assert post(client, {**BODY, 'instrument': 'SENSEX'}).json()['results'][0]['status'] == 'CREATED'
    assert post(client, {**BODY, 'level_date': '2026-09-15'}).json()['results'][0]['status'] == 'CREATED'


@pytest.mark.parametrize('instrument,distance', [('NIFTY', 30), ('BANKNIFTY', 50), ('SENSEX', 100)])
def test_shared_index_arming_and_ui_parity(client, instrument, distance):
    client.put('/settings/indexes/' + instrument, json={'initial_arm_distance_points': distance})
    repo = client.app.state.level_repository
    repo.record_price(instrument, 23200, repo.clock())
    prices = [23200 + distance, 23200 + distance - 1]
    result = post(client, {**BODY, 'instrument': instrument, 'levels': prices}).json()['results']
    assert [r['level_state'] for r in result] == ['ACTIVE', 'PENDING_ARM']
    for price, external in zip(prices, result):
        ui = client.post('/levels', json={'instrument': instrument, 'price': price, 'enabled': True}).json()
        assert ui['status'] == external['level_state']
    assert client.get('/signals').json() == []


def test_missing_price_next_tick_arms_without_trigger(client):
    result = post(client).json()['results'][0]
    assert result['level_state'] == 'PENDING_ARM'
    assert client.post('/simulation/tick', json={'instrument': 'NIFTY', 'price': 23100}).status_code == 200
    assert client.get(f"/levels/{result['level_id']}").json()['status'] == 'ACTIVE'
    assert client.get('/signals').json() == []


def test_idempotency_restart_rollover_and_conflict(tmp_path):
    path, clock = tmp_path / 'retry.db', Clock()
    with TestClient(create_app(path, clock=clock)) as client:
        original = post(client, key='request-1').json()
        assert post(client, key='request-1').json() == original
        assert post(client, {**BODY, 'levels': [24000]}, 'request-1').status_code == 409
    clock.set('2026-09-15T10:00:00+05:30')
    with TestClient(create_app(path, clock=clock)) as client:
        assert post(client, key='request-1').json() == original
        rows = client.get(URL, headers=HEADERS, params={'status': 'EXPIRED'}).json()
        assert len(rows) == 2
        assert all(r['status'] == 'EXPIRED' for r in rows)
        assert post(client, key='new-request').status_code == 422
        assert client.app.state.level_repository.list_enabled('NIFTY') == []


@pytest.mark.parametrize('same_key', [False, True])
def test_concurrent_ingestion_serializes_duplicates(client, same_key):
    repo = client.app.state.level_repository
    data = ExternalLevelsInput(**BODY)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: ingest(repo, data, 'same' if same_key else str(n))[0], range(4)))
    assert len(repo.list()) == 2
    if same_key:
        assert all(r == results[0] for r in results)
    else:
        assert sum(item.status == 'CREATED' for r in results for item in r.results) == 2


def test_failure_rolls_back_levels_audit_and_retry_result(client):
    repo = client.app.state.level_repository
    original = repo.create
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('injected failure')
        return original(*args, **kwargs)

    with patch.object(repo, 'create', side_effect=fail_second):
        with pytest.raises(RuntimeError, match='injected'):
            post(client, key='atomic')
    assert repo.list() == []
    with connect(repo.database_path) as connection:
        for table in ['external_level_audit', 'external_level_requests']:
            assert connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0
    assert all(r['status'] == 'CREATED' for r in post(client, key='atomic').json()['results'])


@pytest.mark.parametrize('key', ['', '   ', 'has space', 'x' * 201])
def test_invalid_idempotency_reference(client, key):
    assert post(client, key=key).status_code == 422
    assert client.get('/levels').json() == []


def test_created_levels_publish_normal_ui_event(client):
    with client.websocket_connect('/ws/market') as websocket:
        result = post(client, {**BODY, 'levels': [23231]}).json()['results'][0]
        message = websocket.receive_json()
        assert message['type'] == 'LEVEL_UPDATED'
        assert message['data']['level']['id'] == result['level_id']
        assert message['data']['level']['status'] == 'PENDING_ARM'
    with patch.object(client.app.state.websocket_hub, 'publish') as publish:
        assert post(client, {**BODY, 'levels': [23231]}).json()['results'][0]['status'] == 'DUPLICATE'
        publish.assert_not_called()


def test_external_level_uses_trade_rearm_and_rollover(tmp_path):
    clock = Clock()
    with TestClient(create_app(tmp_path / 'lifecycle.db', clock=clock)) as client:
        result = post(client, {**BODY, 'levels': [25000]}).json()['results'][0]
        level_id = result['level_id']

        def tick(price):
            assert client.post('/simulation/tick', json={'instrument': 'NIFTY', 'price': price}).status_code == 200
            return client.get(f'/levels/{level_id}').json()['status']

        assert tick(24900) == 'ACTIVE'
        assert client.get('/trades').json() == []
        assert tick(25000) == 'DISARMED'
        assert len(client.get('/trades').json()) == 1
        assert tick(24950) == 'ACTIVE'
        assert len(client.get('/trades').json()) == 1
        clock.set('2026-09-15T10:00:00+05:30')
        assert tick(25000) == 'EXPIRED'
        assert len(client.get('/trades').json()) == 1
