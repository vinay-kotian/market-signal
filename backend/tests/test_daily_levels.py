from active_level_fixture import create_active_level, create_active_record
import threading
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.database import connect, initialize_database
from app.level_repository import LevelRepository
from app.main import create_app
from app.models import LevelInput
from app.option_prices import SimulatedOptionPrices
from app.option_models import StoredOptionSelection
from app.signal_models import SignalResult
from app.trading_date import trading_date
from test_backtests import run, dataset
from test_paper_trades import publish

PAYLOAD = dict(instrument='NIFTY', price=25000, enabled=True)


class Clock:
    def __init__(self, value='2026-09-14T10:00:00+05:30'):
        self.set(value)

    def __call__(self):
        return self.value

    def set(self, value):
        self.value = datetime.fromisoformat(value)


def test_today_eligible_and_historical_queryable(client):
    today = create_active_level(client, json=PAYLOAD).json()
    yesterday = create_active_level(client, json={**PAYLOAD, 'level_date': '2026-09-13'}).json()
    future = create_active_level(client, json={**PAYLOAD, 'level_date': '2026-09-15'}).json()
    assert today['level_date'] == '2026-09-14'
    assert today['status'] == future['status'] == 'ACTIVE'
    assert yesterday['status'] == 'EXPIRED'
    publish(client, [24900, 25000, 25100, 25000])
    assert {row['level_id'] for row in client.get('/signals').json()} == {today['id']}
    assert client.get(f"/levels/{yesterday['id']}/events").json() == []
    assert client.get(f"/levels/{future['id']}/events").json() == []
    assert len(client.get('/levels').json()) == 3
    assert client.get('/levels?level_date=2026-09-13').json() == [yesterday]
    assert client.get('/levels?level_date=not-a-date').status_code == 422
    assert client.get('/levels?level_date=2026-09-12').json() == []


@pytest.mark.parametrize('timestamp,expected', [
    ('2026-09-14T18:29:59+00:00', '2026-09-14'),
    ('2026-09-14T18:30:00+00:00', '2026-09-15'),
    ('2026-09-15T00:00:00+05:30', '2026-09-15'),
])
def test_date_defaults_use_kolkata(tmp_path, timestamp, expected):
    with TestClient(create_app(tmp_path / 'date.db', clock=Clock(timestamp))) as client:
        assert create_active_level(client, json=PAYLOAD).json()['level_date'] == expected


def test_naive_clock_rejected():
    with pytest.raises(ValueError, match='timezone-aware'):
        trading_date(datetime(2026, 9, 14))


def test_startup_expires_active_disarmed_and_disabled_preserving_history(tmp_path):
    path, clock = tmp_path / 'startup.db', Clock()
    with TestClient(create_app(path, clock=clock)) as client:
        disarmed = create_active_level(client, json=PAYLOAD).json()
        active = create_active_level(client, json={**PAYLOAD, 'price': 26000}).json()
        disabled = create_active_level(client, json={**PAYLOAD, 'enabled': False}).json()
        publish(client, [24900, 25000])
        events = client.get(f"/levels/{disarmed['id']}/events").json()
        assert events[0]['event_type'] == 'LEVEL_DISARMED'
        trades = client.get('/trades').json()
    clock.set('2026-09-15T08:00:00+05:30')
    with TestClient(create_app(path, clock=clock)) as client:
        rows = client.get('/levels').json()
        assert {r['id'] for r in rows} == {disarmed['id'], active['id'], disabled['id']}
        assert all(r['status'] == 'EXPIRED' and r['level_date'] == '2026-09-14' for r in rows)
        assert client.get(f"/levels/{disarmed['id']}/events").json() == events
        count = len(client.get('/signals').json())
        publish(client, [24000, 25000, 26100, 26000])
        assert len(client.get('/signals').json()) == count
        assert len(client.get('/trades').json()) == len(trades)
        assert client.get(f"/levels/{disarmed['id']}/events").json() == events
        assert client.delete(f"/levels/{active['id']}").status_code == 409
        assert client.put(f"/levels/{disarmed['id']}", json={**PAYLOAD, 'level_date': '2026-09-15'}).status_code == 409
    with TestClient(create_app(path, clock=clock)) as client:
        assert client.get('/levels').json() == rows  # Expiry timestamps remain stable.


def test_expiry_without_ticks_and_websocket_notification(tmp_path):
    clock = Clock('2026-09-14T18:29:59+00:00')
    with TestClient(create_app(tmp_path / 'rollover.db', clock=clock)) as client:
        level = create_active_level(client, json=PAYLOAD).json()
        changed = threading.Event()
        monitor = client.app.state.level_monitor
        original = monitor.on_expired

        def observed(rows):
            original(rows)
            changed.set()

        monitor.on_expired = observed
        with client.websocket_connect('/ws/market') as websocket:
            clock.set('2026-09-14T18:30:00+00:00')
            assert changed.wait(3), 'Background expiry did not run without price ticks'
            message = websocket.receive_json()
            assert message['type'] == 'LEVEL_UPDATED'
            assert message['data']['level']['id'] == level['id']
            assert message['data']['level']['status'] == 'EXPIRED'
        assert client.get(f"/levels/{level['id']}").json()['status'] == 'EXPIRED'
        assert create_active_level(client, json=PAYLOAD).json()['level_date'] == '2026-09-15'


