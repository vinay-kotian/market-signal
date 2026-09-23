from fastapi.testclient import TestClient

from app.database import connect, initialize_database
from app.main import create_app
from app.settings import TradeSettings, SignalSettings, OptionSettings
from app.trade_repository import TradeRepository
from test_paper_report import add_trade
from test_paper_trades import add_level, publish
from test_backtests import run


def test_classification_reports_history_and_restart(client):
    winner = add_trade(client, 1, 200)
    loser = add_trade(client, 2, -100)
    assert winner.validity_status == 'VALID'
    assert winner.validity_reason is None
    assert winner.exclude_from_strategy_metrics is False
    before = client.get(f'/trades/{loser.trade_id}').json()
    classification = dict(validity_status='INVALID_STRATEGY_BUG',
                          reason='Repeated entry caused by level rearm bug',
                          exclude_from_strategy_metrics=True)
    response = client.patch(f'/trades/{loser.trade_id}/classification', json=classification)
    assert response.status_code == 200
    after = client.get(f'/trades/{loser.trade_id}').json()
    assert after['events'] == before['events']
    for key, value in before['trade'].items():
        if key not in ('validity_status', 'validity_reason', 'exclude_from_strategy_metrics'):
            assert after['trade'][key] == value
    assert client.get('/trades/history').json()['total'] == 2
    assert len(client.get('/trades').json()) == 2
    strategy = client.get('/reports/paper-trading').json()
    assert (strategy['recorded_trades'], strategy['included_trades'], strategy['excluded_trades']) == (2, 1, 1)
    assert strategy['net_pnl'] == 200
    assert strategy['win_rate'] == 100
    assert strategy['profit_factor'] is None
    raw = client.get('/reports/paper-trading?view=RAW').json()
    assert raw['total_trades'] == 2
    assert raw['net_pnl'] == 100
    assert raw['win_rate'] == 50
    assert raw['profit_factor'] == 2
    with TestClient(create_app(client.app.state.database_path)) as restarted:
        assert restarted.get(f'/trades/{loser.trade_id}').json() == after
        assert restarted.patch(f'/trades/{loser.trade_id}/classification', json=dict(
            validity_status='VALID', reason='Reviewed', exclude_from_strategy_metrics=False)).status_code == 200
    assert client.get('/reports/paper-trading').json()['net_pnl'] == 100
    assert client.get(f'/trades/{loser.trade_id}/events').json() == before['events']


def test_classification_validation_and_scope(client):
    trade = add_trade(client)
    payload = dict(validity_status='MANUAL_REVIEW', reason='Investigating', exclude_from_strategy_metrics=False)
    assert client.patch('/trades/99999/classification', json=payload).status_code == 404
    for override in ({'validity_status': 'BAD'}, {'entry_price': 123}, {'settings_snapshot': {}}):
        assert client.patch(f'/trades/{trade.trade_id}/classification', json={**payload, **override}).status_code == 422
    assert client.get('/reports/paper-trading?view=BAD').status_code == 422
    with connect(client.app.state.database_path) as connection:
        connection.execute("UPDATE trades SET trade_mode = 'BACKTEST' WHERE trade_id = ?", (trade.trade_id,))
    assert client.patch(f'/trades/{trade.trade_id}/classification', json=payload).status_code == 404


def test_entry_snapshot_and_version_survive_settings_changes(tmp_path, monkeypatch):
    monkeypatch.setenv('STRATEGY_VERSION', '1.2.3')
    settings = TradeSettings(number_of_lots=3, level_rearm_distance_points=75)
    signals = SignalSettings(lookback_minutes=12, minimum_approach_distance_enabled=True,
                             minimum_approach_distance_points=20)
    options = OptionSettings(itm_depth=2)
    path = tmp_path / 'snapshot.sqlite3'
    with TestClient(create_app(path, trade_settings=settings, signal_settings=signals, option_settings=options)) as client:
        add_level(client)
        publish(client, [24900, 25000])
        trade, = client.get('/trades').json()
        expected = {**signals.model_dump(mode='json'), **options.model_dump(mode='json'),
                    **settings.model_dump(mode='json'), 'timezone': 'Asia/Kolkata', 'initial_arm_distance_points': 30}
        assert trade['settings_snapshot'] == expected
        assert trade['strategy_version'] == '1.2.3'
        assert trade['validity_status'] == 'VALID'
        settings.number_of_lots = 7
        signals.lookback_minutes = 5
        options.itm_depth = 1
        assert client.get('/trades').json()[0]['settings_snapshot'] == expected
    monkeypatch.setenv('STRATEGY_VERSION', '2.0.0')
    with TestClient(create_app(path)) as client:
        saved = client.get('/trades').json()[0]
        assert saved['settings_snapshot'] == expected
        assert saved['strategy_version'] == '1.2.3'


def test_existing_trades_migrate_without_changing_execution(client):
    trade = add_trade(client, pnl=200)
    path = client.app.state.database_path
    metadata = ('strategy_version', 'validity_status', 'validity_reason',
                'exclude_from_strategy_metrics', 'settings_snapshot')
    with connect(path) as connection:
        for name in metadata:
            connection.execute(f'ALTER TABLE trades DROP COLUMN {name}')
        before = dict(connection.execute('SELECT * FROM trades').fetchone())
        events = [dict(row) for row in connection.execute('SELECT * FROM trade_events')]
    initialize_database(path)
    initialize_database(path)
    with connect(path) as connection:
        after = dict(connection.execute('SELECT * FROM trades').fetchone())
        assert {key: after[key] for key in before} == before
        assert [dict(row) for row in connection.execute('SELECT * FROM trade_events')] == events
    saved = TradeRepository(path).recent()[0]
    assert saved.trade_id == trade.trade_id
    assert saved.strategy_version == 'UNKNOWN'
    assert saved.validity_status == 'MANUAL_REVIEW'
    assert saved.settings_snapshot == {'provenance': 'LEGACY_UNAVAILABLE'}
    assert saved.exclude_from_strategy_metrics is False
    assert client.get('/reports/paper-trading').json()['net_pnl'] == 200


def test_backtest_version_and_snapshot_persist(client, monkeypatch):
    monkeypatch.setenv('STRATEGY_VERSION', '3.1.0')
    result = run(client, lookback_minutes=8, itm_depth=1)
    assert result['strategy_version'] == '3.1.0'
    trade, = result['trades']
    assert trade['strategy_version'] == '3.1.0'
    assert trade['settings_snapshot']['lookback_minutes'] == 8
    monkeypatch.setenv('STRATEGY_VERSION', '4.0.0')
    assert client.get('/backtests/' + result['id']).json() == result
