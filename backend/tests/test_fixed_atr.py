"""Strategy 3 specifications plus shared PAPER/BACKTEST integration."""
from datetime import datetime, timedelta
import pytest
from pydantic import ValidationError
from app.fixed_atr import (IST, FixedAtrSettings, OptionMinuteCandle, entry_plan,
                           simulate_trade)
from app.fixed_atr_data import FixedAtrData
from app.database import connect, initialize_database
from test_atr_exit import configure
from test_position_monitor import enter, tick
from test_backtests import CONTRACTS, SYMBOL, dataset, run, post

def run_async(coroutine):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


def strategy_dataset():
    return [{**r, 'timestamp': r['timestamp'].replace('10:01:00', '10:00:00').replace('10:01:01', '10:00:00')} for r in dataset()]


ENTRY = datetime(2026, 9, 14, 10, tzinfo=IST)


def candle(start, low=98, high=102, close=100, symbol=SYMBOL):
    return OptionMinuteCandle(symbol=symbol, timestamp=start, open=100, high=high, low=low, close=close)


def history(count=15):
    return [candle(ENTRY-timedelta(minutes=count-i)) for i in range(count)]


def plan(rows=None, **settings):
    return entry_plan(100, ENTRY, SYMBOL, history() if rows is None else rows, FixedAtrSettings(**settings))


def simulate(rows, entry_time=ENTRY, **kwargs):
    return simulate_trade(trade_id='excel-1', instrument='NIFTY', option_symbol=SYMBOL,
        entry_time=entry_time, entry_price=100, quantity=10, candles=rows, **kwargs)


def test_full_and_fractional_sma_formula():
    result = plan()
    assert result['atr_value'] == 4 and result['atr_sample_count'] == 14
    assert result['initial_stop'] == 97 and result['target'] == 106
    assert result['stop_distance'] == 3 and result['initial_risk_pct'] == 3
    assert result['stop_source'] == 'ATR'


def test_sma_is_not_wilder_and_first_candle_has_no_tr():
    rows = history(4)
    rows[-1] = candle(rows[-1].timestamp, low=90, high=110)
    result = plan(rows, atr_period=2)
    assert result['atr_value'] == 12 and result['atr_sample_count'] == 2
    assert plan(history(2))['atr_sample_count'] == 1
    assert plan(history(2))['atr_value'] == 4


@pytest.mark.parametrize('rows,reason', [([], 'INSUFFICIENT_PRE_ENTRY_CANDLES'),
    (history(1), 'INSUFFICIENT_PRE_ENTRY_CANDLES'),
    ([candle(c.timestamp, low=100, high=100) for c in history(3)], 'ATR_UNAVAILABLE_OR_INVALID'),
    ([candle(c.timestamp, low=0, high=400) for c in history(3)], 'ATR_STOP_INVALID')])
def test_fallback(rows, reason):
    result = plan(rows)
    assert result['initial_stop'] == 80 and result['target'] == 140
    assert result['fallback_reason'] == reason and result['stop_source'] == 'FALLBACK'


@pytest.mark.parametrize('settings', [dict(atr_multiplier=0), dict(atr_multiplier=float('nan')),
    dict(fallback_sl_pct=100), dict(fallback_sl_pct=-1), dict(atr_method='WILDER'),
    dict(risk_reward_ratio=0), dict(eod_exit_time='15:25:01')])
def test_invalid_settings_rejected(settings):
    with pytest.raises(ValidationError):
        FixedAtrSettings(**settings)


def test_invalid_fallback_defensive_check():
    broken = FixedAtrSettings().model_copy(update={'fallback_sl_pct': 100})
    result = simulate([], settings=broken)
    assert result['status'] == 'REJECTED' and result['reason'] == 'FALLBACK_STOP_INVALID'


def test_guard_blocks_without_tightening():
    with pytest.raises(ValueError, match='MAX_INITIAL_RISK_EXCEEDED'):
        plan(max_initial_risk_pct=2)
    assert plan(max_initial_risk_pct=3)['initial_stop'] == 97


