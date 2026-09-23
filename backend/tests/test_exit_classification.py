import pytest
from fastapi.testclient import TestClient

from app.database import connect, initialize_database
from app.main import create_app
from app.settings import TradeSettings
from test_backtests import dataset, run
from test_trailing_stop import enter, send, events


@pytest.mark.parametrize('prices,settings,expected,stop', [
    ([90], {}, 'STOP_LOSS', 90),
    ([85], {}, 'STOP_LOSS', 90),
    ([105, 94.5], {}, 'TRAILING_STOP_LOSS', 94.5),
    ([120, 108], {}, 'TRAILING_STOP_LOSS', 108),
    ([110, 100], {}, 'TRAILING_STOP_LOSS', 100),
    ([110, 101], {'breakeven_lock_percent': 1}, 'TRAILING_STOP_LOSS', 101),
    ([120, 99], {}, 'TRAILING_STOP_LOSS', 108),
    ([112.5, 90], {'trailing_stop_percentage': 20, 'breakeven_protection_enabled': False}, 'STOP_LOSS', 90),
    # A tighter trailing percentage can advance AND hit protection on the first
    # option tick. The Trade object still has 90, but the triggering stop is 95.
    ([94], {'trailing_stop_percentage': 5, 'breakeven_protection_enabled': False}, 'TRAILING_STOP_LOSS', 95),
])
def test_paper_and_backtest_classify_from_triggering_stop(tmp_path, prices, settings, expected, stop):
    with TestClient(create_app(tmp_path / 'classification.sqlite3', trade_settings=TradeSettings(**settings))) as client:
        trade = enter(client)
        for price in prices:
            closed = send(client, trade, price)
        assert closed['status'] == 'CLOSED'
        assert closed['initial_stop_loss'] == 90
        assert closed['current_stop_loss'] == stop
        assert closed['exit_reason'] == expected
        assert closed['exit_price'] == prices[-1]
        assert closed['realised_pnl'] == (prices[-1] - 100) * 10
        assert client.get('/trades/history').json()['items'][0]['exit_reason'] == expected
        assert client.get(f"/trades/{trade['trade_id']}").json()['trade']['exit_reason'] == expected
        history = events(client, trade)
        assert [event['event_type'] for event in history][-2:] == ['STOP_LOSS_HIT', 'POSITION_CLOSED']
        assert send(client, trade, 80) == closed
        assert events(client, trade) == history

        replay = run(client, dataset([(f'10:{i + 2:02d}:00', price) for i, price in enumerate(prices)]), **settings)
        backtest_trade, = replay['trades']
        for field in ('exit_reason', 'initial_stop_loss', 'current_stop_loss', 'exit_price', 'realised_pnl'):
            assert backtest_trade[field] == closed[field]
        assert backtest_trade['trade_mode'] == 'BACKTEST'


@pytest.mark.parametrize('reason,closing_events', [
    ('MARKET_CLOSING_EXIT', ['MARKET_CLOSING_EXIT_TRIGGERED', 'POSITION_CLOSED']),
    ('MANUAL_SQUARE_OFF', ['POSITION_CLOSED']),
])
def test_explicit_non_stop_reason_is_preserved_with_advanced_protection(client, reason, closing_events):
    trade = enter(client)
    send(client, trade, 120)
    repository = client.app.state.trade_repository
    current = repository.recent()[0]
    with connect(repository.database_path) as connection:
        assert repository.close(current, 99, current.entry_time, reason, connection)
        assert not repository.close(current, 98, current.entry_time, reason, connection)
    closed = client.get('/trades').json()[0]
    assert closed['exit_reason'] == reason
    assert closed['current_stop_loss'] == 108
    kinds = [event['event_type'] for event in events(client, trade)]
    assert kinds[-len(closing_events):] == closing_events
    assert 'STOP_LOSS_HIT' not in kinds
    assert kinds.count('POSITION_CLOSED') == 1
    assert send(client, trade, 80) == closed


def test_restart_keeps_legacy_closed_reasons_and_events(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with TestClient(create_app(path)) as client:
        trade = enter(client)
        send(client, trade, 120)
        send(client, trade, 108)
        # A pre-feature closed record may have an advanced stop but STOP_LOSS.
        with connect(path) as connection:
            connection.execute("UPDATE trades SET exit_reason = 'STOP_LOSS'")
        legacy = client.get('/trades').json()
        history = events(client, trade)
    initialize_database(path)
    initialize_database(path)
    with TestClient(create_app(path)) as client:
        assert client.get('/trades').json() == legacy
        assert events(client, trade) == history
        assert send(client, trade, 90) == legacy[0]


def test_advanced_stop_exit_and_events_roll_back_together(tmp_path):
    path = tmp_path / 'rollback.sqlite3'
    with TestClient(create_app(path), raise_server_exceptions=False) as client:
        trade = enter(client)
        protected = send(client, trade, 120)
        history = events(client, trade)
        with connect(path) as connection:
            connection.execute("""CREATE TRIGGER fail_close BEFORE INSERT ON trade_events
                WHEN NEW.event_type = 'POSITION_CLOSED'
                BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        assert client.post('/simulation/tick', json=dict(instrument=trade['option_symbol'], price=99)).status_code == 500
        assert client.get('/trades').json()[0] == protected
        assert events(client, trade) == history
        with connect(path) as connection:
            connection.execute('DROP TRIGGER fail_close')
        assert send(client, trade, 99)['exit_reason'] == 'TRAILING_STOP_LOSS'
