from datetime import datetime
import json
from uuid import uuid4

import pytest
from app.database import connect
from app.option_models import OptionSelection
from app.backtests import BacktestRunner
from test_signal_filters import save


def selection(client, timestamp):
    timestamp = timestamp.replace('Z', '+00:00')
    signal = save(client, timestamp)
    return client.app.state.option_repository.save(signal.id, OptionSelection(
        instrument='NIFTY', trigger_price=25000, direction='FROM_BELOW',
        option_type='CE', itm_depth=1, status='FAILED', failure_reason='MISSING_OPTION_CONTRACT'),
        datetime.fromisoformat(timestamp))


def test_signal_and_selection_exact_midnight_boundaries_and_restart(client):
    times = ['2026-10-02T18:29:59.999999Z', '2026-10-02T18:30:00Z',
             '2026-10-03T23:59:59.999999+05:30', '2026-10-03T18:30:00Z']
    rows = [selection(client, timestamp) for timestamp in times]
    params = dict(from_date='2026-10-03', to_date='2026-10-03')
    assert [row['id'] for row in client.get('/option-selections', params=params).json()] == [rows[2].id, rows[1].id]
    assert [row['id'] for row in client.get('/signals', params=params).json()] == [rows[2].signal_id, rows[1].signal_id]
    history = client.get('/option-selections/history', params=params).json()
    assert history['total'] == 2
    from app.option_repository import OptionSelectionRepository
    from datetime import date
    restarted = OptionSelectionRepository(client.app.state.database_path)
    assert len(restarted.recent(from_date=date(2026, 10, 3), to_date=date(2026, 10, 3))) == 2
    assert len(client.get('/option-selections').json()) == 4


def test_option_scope_filters_before_pagination_and_recent_limit(client):
    matches = [selection(client, '2026-10-03T10:00:00+05:30') for _ in range(25)]
    for _ in range(105):
        selection(client, '2026-10-04T10:00:00+05:30')
    params = dict(from_date='2026-10-03', to_date='2026-10-03')
    first = client.get('/option-selections/history', params=params).json()
    second = client.get('/option-selections/history', params={**params, 'page': 2}).json()
    assert first['total'] == second['total'] == 25
    assert [row['id'] for row in first['items'] + second['items']] == [row.id for row in reversed(matches)]
    assert len(client.get('/option-selections', params=params).json()) == 25
    assert client.get('/option-selections/history', params={**params, 'page': 0}).status_code == 422


@pytest.mark.parametrize('endpoint', ['/signals', '/option-selections', '/option-selections/history', '/backtests'])
@pytest.mark.parametrize('start,end', [('2026-10-04', '2026-10-03'), ('bad', '2026-10-03'), ('2026-02-30', '2026-10-03')])
def test_invalid_date_scopes(client, endpoint, start, end):
    assert client.get(endpoint, params=dict(from_date=start, to_date=end)).status_code == 422


def test_run_history_uses_creation_time_not_simulation_day_and_persists(client):
    runner = client.app.state.backtest_runner
    timestamps = ['2026-10-02T18:29:59.999999Z', '2026-10-02T18:30:00Z',
                  '2026-10-03T23:59:59.999999+05:30', '2026-10-03T18:30:00Z']
    ids = []
    for timestamp in timestamps:
        run_id = str(uuid4()); ids.append(run_id)
        directory = runner.directory / run_id
        directory.mkdir(parents=True)
        result = dict(id=run_id, trading_date='2026-09-14', instrument='NIFTY', status='COMPLETED', created_at=timestamp)
        with connect(directory / 'results.sqlite3') as connection:
            connection.execute('CREATE TABLE backtest_run (created_at TEXT, result TEXT)')
            connection.execute('INSERT INTO backtest_run VALUES (?, ?)', (timestamp, json.dumps(result)))
    rows = client.get('/backtests', params=dict(from_date='2026-10-03', to_date='2026-10-03')).json()
    assert {row['id'] for row in rows} == set(ids[1:3])
    assert len(BacktestRunner(runner.directory).list()) == 4
    assert client.get('/option-selections').json() == []
    assert client.get('/trades').json() == []


def test_entry_premium_is_only_read_from_paper_and_report_scope_isolated(client):
    from test_paper_report import add_trade
    selected = selection(client, '2026-10-03T10:00:00+05:30')
    trade = add_trade(client, selected.id, pnl=25, entered=datetime.fromisoformat('2026-10-03T10:00:00+05:30'))
    params = dict(from_date='2026-10-03', to_date='2026-10-03')
    assert client.get('/option-selections/history', params=params).json()['items'][0]['entry_premium'] == 100
    with connect(client.app.state.database_path) as connection:
        connection.execute("UPDATE trades SET trade_mode='BACKTEST' WHERE trade_id=?", (trade.trade_id,))
    assert client.get('/option-selections/history', params=params).json()['items'][0]['entry_premium'] is None
    assert client.get('/trades/history', params=params).json()['total'] == 0
    assert client.get('/reports/paper-trading', params=params).json()['total_trades'] == 0


def test_event_history_filters_exact_occurrence_boundaries(client):
    from test_paper_report import add_trade
    trade = add_trade(client)
    times = ['2026-10-02T18:29:59.999999+00:00', '2026-10-02T18:30:00+00:00',
             '2026-10-03T23:59:59.999999+05:30', '2026-10-03T18:30:00+00:00']
    with connect(client.app.state.database_path) as connection:
        for index, timestamp in enumerate(times):
            client.app.state.trade_events.record(trade.trade_id, 'TRAILING_STOP_UPDATED', 100,
                datetime.fromisoformat(timestamp), connection, previous_stop=90 + index, current_stop=95 + index)
    params = dict(from_date='2026-10-03', to_date='2026-10-03')
    events = client.get(f'/trades/{trade.trade_id}/events', params=params).json()
    assert len(events) == 2
    assert len(client.get(f'/trades/{trade.trade_id}/events').json()) >= 4
    assert client.get(f'/trades/{trade.trade_id}/events', params=dict(from_date='2026-10-04', to_date='2026-10-03')).status_code == 422
    # Instrument view uses the same exact day boundaries for its recorded signals.
    for timestamp in times:
        save(client, timestamp)
    signals = [row for row in client.get('/instruments/NIFTY/events', params={'date': '2026-10-03'}).json()['events']
               if row['event_type'] == 'SIGNAL_GENERATED']
    assert len(signals) == 2
