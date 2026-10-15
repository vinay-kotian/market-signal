"""Level metadata must never change strategy decisions or historical snapshots."""
import csv
from io import StringIO
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.database import connect, initialize_database
from app.main import create_app
from app.option_models import StoredOptionSelection
from app.signal_models import SignalResult
from test_backtests import run, post
from test_daily_levels import Clock
from test_paper_trades import publish
from test_external_levels import post as external_post, BODY

BASE = dict(instrument='NIFTY', price=25000, enabled=True)


def create(client, **changes):
    response = client.post('/levels', json={**BASE, **changes})
    assert response.status_code == 201, response.text
    return response.json()


def test_date_and_attributes_persist_and_refresh_views(tmp_path):
    path = tmp_path / 'edit.db'
    with TestClient(create_app(path, clock=Clock())) as client:
        level = create(client, timeframe='5m')
        with client.websocket_connect('/ws/market') as ws:
            response = client.put(f"/levels/{level['id']}", json={**BASE, 'price': 25100,
                'enabled': False, 'level_date': '2026-09-15', 'timeframe': '1h'})
            assert response.status_code == 200
            updated = response.json()
            message = ws.receive_json()
            assert message['type'] == 'LEVEL_UPDATED'
            assert message['data']['level'] == updated
        assert updated['created_at'] == level['created_at']
        assert updated['timeframe'] == '1h'
        assert client.get('/levels?level_date=2026-09-14').json() == []
        assert client.get('/levels?level_date=2026-09-15').json() == [updated]
        publish(client, [25000, 25100])
        assert client.get('/signals').json() == []
    with TestClient(create_app(path, clock=Clock())) as client:
        assert client.get(f"/levels/{level['id']}").json() == updated


@pytest.mark.parametrize('invalid', ['2026-02-30', '20260915', '2026-09-15T00:00:00Z', 1789430400])
def test_invalid_calendar_dates_do_not_write(client, invalid):
    level = create(client)
    assert client.put(f"/levels/{level['id']}", json={**BASE, 'level_date': invalid}).status_code == 422
    assert client.get(f"/levels/{level['id']}").json() == level


def test_date_duplicate_past_and_expired_rejected_atomically(client):
    original = create(client, timeframe='15m')
    future = create(client, timeframe='15m', level_date='2026-09-15')
    for target in ('2026-09-13', '2026-09-15'):
        response = client.put(f"/levels/{original['id']}", json={**BASE, 'timeframe': '15m', 'level_date': target})
        assert response.status_code == 409
        assert client.get(f"/levels/{original['id']}").json() == original
    expired = create(client, level_date='2026-09-13')
    assert client.put(f"/levels/{expired['id']}", json={**BASE, 'level_date': '2026-09-16'}).status_code == 409
    assert client.delete(f"/levels/{future['id']}").status_code == 204
    assert client.put(f"/levels/{original['id']}", json={**BASE, 'level_date': '2026-09-15'}).status_code == 200


def test_numeric_sort_after_create_edit_delete_and_date_filter(client):
    rows = [create(client, price=price) for price in (100, 9.5, 20)]
    create(client, price=1, level_date='2026-09-15')
    prices = lambda: [row['price'] for row in client.get('/levels?level_date=2026-09-14').json()]
    assert prices() == [9.5, 20, 100]
    assert client.put(f"/levels/{rows[0]['id']}", json={**BASE, 'price': 2}).status_code == 200
    assert prices() == [2, 9.5, 20]
    assert client.delete(f"/levels/{rows[1]['id']}").status_code == 204
    assert prices() == [2, 20]
    assert [row['price'] for row in client.get('/levels').json()] == [1, 2, 20]


def test_timeframe_validation_options_and_omitted_update(client, monkeypatch):
    monkeypatch.setenv('LEVEL_TIMEFRAMES', '30m,4h')
    assert client.get('/levels/timeframes').json() == ['5m', '15m', '1h', '1d', '30m', '4h']
    level = create(client, timeframe='30m')
    assert client.put(f"/levels/{level['id']}", json={**BASE, 'enabled': False}).json()['timeframe'] == '30m'
    for value, status in [('wrong', 422), ('0m', 422), ('7m', 409), (5, 422)]:
        assert client.post('/levels', json={**BASE, 'timeframe': value}).status_code == status
    assert client.put(f"/levels/{level['id']}", json={**BASE, 'timeframe': None}).json()['timeframe'] is None


def test_duplicate_identity_is_atomic_and_allows_distinct_timeframes(client):
    for timeframe in (None, '5m', '15m', '1h', '1d'):
        create(client, timeframe=timeframe)
        assert client.post('/levels', json={**BASE, 'timeframe': timeframe}).status_code == 409
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: client.post('/levels', json={**BASE, 'price': 25100}), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert len(client.get('/levels').json()) == 6


