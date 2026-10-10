from datetime import datetime
import pytest
from app.database import connect
from test_paper_report import add_trade


def add(client, index, pnl, strategy='LEGACY', risk=100, exit_time=None, excluded=False, entered='2026-10-03T10:00:00+05:30', instrument='NIFTY', mode='PAPER', reason='STOP_LOSS'):
    trade = add_trade(client, index, pnl, instrument, datetime.fromisoformat(entered.replace('Z', '+00:00')))
    with connect(client.app.state.database_path) as connection:
        connection.execute('UPDATE trades SET strategy_type=?, initial_risk_amount=?, exit_time=?, exclude_from_strategy_metrics=?, trade_mode=?, exit_reason=? WHERE trade_id=?',
            (strategy, risk, (exit_time or entered) if pnl is not None else None, excluded, mode, reason if pnl is not None else None, trade.trade_id))
    return trade


def query(client, **params):
    response = client.get('/reports/strategy-comparison', params=dict(from_date='2026-10-03', to_date='2026-10-03', **params))
    assert response.status_code == 200, response.text
    return response.json()


def test_metrics_reuse_reports_include_all_rows_and_order_exits(client):
    # Insert out of chronological order, including mixed UTC/IST offsets.
    add(client, 1, -100, exit_time='2026-10-03T06:00:00Z')
    add(client, 2, 200, exit_time='2026-10-03T10:00:00+05:30')
    add(client, 3, -50, exit_time='2026-10-03T11:00:00+05:30', risk=None, reason='MANUAL_SQUARE_OFF')
    add(client, 4, 0, exit_time='2026-10-03T12:00:00+05:30', risk=0)
    add(client, 5, None)
    add(client, 6, 300, 'ATR', exit_time='2026-10-03T10:00:00+05:30')
    add(client, 7, -50, 'ATR', exit_time='2026-10-03T10:30:00+05:30')
    result = query(client)
    legacy, atr = (result['strategies'][strategy] for strategy in ('LEGACY', 'ATR'))
    assert legacy['total_trades'] == 5 and legacy['win_rate'] == pytest.approx(100/3)
    assert legacy['net_pnl'] == 50 and legacy['profit_factor'] == pytest.approx(4/3)
    assert legacy['max_drawdown'] == 150
    assert legacy['average_r'] == .5 and legacy['average_r_sample_size'] == 2
    assert legacy['sl_hits'] == 3
    assert atr['net_pnl'] == 250 and atr['profit_factor'] == 6 and atr['max_drawdown'] == 50
    assert atr['average_r'] == 1.25 and atr['sl_hits'] == 2
    assert result['costs_included'] is False
    for strategy in ('LEGACY', 'ATR'):
        existing = client.get('/reports/paper-trading', params=dict(from_date='2026-10-03', to_date='2026-10-03', strategy_type=strategy)).json()
        assert all(result['strategies'][strategy][key] == value for key, value in existing.items())


def test_range_view_filters_and_backtest_isolation(client):
    add(client, 1, 100, 'ATR', excluded=True)
    add(client, 2, 50, 'LEGACY', mode='BACKTEST')
    add(client, 3, 400, 'ATR', entered='2026-10-03T18:30:00Z')  # next IST date
    add(client, 4, 25, entered='2026-10-02T18:30:00Z', instrument='BANKNIFTY')
    assert query(client)['strategies']['ATR']['total_trades'] == 0
    assert query(client, view='RAW')['strategies']['ATR']['net_pnl'] == 100
    assert query(client)['strategies']['LEGACY']['net_pnl'] == 25
    assert query(client, instrument='NIFTY')['strategies']['LEGACY']['total_trades'] == 0
    assert query(client, status='OPEN')['strategies']['LEGACY']['total_trades'] == 0
    # History strategy filters never hide the other strategy's comparison column.
    assert query(client, view='RAW', strategy_type='LEGACY')['strategies']['ATR']['net_pnl'] == 100
    response = client.get('/reports/strategy-comparison?from_date=2026-10-03&to_date=2026-10-04&view=RAW').json()
    assert response['strategies']['ATR']['net_pnl'] == 500


def test_empty_unknown_r_and_no_loss_states(client):
    result = query(client)
    for group in result['strategies'].values():
        assert group['total_trades'] == group['max_drawdown'] == group['sl_hits'] == 0
        assert group['average_r'] is None and group['profit_factor'] is None
    add(client, 1, 100, risk=None)
    group = query(client)['strategies']['LEGACY']
    assert group['average_r'] is None and group['average_r_sample_size'] == 0
    assert group['profit_factor'] is None and group['max_drawdown'] == 0


def test_unpaginated_comparison(client):
    for index in range(1, 26): add(client, index, 10, strategy='ATR')
    assert query(client, page=2)['strategies']['ATR']['total_trades'] == 25
    assert query(client)['strategies']['ATR']['net_pnl'] == 250


@pytest.mark.parametrize('query_string', ['from_date=bad', 'from_date=2026-02-30', 'from_date=2026-10-04&to_date=2026-10-03', 'view=UNKNOWN', 'status=UNKNOWN'])
def test_invalid_queries(client, query_string):
    assert client.get(f'/reports/strategy-comparison?{query_string}').status_code == 422


def test_drawdown_preserves_exit_microsecond_order(client):
    add(client, 1, -50, exit_time='2026-10-03T10:00:00.000002+05:30')
    add(client, 2, 100, exit_time='2026-10-03T10:00:00.000001+05:30')
    add(client, 3, -50, exit_time='2026-10-03T10:00:00.000003+05:30')
    assert query(client)['strategies']['LEGACY']['max_drawdown'] == 100
