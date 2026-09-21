from datetime import datetime
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import create_app
from test_paper_report import add_trade


PAYLOAD = dict(validity_status='INVALID_STRATEGY_BUG',
               reason='Repeated trades caused by level re-arm bug',
               exclude_from_strategy_metrics=True)


def snapshot(client):
    with connect(client.app.state.database_path) as connection:
        return {table: [dict(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY 1')]
                for table in ('trades', 'trade_events', 'trade_entry_results')}


def test_bulk_persists_only_metadata_and_can_be_reversed(client):
    first = add_trade(client, 1, 200)
    second = add_trade(client, 2, -50)
    untouched = add_trade(client, 3, 100)
    before = snapshot(client)
    response = client.patch('/trades/classification/bulk', json={**PAYLOAD, 'trade_ids': [first.trade_id, second.trade_id]})
    assert response.status_code == 200, response.text
    assert [row['trade_id'] for row in response.json()] == [first.trade_id, second.trade_id]
    after = snapshot(client)
    assert after['trade_events'] == before['trade_events']
    assert after['trade_entry_results'] == before['trade_entry_results']
    for original, updated in zip(before['trades'], after['trades']):
        if original['trade_id'] == untouched.trade_id:
            assert updated == original
        else:
            assert updated['validity_status'] == PAYLOAD['validity_status']
            assert updated['validity_reason'] == PAYLOAD['reason']
            assert updated['exclude_from_strategy_metrics'] == 1
            for key in original.keys() - {'validity_status', 'validity_reason', 'exclude_from_strategy_metrics'}:
                assert updated[key] == original[key], key  # Includes every execution field and timestamp.
    raw = client.get('/reports/paper-trading?view=RAW').json()
    strategy = client.get('/reports/paper-trading?view=STRATEGY').json()
    assert raw['total_trades'] == 3 and raw['net_pnl'] == 250
    assert strategy['total_trades'] == 1 and strategy['net_pnl'] == 100
    assert strategy['recorded_trades'] == 3 and strategy['excluded_trades'] == 2
    assert client.get('/trades/history').json()['total'] == 3
    assert len(client.get('/trades/by-date?date=2026-09-14').json()) == 3
    with TestClient(create_app(client.app.state.database_path)) as restarted:
        assert snapshot(restarted) == after
        response = restarted.patch('/trades/classification/bulk', json=dict(
            trade_ids=[first.trade_id, second.trade_id], validity_status='VALID',
            reason='Reviewed and restored', exclude_from_strategy_metrics=False))
        assert response.status_code == 200
    assert client.get('/reports/paper-trading').json()['net_pnl'] == 250
    assert snapshot(client)['trade_events'] == before['trade_events']
    for trade in client.get('/trades').json():
        assert trade['validity_status'] == 'VALID'
        assert not trade['exclude_from_strategy_metrics']


@pytest.mark.parametrize('ids', [[], [0], [-1], [True], ['1'], [9223372036854775808]])
def test_invalid_ids_are_rejected_safely(client, ids):
    add_trade(client)
    before = snapshot(client)
    assert client.patch('/trades/classification/bulk', json={**PAYLOAD, 'trade_ids': ids}).status_code == 422
    assert snapshot(client) == before


def test_missing_or_non_paper_target_rejects_entire_batch(client):
    first, second = add_trade(client, 1), add_trade(client, 2)
    with connect(client.app.state.database_path) as connection:
        connection.execute("UPDATE trades SET trade_mode = 'BACKTEST' WHERE trade_id = ?", (second.trade_id,))
    before = snapshot(client)
    for target in [second.trade_id, 999999]:
        response = client.patch('/trades/classification/bulk', json={**PAYLOAD, 'trade_ids': [first.trade_id, target]})
        assert response.status_code == 404
        assert snapshot(client) == before


def test_duplicate_ids_and_forbidden_execution_fields(client):
    trade = add_trade(client)
    before = snapshot(client)
    assert client.patch('/trades/classification/bulk', json={**PAYLOAD, 'trade_ids': [trade.trade_id], 'entry_price': 123}).status_code == 422
    assert snapshot(client) == before
    response = client.patch('/trades/classification/bulk', json={**PAYLOAD, 'trade_ids': [trade.trade_id, trade.trade_id]})
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_write_failure_rolls_back_entire_batch(client):
    first, second = add_trade(client, 1), add_trade(client, 2)
    before = snapshot(client)
    with connect(client.app.state.database_path) as connection:
        connection.execute(f"""CREATE TRIGGER fail_bulk BEFORE UPDATE OF validity_status ON trades
            WHEN NEW.trade_id = {second.trade_id} BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        client.patch('/trades/classification/bulk', json={**PAYLOAD, 'trade_ids': [first.trade_id, second.trade_id]})
    assert snapshot(client) == before


def test_by_date_kolkata_boundaries_and_paper_scope(client):
    times = ['2026-09-13T18:29:59+00:00', '2026-09-13T18:30:00+00:00',
             '2026-09-14T23:59:59+05:30', '2026-09-14T18:30:00+00:00']
    trades = [add_trade(client, index, entered=datetime.fromisoformat(timestamp)) for index, timestamp in enumerate(times, 1)]
    other = add_trade(client, 5)
    with connect(client.app.state.database_path) as connection:
        connection.execute("UPDATE trades SET trade_mode = 'BACKTEST' WHERE trade_id = ?", (other.trade_id,))
    response = client.get('/trades/by-date?date=2026-09-14')
    assert response.status_code == 200
    assert [trade['trade_id'] for trade in response.json()] == [trades[2].trade_id, trades[1].trade_id]
    assert client.get('/trades/by-date?date=2026-09-12').json() == []
    assert client.get('/trades/by-date').status_code == 422
    assert client.get('/trades/by-date?date=bad').status_code == 422
    assert client.get('/trades/by-date?date=9999-12-31').status_code == 200


def test_by_date_and_bulk_not_limited_to_a_page_or_latest_hundred(client):
    ids = [add_trade(client, index).trade_id for index in range(1, 103)]
    assert len(client.get('/trades/by-date?date=2026-09-14').json()) == 102
    response = client.patch('/trades/classification/bulk', json={**PAYLOAD, 'trade_ids': ids})
    assert response.status_code == 200 and len(response.json()) == 102
    assert client.get('/reports/paper-trading').json()['excluded_trades'] == 102