@pytest.mark.parametrize('low,high,reason,fill', [(96,102,'SL',97), (98,110,'TARGET',106), (90,120,'SL',97)])
def test_candle_first_touch_and_theoretical_fills(low, high, reason, fill):
    result = simulate(history()+[candle(ENTRY, low=low, high=high)])
    assert result['status'] == 'CLOSED' and result['exit_reason'] == reason
    assert result['exit_price'] == fill


def test_eod_and_incomplete_data():
    settings = FixedAtrSettings(eod_exit_time='10:02')
    rows = history()+[candle(ENTRY), candle(ENTRY+timedelta(minutes=1), close=101)]
    result = simulate(rows, settings=settings)
    assert result['exit_reason'] == 'EOD' and result['exit_price'] == 101
    assert simulate(rows[:-1], settings=settings)['status'] == 'DATA_INCOMPLETE'
    missing = history()+[candle(ENTRY+timedelta(minutes=1), low=90)]
    assert simulate(missing, settings=settings)['reason'] == 'MISSING_POST_ENTRY_MINUTE'


def test_partial_entry_candle_policies_and_no_future_leakage():
    partial = ENTRY+timedelta(seconds=30)
    rows = history()+[candle(ENTRY, low=90, high=120), candle(ENTRY+timedelta(minutes=1), high=107)]
    result = simulate(rows, entry_time=partial)
    assert result['exit_reason'] == 'TARGET'
    assert result['atr_value'] == 4
    result = simulate(rows, entry_time=partial,
        settings=FixedAtrSettings(entry_candle_policy='FULL_CANDLE_APPROXIMATION'))
    assert result['exit_reason'] == 'SL'
    assert entry_plan(100, partial, SYMBOL, rows)['atr_value'] == 4
    assert plan(rows)['atr_value'] == 4


def test_order_independence_and_frozen_settings():
    rows = history()+[candle(ENTRY, high=107)]
    assert simulate(rows) == simulate(list(reversed(rows)))
    settings = FixedAtrSettings()
    snapshot = plan()['frozen_strategy_settings']
    with pytest.raises(ValidationError):
        settings.atr_multiplier = 8
    assert snapshot['atr_multiplier'] == .75


def test_quantity_cost_r_and_duration():
    result = simulate(history()+[candle(ENTRY, high=107)], brokerage=2, taxes=1, slippage_cost=.5, other_fees=.5)
    assert result['gross_pnl'] == 60 and result['net_pnl'] == 56
    assert result['realized_r_multiple'] == 2 and result['return_percentage'] == 6
    assert result['holding_duration_seconds'] == 60
    assert simulate(history(), brokerage=-1)['status'] == 'REJECTED'


def test_quality_errors_and_missing_pre_entry_minute():
    rows = history()
    rows.pop(3)
    result = plan(rows)
    assert result['data_quality_warnings'] and result['atr_sample_count'] == 12
    assert simulate(history()+[history()[0]])['reason'] == 'DUPLICATE_MINUTE_CANDLE'
    assert simulate([candle(ENTRY, symbol='OTHER')])['reason'] == 'OPTION_CONTRACT_MISMATCH'
    with pytest.raises(ValidationError): candle(ENTRY+timedelta(seconds=1))
    with pytest.raises(ValidationError): candle(ENTRY.replace(tzinfo=None))
    with pytest.raises(ValidationError): candle(ENTRY, high=99)
    utc_rows = [c.model_copy(update={'timestamp': c.timestamp.astimezone(__import__('datetime').timezone.utc)}) for c in history()]
    assert plan(utc_rows) == plan(history())


def test_paper_frozen_fixed_plan(client):
    configure(client, default_exit_strategy='ATR_FIXED')
    app = client.app
    symbols = [c.symbol for c in app.state.paper_executor.instruments.contracts('NIFTY')]
    data = app.state.paper_executor.fixed_atr_data
    data.cache([c.model_copy(update={'symbol': symbol}) for symbol in symbols for c in history()])
    trade = enter(client)
    assert trade['strategy_type'] == 'ATR_FIXED' and trade['strategy3_entry']['target'] == 106
    assert trade['initial_stop_loss'] == 97 and not trade['breakeven_protection_enabled']
    configure(client, strategy3=FixedAtrSettings(atr_multiplier=5).model_dump(mode='json'))
    tick(client, trade['option_symbol'], 105)
    current = client.get('/trades').json()[0]
    assert current['current_stop_loss'] == 97 and current['strategy3_entry'] == trade['strategy3_entry']
    tick(client, trade['option_symbol'], 108)
    current = client.get('/trades').json()[0]
    assert current['exit_reason'] == 'TARGET' and current['exit_price'] == 108
    assert client.get('/trades/history?strategy_type=ATR_FIXED').json()['total'] == 1
    assert client.get('/watchlist/options').status_code == 200