def test_tick_expiry_blocks_old_rearm_even_before_background_check(tmp_path):
    clock = Clock()
    with TestClient(create_app(tmp_path / 'tick.db', clock=clock)) as client:
        level = create_active_level(client, json=PAYLOAD).json()
        publish(client, [24900, 25000])
        old = client.app.state.level_repository.get(level['id'])
        assert old.status == 'DISARMED'
        clock.set('2026-09-15T10:00:00+05:30')
        assert client.app.state.level_repository.rearm(old, 24900, 50, clock()) is False
        publish(client, [24900, 25000])
        assert client.get(f"/levels/{old.id}").json()['status'] == 'EXPIRED'
        assert len(client.get('/signals').json()) == len(client.get('/trades').json()) == 1
        assert len(client.get(f'/levels/{old.id}/events').json()) == 1


def test_execution_rechecks_date_and_expired_is_terminal(tmp_path):
    clock = Clock()
    with TestClient(create_app(tmp_path / 'execution.db', clock=clock, option_prices=SimulatedOptionPrices())) as client:
        level = create_active_level(client, json=PAYLOAD).json()
        publish(client, [24900, 25000])
        signal = SignalResult(**client.get('/signals').json()[0])
        selection = StoredOptionSelection(**client.get('/option-selections').json()[0])
        clock.set('2026-09-15T10:00:00+05:30')
        executor = client.app.state.paper_executor
        executor.prices.set_price(selection.option_symbol, 100)
        assert executor.execute(signal, selection, clock()).failure_reason == 'LEVEL_EXPIRED'
        assert client.get('/trades').json() == []
        client.portal.call(client.app.state.level_monitor.reconcile)
        clock.set('2026-09-14T10:00:00+05:30')
        assert client.app.state.level_repository.list_enabled('NIFTY') == []
        assert executor.execute(signal, selection, clock()).failure_reason == 'LEVEL_EXPIRED'
        assert not client.app.state.level_repository.change_status(level['id'], 'ACTIVE', 24900, clock())


def test_quote_fetch_crossing_midnight_does_not_save_stale_signals(tmp_path):
    clock = Clock()
    with TestClient(create_app(tmp_path / 'quote.db', clock=clock)) as client:
        level = create_active_level(client, json=PAYLOAD).json()
        publish(client, [24900])

        async def delayed_quote(selection):
            clock.set('2026-09-15T10:00:00+05:30')

        client.app.state.paper_executor.prepare = delayed_quote
        publish(client, [25000])
        assert client.get('/signals').json() == []
        assert client.get('/trades').json() == []
        assert client.get('/simulation/events').json() == []
        assert client.get(f"/levels/{level['id']}").json()['status'] == 'EXPIRED'


def test_level_date_cannot_be_edited(client):
    level = create_active_level(client, json=PAYLOAD).json()
    assert client.put(f"/levels/{level['id']}", json={**PAYLOAD, 'level_date': '2026-09-15'}).status_code == 409
    assert client.get(f"/levels/{level['id']}").json() == level


def test_migration_preserves_ids_events_sequence_and_derives_local_date(tmp_path):
    path = tmp_path / 'legacy.db'
    initialize_database(path)
    with connect(path) as c:
        c.execute('DROP TABLE levels')
        c.execute("""CREATE TABLE levels (id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument TEXT NOT NULL, price REAL NOT NULL, enabled INTEGER NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'DISARMED')))""")
        c.execute("INSERT INTO levels VALUES (7, 'NIFTY', 25000, 1, '2026-09-13T20:00:00Z', '2026-09-14T05:00:00Z', 'DISARMED')")
        c.execute("INSERT INTO level_events(level_id, event_type, underlying_price, timestamp) VALUES (7, 'LEVEL_DISARMED', 25000, '2026-09-14T05:00:00Z')")
        c.execute("UPDATE sqlite_sequence SET seq = 99 WHERE name = 'levels'")
        before = dict(c.execute('SELECT * FROM levels').fetchone())
        event = dict(c.execute('SELECT * FROM level_events').fetchone())
    initialize_database(path)
    initialize_database(path)
    with connect(path) as c:
        after = dict(c.execute('SELECT * FROM levels').fetchone())
        assert {key: after[key] for key in before} == before
        assert after['level_date'] == '2026-09-14'
        assert dict(c.execute('SELECT * FROM level_events').fetchone()) == event
    repository = LevelRepository(path, Clock('2026-09-15T10:00:00+05:30'))
    repository.expire_before(repository.clock())
    assert repository.get(7).status == 'EXPIRED'
    assert create_active_record(repository, LevelInput(**PAYLOAD)).id == 100


def test_backtest_levels_use_replay_date_and_expire_on_rollover(client):
    result = run(client)
    assert result['levels'][0]['level_date'] == '2026-09-14'
    assert result['levels'][0]['status'] == 'DISARMED'
    rows = dataset() + [dict(timestamp='2026-09-15T10:00:00+05:30', instrument='NIFTY', price=24900),
                        dict(timestamp='2026-09-15T10:01:00+05:30', instrument='NIFTY', price=25000)]
    result = run(client, rows)
    assert result['levels'][0]['status'] == 'EXPIRED'
    assert len(result['signals']) == len(result['trades']) == 1
    result = run(client, end_time='2026-09-15T00:00:00+05:30')
    assert result['levels'][0]['status'] == 'EXPIRED'
    assert client.get('/backtests/' + result['id']).json() == result
