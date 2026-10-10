import csv
from datetime import datetime
from io import StringIO

import pytest

from app.database import connect
from app.report_csv import CSV_FIELDS, csv_chunks
from test_paper_report import add_trade


URL = '/reports/export'  # Vite/Nginx strip the public /api prefix.
HEADERS = {'X-API-Key': 'report-test-key'}


@pytest.fixture(autouse=True)
def export_key(monkeypatch):
    monkeypatch.setenv('EXTERNAL_LEVELS_API_KEY', HEADERS['X-API-Key'])


def export(client, start='2026-10-03', **params):
    response = client.get(URL, params={'from_date': start, **params}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response, list(csv.DictReader(StringIO(response.text, newline='')))


def add(client, index, timestamp, pnl=None):
    return add_trade(client, index, pnl, entered=datetime.fromisoformat(timestamp.replace('Z', '+00:00')))


def test_single_day_defaults_and_persisted_fields(client):
    trade = add(client, 1, '2026-10-03T09:15:00+05:30', -50)
    opened = add(client, 2, '2026-10-03T09:16:00+05:30')
    add(client, 3, '2026-10-04T09:15:00+05:30', 100)
    response, rows = export(client)
    assert response.headers['content-type'] == 'text/csv; charset=utf-8'
    assert response.headers['content-disposition'] == (
        'attachment; filename="trading-report-PAPER-2026-10-03-2026-10-03.csv"')
    assert [int(row['trade_id']) for row in rows] == [trade.trade_id, opened.trade_id]
    stored = client.get(f'/trades/{trade.trade_id}').json()['trade']
    for field in CSV_FIELDS:
        if field in ('entry_time', 'exit_time'):
            assert datetime.fromisoformat(rows[0][field].replace('Z', '+00:00')) == datetime.fromisoformat(
                stored[field].replace('Z', '+00:00'))
        elif isinstance(stored[field], (float, int)):
            assert float(rows[0][field]) == stored[field]
        else:
            assert rows[0][field] == (stored[field] or '')
    assert rows[0]['realised_pnl'] == '-50.0'  # Numeric losses stay numeric.
    assert rows[1]['exit_time'] == rows[1]['exit_price'] == rows[1]['realised_pnl'] == ''


def test_multiday_export_all_pages_in_exact_timestamp_order(client):
    add(client, 1, '2026-10-02T23:59:59.999999+05:30')
    latest = add(client, 2, '2026-10-04T23:59:59.999999+05:30')
    middle = [add(client, i, '2026-10-03T12:00:00+05:30') for i in range(3, 305)]
    earliest = add(client, 305, '2026-10-03T00:00:00+05:30')
    # SQLite julianday loses microsecond precision. Export uses normalized UTC.
    before_latest = add(client, 306, '2026-10-04T23:59:59.999998+05:30')
    add(client, 307, '2026-10-05T00:00:00+05:30')
    _, rows = export(client, to_date='2026-10-04')
    assert [int(row['trade_id']) for row in rows] == [
        earliest.trade_id, *(trade.trade_id for trade in middle), before_latest.trade_id, latest.trade_id]


def test_kolkata_entry_date_boundaries_and_offsets(client):
    times = [
        '2026-10-02T18:29:59.999999Z', '2026-10-02T18:30:00Z',
        '2026-10-03T00:00:00.000001+05:30', '2026-10-03T18:29:59.999999Z',
        '2026-10-03T18:30:00Z',
    ]
    trades = [add(client, i, timestamp, 10) for i, timestamp in enumerate(times, 1)]
    # Legacy naive timestamps are treated as UTC, just like existing reports.
    with connect(client.app.state.database_path) as connection:
        connection.execute("UPDATE trades SET entry_time = '2026-10-02T18:30:00' WHERE trade_id = ?",
                           (trades[1].trade_id,))
    _, rows = export(client)
    assert [int(row['trade_id']) for row in rows] == [trade.trade_id for trade in trades[1:4]]
    assert all(row['exit_time'].startswith('2026-09-14') for row in rows)


def test_empty_and_extreme_dates_return_headers(client):
    for day in ['2026-10-03', '0001-01-01', '9999-12-31']:
        response, rows = export(client, day)
        assert rows == []
        assert list(csv.reader(StringIO(response.text))) == [list(CSV_FIELDS)]


@pytest.mark.parametrize('params', [
    {}, {'from_date': 'bad'}, {'from_date': '2026-02-30'}, {'from_date': '20261003'},
    {'from_date': '2026-10-03T00:00:00Z'}, {'from_date': '1790985600'},
    {'from_date': '2026-10-04', 'to_date': '2026-10-03'},
    {'from_date': '2026-10-03', 'to_date': ''},
    {'from_date': '2026-10-03', 'to_date': '2026-02-30'},
    {'from_date': '2026-10-03', 'mode': 'LIVE'},
    {'from_date': '2026-10-03', 'mode': 'bad'},
])
def test_invalid_queries(client, params):
    assert client.get(URL, params=params, headers=HEADERS).status_code == 422


@pytest.mark.parametrize('headers', [{}, {'X-API-Key': 'wrong'}])
def test_authentication_required(client, headers):
    response = client.get(URL, params={'from_date': '2026-10-03'}, headers=headers)
    assert response.status_code == 401
    assert 'content-disposition' not in response.headers


def test_unconfigured_auth_fails_closed(client):
    from app.external_levels import ExternalLevelsSettings
    client.app.state.external_levels_settings = ExternalLevelsSettings()
    assert client.get(URL, params={'from_date': '2026-10-03'}, headers=HEADERS).status_code == 503


def test_mode_isolation_and_optional_view_filters(client):
    paper = add(client, 1, '2026-10-03T10:00:00+05:30', 100)
    excluded = add(client, 2, '2026-10-03T11:00:00+05:30')
    backtest = add(client, 3, '2026-10-03T12:00:00+05:30', 500)
    with connect(client.app.state.database_path) as connection:
        connection.execute("UPDATE trades SET trade_mode = 'BACKTEST' WHERE trade_id = ?", (backtest.trade_id,))
        connection.execute('UPDATE trades SET exclude_from_strategy_metrics = 1 WHERE trade_id = ?', (excluded.trade_id,))
    _, raw = export(client)
    assert [int(row['trade_id']) for row in raw] == [paper.trade_id, excluded.trade_id]
    _, strategy = export(client, view='STRATEGY', status='CLOSED', instrument='nifty')
    assert [int(row['trade_id']) for row in strategy] == [paper.trade_id]
    _, other = export(client, mode='BACKTEST')
    assert [int(row['trade_id']) for row in other] == [backtest.trade_id]


@pytest.mark.parametrize('symbol', ['=1+1', '+SUM(A1)', '-1+2', '@SUM(A1)', '  =1+1', '\t=1+1', '\r=1+1', '\n=1+1'])
def test_formula_injection_is_neutralized(client, symbol):
    trade = add(client, 1, '2026-10-03T10:00:00+05:30', -50)
    with connect(client.app.state.database_path) as connection:
        connection.execute('UPDATE trades SET option_symbol = ? WHERE trade_id = ?', (symbol, trade.trade_id))
    _, rows = export(client)
    assert rows[0]['option_symbol'] == "'" + symbol
    assert rows[0]['realised_pnl'] == '-50.0'


def test_csv_quotes_unicode_commas_and_multiline_text(client):
    trade = add(client, 1, '2026-10-03T10:00:00+05:30')
    text = 'निफ्टी, "review"\r\nsecond line'
    with connect(client.app.state.database_path) as connection:
        connection.execute('UPDATE trades SET validity_reason = ? WHERE trade_id = ?', (text, trade.trade_id))
    response, rows = export(client)
    assert rows[0]['validity_reason'] == text
    assert '"निफ्टी, ""review""\r\nsecond line"' in response.text


def test_stream_is_lazy_and_closes_source():
    consumed, closed = [], []

    def source():
        try:
            for i in range(10000):
                consumed.append(i)
                yield dict.fromkeys(CSV_FIELDS, i)
        finally:
            closed.append(True)

    chunks = csv_chunks(source())
    assert next(chunks).startswith('trade_id,')
    assert consumed == []
    next(chunks)
    assert consumed == [0]
    chunks.close()
    assert closed == [True]