def test_backtest_fixed_candle_stop_first_and_isolation(client):
    minute_rows = [c.model_dump(mode='json', exclude={'volume'}) for c in history()+[candle(ENTRY, low=90, high=120)]]
    result = run(client, strategy_dataset(), exit_strategy='ATR_FIXED', minute_candles=minute_rows, transaction_cost_per_order=2)
    assert result['status'] == 'COMPLETED', result.get('error_message')
    trade, = result['trades']
    assert trade['exit_reason'] == 'SL' and trade['exit_price'] == 97
    assert trade['strategy3_entry']['atr_sample_count'] == 14
    assert trade['net_pnl'] == -34 and trade['realized_r_multiple'] == -1
    assert client.get('/trades').json() == []


def test_backtest_fallback_eod_and_incomplete(client):
    config = dict(exit_strategy='ATR_FIXED', strategy3_configuration={'eod_exit_time':'10:02'})
    rows = [candle(ENTRY), candle(ENTRY+timedelta(minutes=1), close=101)]
    complete = run(client, strategy_dataset(), **config, minute_candles=[c.model_dump(mode='json') for c in rows])
    assert complete['status'] == 'COMPLETED', complete.get('error_message')
    trade, = complete['trades']
    assert trade['exit_reason'] == 'EOD' and trade['exit_price'] == 101
    assert trade['strategy3_entry']['stop_source'] == 'FALLBACK'
    incomplete = post(client, strategy_dataset(), **config).json()
    assert incomplete['status'] == 'DATA_INCOMPLETE'
    assert incomplete['trades'][0]['exit_price'] is None


def test_backtest_guard_rejection_and_duplicate_validation(client):
    result = run(client, exit_strategy='ATR_FIXED', strategy3_configuration={'max_initial_risk_pct': 10})
    assert result['total_trades'] == 0
    assert result['entry_results'][0]['failure_reason'] == 'MAX_INITIAL_RISK_EXCEEDED'
    body = dict(trading_date='2026-09-14', instrument='NIFTY', levels=[25000], contracts=CONTRACTS,
                dataset=dataset(), exit_strategy='ATR_FIXED', minute_candles=[candle(ENTRY).model_dump(mode='json')]*2)
    assert client.post('/backtests/run', json=body).status_code == 422


def test_migration_preserves_existing_trade_and_sequence(tmp_path):
    from app.trade_metadata import initialize_trade_metadata
    path = tmp_path/'old.sqlite3'
    with connect(path) as c:
        c.execute("CREATE TABLE trades (trade_id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_type TEXT CHECK(strategy_type IN ('LEGACY','ATR')))")
        c.execute("INSERT INTO trades VALUES (21, 'ATR')")
        c.execute('CREATE INDEX old_strategy ON trades(strategy_type)')
        c.execute("INSERT INTO trades VALUES (30, 'LEGACY')")
        c.execute('DELETE FROM trades WHERE trade_id=30')
        initialize_trade_metadata(c)
        initialize_trade_metadata(c)
        c.execute("INSERT INTO trades (strategy_type) VALUES ('ATR_FIXED')")
        assert c.execute('SELECT max(trade_id) FROM trades').fetchone()[0] == 31
        assert c.execute('SELECT strategy_type FROM trades WHERE trade_id=21').fetchone()[0] == 'ATR'
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name='old_strategy'").fetchone()