def test_same_price_generates_independent_signals_and_frozen_paper_entries(client):
    first = create(client, timeframe='5m')
    second = create(client, timeframe='1h')
    publish(client, [24900, 25000, 25000])
    signals = client.get('/signals').json()
    trades = client.get('/trades').json()
    assert len(signals) == 2
    assert len(trades) == 1  # Existing one-open-trade-per-instrument rule remains in force.
    assert any(row['failure_reason'] == 'ACTIVE_TRADE_EXISTS' for row in client.get('/trade-entry-results').json())
    assert {signal['timeframe'] for signal in signals} == {'5m', '1h'}
    assert {trade['timeframe'] for trade in trades} == {'5m'}
    assert all(trade['trade_mode'] == 'PAPER' and trade['strategy_type'] == 'LEGACY' for trade in trades)
    for level in (first, second):
        assert client.put(f"/levels/{level['id']}", json={**BASE, 'level_date': '2026-09-15'}).status_code == 409
    assert client.put(f"/levels/{first['id']}", json={**BASE, 'price': 25100, 'timeframe': '15m'}).status_code == 200
    assert client.get('/signals').json() == signals
    assert client.get('/trades').json() == trades
    signal = next(signal for signal in signals if signal['level_id'] == first['id'])
    selection = next(row for row in client.get('/option-selections').json() if row['signal_id'] == signal['id'])
    client.app.state.paper_executor.execute(SignalResult(**signal), StoredOptionSelection(**selection), client.app.state.level_repository.clock())
    assert client.get('/trades').json() == trades  # Re-execution cannot duplicate a signal entry.


def test_rejected_signal_also_blocks_date_changes(client):
    level = create(client, timeframe='5m')
    publish(client, [24900])  # arm, no approach samples at next tick
    # Persist a rejected analysis through the actual signal service.
    from app.signal_models import SignalAnalysis
    repo = client.app.state.signal_repository
    repo.save(SignalAnalysis(trigger_id=1, level_id=level['id'], instrument='NIFTY', level=25000,
        timeframe='5m', trigger_price=25000, direction=None, approach_distance=None, valid=False,
        rejection_reason='INSUFFICIENT_PRICE_HISTORY', timestamp=client.app.state.level_repository.clock()))
    before = client.get('/signals').json()
    assert client.put(f"/levels/{level['id']}", json={**BASE, 'level_date': '2026-09-15'}).status_code == 409
    assert client.get('/signals').json() == before


def test_reports_detail_filters_and_csv_use_entry_timeframe(client, monkeypatch):
    monkeypatch.setenv('EXTERNAL_LEVELS_API_KEY', 'timeframe-test')
    # Settings are loaded at app creation, so use the fixture's service configuration.
    from pydantic import SecretStr
    client.app.state.external_levels_settings.api_key = SecretStr('timeframe-test')
    from test_paper_report import add_trade
    for index, timeframe in enumerate(('5m', '1h', None), 1):
        trade = add_trade(client, index)
        with connect(client.app.state.database_path) as c:
            c.execute('UPDATE trades SET timeframe = ? WHERE trade_id = ?', (timeframe, trade.trade_id))
    for timeframe in ('5m', '1h', 'UNKNOWN'):
        params = dict(timeframe=timeframe, from_date='2026-09-14', to_date='2026-09-14', view='RAW')
        history = client.get('/trades/history', params=params).json()
        assert history['total'] == 1
        trade = history['items'][0]
        expected = None if timeframe == 'UNKNOWN' else timeframe
        assert trade['timeframe'] == expected
        assert client.get(f"/trades/{trade['trade_id']}").json()['trade']['timeframe'] == expected
        assert client.get('/trades/history/ids', params=params).json() == [trade['trade_id']]
        assert client.get('/reports/paper-trading', params=params).json()['total_trades'] == 1
        comparison = client.get('/reports/strategy-comparison', params=params).json()
        assert comparison['strategies']['LEGACY']['total_trades'] == 1
        response = client.get('/reports/export', params=params, headers={'X-API-Key': 'timeframe-test'})
        assert response.status_code == 200
        row, = list(csv.DictReader(StringIO(response.text)))
        assert row['timeframe'] == (expected or '')
    assert client.get('/trades/history?timeframe=garbage').status_code == 422


def test_backtest_structured_levels_and_legacy_inputs(client):
    result = run(client, levels=[dict(price=25000, timeframe='5m'), dict(price=25000, timeframe='1h'), dict(price=25000, timeframe='5m')])
    assert len(result['levels']) == len(result['signals']) == 2
    assert len(result['trades']) == 1
    assert any(row['failure_reason'] == 'ACTIVE_TRADE_EXISTS' for row in result['entry_results'])
    assert {trade['timeframe'] for trade in result['trades']} == {'5m'}
    assert {level['timeframe'] for level in result['levels']} == {'5m', '1h'}
    assert client.get('/backtests/' + result['id']).json() == result
    assert all(trade['trade_mode'] == 'BACKTEST' for trade in result['trades'])
    assert client.get('/trades').json() == []
    old = run(client)
    assert old['levels'][0]['timeframe'] is old['signals'][0]['timeframe'] is old['trades'][0]['timeframe'] is None
    assert post(client, levels=[dict(price=25000, timeframe='7m')]).status_code == 422


