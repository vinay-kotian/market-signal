from datetime import datetime

import pytest

from test_paper_report import add_trade


ENDPOINTS = ['/reports/paper-trading', '/trades/history', '/trades/history/ids']


def add(client, index, timestamp, pnl=10, excluded=False, instrument='NIFTY'):
    trade = add_trade(client, index, pnl, instrument, datetime.fromisoformat(timestamp))
    if excluded:
        response = client.patch(f'/trades/{trade.trade_id}/classification', json=dict(
            validity_status='INVALID_STRATEGY_BUG', reason='Report fixture', exclude_from_strategy_metrics=True))
        assert response.status_code == 200
    return trade.trade_id


def query(client, start, end, **filters):
    params = dict(from_date=start, to_date=end, view='STRATEGY', **filters)
    responses = [client.get(endpoint, params=params) for endpoint in ENDPOINTS]
    assert all(response.status_code == 200 for response in responses)
    return [response.json() for response in responses]


def test_single_day_all_metrics_and_view_reconcile(client):
    add(client, 1, '2026-10-02T10:00:00+05:30', 500)
    ids = [add(client, i, '2026-10-03T10:00:00+05:30', pnl)
           for i, pnl in enumerate([200, 100, -50, -100, 0, None], 2)]
    excluded = add(client, 8, '2026-10-03T11:00:00+05:30', 800, excluded=True)
    add(client, 9, '2026-10-04T10:00:00+05:30', -500)
    report, history, matching = query(client, '2026-10-03', '2026-10-03')
    assert report == dict(view='STRATEGY', recorded_trades=7, included_trades=6,
        excluded_trades=1, total_trades=6, open_trades=1, closed_trades=5,
        winning_trades=2, losing_trades=2, breakeven_trades=1, win_rate=50,
        gross_profit=300, gross_loss=150, net_pnl=150, average_profit=150,
        average_loss=75, maximum_profit=200, maximum_loss=100, profit_factor=2)
    assert history['total'] == report['included_trades'] == report['total_trades']
    assert set(matching) == {trade['trade_id'] for trade in history['items']} == set(ids)
    params = dict(from_date='2026-10-03', to_date='2026-10-03', view='RAW')
    raw = client.get(ENDPOINTS[0], params=params).json()
    raw_history = client.get(ENDPOINTS[1], params=params).json()
    assert raw['total_trades'] == raw_history['total'] == 7
    assert raw['net_pnl'] == 950
    assert {row['trade_id'] for row in raw_history['items']} == set(ids + [excluded])


def test_multiday_range_includes_both_days_and_filters_before_pagination(client):
    add(client, 1, '2026-09-29T23:59:59.999999+05:30', 900)
    ids = [add(client, i, f'2026-{day}T12:00:00+05:30', 10)
           for i, day in enumerate(['09-30', '10-01', '10-02', '10-03'] * 6, 2)]
    add(client, 26, '2026-10-04T00:00:00+05:30', 900)
    report, first, matching = query(client, '2026-09-30', '2026-10-03')
    report_page_two, second, matching_two = query(client, '2026-09-30', '2026-10-03', page=2)
    assert first['total'] == second['total'] == report['total_trades'] == 24
    assert len(first['items']) == 20 and len(second['items']) == 4
    assert report['net_pnl'] == 240
    assert report_page_two == report
    assert set(matching) == set(matching_two) == set(ids)
    assert {row['trade_id'] for row in first['items'] + second['items']} == set(ids)


def test_kolkata_boundaries_preserve_microseconds_and_use_entry_not_exit(client):
    times = [
        '2026-10-02T18:29:59.999999+00:00',  # Before selected start.
        '2026-10-02T18:30:00+00:00',         # Exactly local midnight.
        '2026-10-03T00:00:00.000001+05:30',
        '2026-10-03T18:29:59.999999+00:00',  # Last microsecond of selected day.
        '2026-10-03T23:59:59.999999+05:30',
        '2026-10-03T18:30:00+00:00',         # Next local midnight.
    ]
    ids = [add(client, i, timestamp) for i, timestamp in enumerate(times, 1)]
    # add_trade's exit timestamps are in September; report must use October entry.
    report, history, matching = query(client, '2026-10-03', '2026-10-03')
    assert report['net_pnl'] == 40
    assert report['total_trades'] == history['total'] == 4
    assert set(matching) == {row['trade_id'] for row in history['items']} == set(ids[1:5])
    legacy = client.get('/trades/by-date', params={'date': '2026-10-03'}).json()
    assert {row['trade_id'] for row in legacy} == set(matching)


@pytest.mark.parametrize('endpoint', ENDPOINTS)
@pytest.mark.parametrize('start,end', [
    ('2026-10-04', '2026-10-03'), ('bad', '2026-10-03'),
    ('2026-02-30', '2026-10-03'), ('2026-10-03', ''),
])
def test_invalid_ranges_rejected(client, endpoint, start, end):
    assert client.get(endpoint, params=dict(from_date=start, to_date=end)).status_code == 422


def test_empty_range_and_status_instrument_filters_reconcile(client):
    add(client, 1, '2026-10-03T10:00:00+05:30', None, instrument='BANKNIFTY')
    included = add(client, 2, '2026-10-03T10:00:00+05:30', 25, instrument='BANKNIFTY')
    add(client, 3, '2026-10-03T10:00:00+05:30', 50, instrument='NIFTY')
    report, history, matching = query(client, '2026-10-03', '2026-10-03', status='CLOSED', instrument='banknifty')
    assert report['total_trades'] == history['total'] == 1
    assert report['net_pnl'] == 25
    assert matching == [included]
    report, history, matching = query(client, '2026-10-05', '2026-10-05')
    assert report['total_trades'] == report['recorded_trades'] == report['net_pnl'] == history['total'] == 0
    assert history['items'] == matching == []
    assert report['profit_factor'] is None


def test_default_view_is_consistent_for_all_endpoints(client):
    included = add(client, 1, '2026-10-03T10:00:00+05:30')
    add(client, 2, '2026-10-03T10:00:00+05:30', excluded=True)
    params = dict(from_date='2026-10-03', to_date='2026-10-03')
    report, history, ids = [client.get(endpoint, params=params).json() for endpoint in ENDPOINTS]
    assert report['total_trades'] == history['total'] == 1
    assert ids == [included]