def test_backtest_partial_entry_and_frozen_snapshot(client):
    rows = history()+[candle(ENTRY), candle(ENTRY+timedelta(minutes=1), low=90, high=120),
                      candle(ENTRY+timedelta(minutes=2), high=107)]
    result = run(client, exit_strategy='ATR_FIXED', minute_candles=[c.model_dump(mode='json') for c in rows])
    trade, = result['trades']
    assert trade['exit_reason'] == 'TARGET' and trade['exit_price'] == 106
    assert trade['strategy3_entry']['applied_entry_candle_policy'] == 'SKIP_PARTIAL_ENTRY_CANDLE'
    snapshot = trade['strategy_config_snapshot']
    configure(client, strategy3=FixedAtrSettings(atr_multiplier=5).model_dump(mode='json'))
    assert client.get(f"/backtests/{result['id']}").json()['trades'][0]['strategy_config_snapshot'] == snapshot
    assert result['settings_snapshot']['strategy3_configuration']['atr_multiplier'] == .75


def test_backtest_gap_is_incomplete_not_a_fabricated_stop(client):
    rows = history()+[candle(ENTRY+timedelta(minutes=1), low=90)]
    result = post(client, strategy_dataset(), exit_strategy='ATR_FIXED',
        minute_candles=[c.model_dump(mode='json') for c in rows]).json()
    assert result['status'] == 'DATA_INCOMPLETE'
    assert result['trades'][0]['exit_price'] is None


def test_same_strategy_in_historical_candle_execution_model(client):
    from app.backtests import BacktestInput
    from app.historical_market_data import HistoricalDataset
    rows = history()+[candle(ENTRY, low=96, high=107)]
    bundle = HistoricalDataset(contracts=CONTRACTS, ticks=strategy_dataset(),
        minute_candles=[c.model_dump() for c in rows], execution_model='CANDLE_APPROXIMATION')
    config = BacktestInput(trading_date='2026-09-14', instrument='NIFTY', levels=[25000], exit_strategy='ATR_FIXED')
    result = run_async(client.app.state.backtest_runner.run(config, bundle=bundle))
    assert result['status'] == 'COMPLETED', result.get('error_message')
    assert result['trades'][0]['exit_reason'] == 'SL'
    assert result['trades'][0]['exit_price'] == 97


def test_paper_entry_at_strategy3_eod_is_rejected(client):
    from test_paper_trades import add_level, publish
    configure(client, default_exit_strategy='ATR_FIXED', strategy3={'eod_exit_time': '10:00'})
    add_level(client); publish(client, [24900, 25000])
    assert client.get('/trades').json() == []
    assert client.get('/trade-entry-results').json()[0]['failure_reason'] == 'STRATEGY3_EOD_CUTOFF_REACHED'


def test_paper_eod_snapshot_survives_restart(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    moment = [ENTRY]
    path = tmp_path/'restart.sqlite3'
    with TestClient(create_app(path, clock=lambda: moment[0])) as client:
        configure(client, default_exit_strategy='ATR_FIXED', strategy3={'eod_exit_time':'10:02'})
        trade = enter(client)
        assert trade['strategy3_entry']['stop_source'] == 'FALLBACK'
        configure(client, strategy3={'eod_exit_time':'15:25', 'fallback_sl_pct':10})
    with TestClient(create_app(path, clock=lambda: moment[0])) as client:
        current = client.get('/trades').json()[0]
        assert current['strategy3_entry'] == trade['strategy3_entry']
        moment[0] = ENTRY+timedelta(minutes=2)
        tick(client, trade['option_symbol'], 102)
        current = client.get('/trades').json()[0]
        assert current['exit_reason'] == 'EOD' and current['exit_price'] == 102


def test_zerodha_minute_history_read_only_adapter(tmp_path):
    from types import SimpleNamespace
    path = tmp_path/'minutes.sqlite3'
    initialize_database(path)
    calls = []
    class ReadOnlyConnector:
        async def historical_candles(self, token, start, end, interval):
            calls.append((token, interval))
            return [[c.timestamp.isoformat(), c.open, c.high, c.low, c.close] for c in history()+[candle(ENTRY, high=200)]]
    adapter = FixedAtrData(path, 'ZERODHA')
    source = SimpleNamespace(connector=ReadOnlyConnector(), clock=lambda: ENTRY,
        instruments=SimpleNamespace(option=lambda symbol: SimpleNamespace(instrument_token=123)))
    run_async(adapter.prepare(source, SYMBOL))
    with connect(path) as connection:
        rows = adapter.candles(SYMBOL, ENTRY, connection)
    assert len(rows) == 15 and plan(rows)['atr_value'] == 4
    assert calls == [(123, 'minute')]