def test_external_deduplication_includes_timeframe(client, monkeypatch):
    from pydantic import SecretStr
    client.app.state.external_levels_settings.api_key = SecretStr('test-external-secret')
    for timeframe in (None, '5m', '1h'):
        body = {**BODY, 'levels': [25000, 25000], 'timeframe': timeframe}
        response = external_post(client, body)
        assert response.status_code == 200
        assert [row['status'] for row in response.json()['results']] == ['CREATED', 'DUPLICATE']
        assert external_post(client, body).json()['results'][0]['status'] == 'DUPLICATE'
    assert len(client.get('/levels').json()) == 3


def test_nullable_migration_preserves_history(tmp_path):
    path = tmp_path / 'legacy.db'
    with TestClient(create_app(path, clock=Clock())) as client:
        create(client)
        publish(client, [24900, 25000])
        before = {table: None for table in ('levels', 'signals', 'trades')}
        with connect(path) as c:
            for table in before:
                before[table] = [dict(row) for row in c.execute(f'SELECT * FROM {table}')]
    # Remove only the additive column to recreate the pre-upgrade schema.
    with connect(path) as c:
        c.execute('DROP INDEX levels_identity')
        for table in before:
            c.execute(f'ALTER TABLE {table} DROP COLUMN timeframe')
    initialize_database(path)
    initialize_database(path)
    with connect(path) as c:
        for table in before:
            after = [dict(row) for row in c.execute(f'SELECT * FROM {table}')]
            assert after == before[table]
            assert all(row['timeframe'] is None for row in after)


@pytest.mark.parametrize('strategy', ['LEGACY', 'ATR'])
def test_timeframe_metadata_does_not_change_backtest_entry_or_exit(client, strategy):
    from test_atr_exit import candles
    from test_backtests import SYMBOL, dataset
    warm = [c.model_dump(mode='json') for c in candles(SYMBOL)]
    rows = dataset([('10:02:00', 92), ('10:03:00', 80)])
    original = run(client, rows, exit_strategy=strategy, candles=warm)
    tagged = run(client, rows, exit_strategy=strategy, candles=warm,
                 levels=[dict(price=25000, timeframe='1d')])
    fields = ('entry_time', 'entry_price', 'initial_stop_loss', 'exit_time', 'exit_price',
              'exit_reason', 'realised_pnl', 'strategy_type', 'trade_mode')
    assert len(original['trades']) == len(tagged['trades']) == 1
    assert {key: original['trades'][0][key] for key in fields} == {key: tagged['trades'][0][key] for key in fields}
    assert tagged['trades'][0]['timeframe'] == '1d'


def test_edit_waits_for_inflight_tick_and_rechecks_signals(client):
    import asyncio
    import threading
    create(client, timeframe='5m')
    publish(client, [24900])
    started, release, edit_started = threading.Event(), threading.Event(), threading.Event()
    executor = client.app.state.paper_executor
    prepare = executor.prepare

    async def delayed(selection):
        started.set()
        await asyncio.to_thread(release.wait, 3)
        await prepare(selection)

    executor.prepare = delayed
    with ThreadPoolExecutor(2) as pool:
        tick = pool.submit(publish, client, [25000])
        assert started.wait(3)

        def edit():
            edit_started.set()
            return client.put('/levels/1', json={**BASE, 'level_date': '2026-09-15'})

        change = pool.submit(edit)
        try:
            assert edit_started.wait(3)
            assert not change.done()
        finally:
            release.set()
        tick.result(timeout=5)
        assert change.result(timeout=5).status_code == 409
    assert client.get('/levels/1').json()['level_date'] == '2026-09-14'
    assert client.get('/signals').json()[0]['timeframe'] == '5m'


def test_preexisting_duplicate_levels_are_preserved_and_remain_toggleable(client):
    level = create(client)
    with connect(client.app.state.database_path) as c:
        columns = [row['name'] for row in c.execute('PRAGMA table_info(levels)') if row['name'] != 'id']
        names = ', '.join(columns)
        c.execute(f'INSERT INTO levels ({names}) SELECT {names} FROM levels WHERE id = ?', (level['id'],))
    initialize_database(client.app.state.database_path)
    assert len(client.get('/levels').json()) == 2
    assert client.put('/levels/1', json={**BASE, 'enabled': False}).status_code == 200
    assert client.post('/levels', json=BASE).status_code == 409
