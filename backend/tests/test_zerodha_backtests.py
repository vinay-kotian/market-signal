"""Mocked read-only Kite history through shared signal/exit services."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.backtests import BacktestInput, BacktestRunner
from app.database import connect, initialize_database
from app.zerodha.instruments import Instrument, ZerodhaInstrumentService
from app.zerodha.connector import KiteConnector, MarketSettings
from app.zerodha_history import ZerodhaHistoricalDataLoader, IST

DAY = '2026-10-09'
NOW = datetime(2026, 10, 12, 10, tzinfo=IST)
PE, CE = 'NIFTY26OCT25000PE', 'NIFTY26OCT24900CE'


def record(token, symbol, kind, strike=0, expiry=None):
    return Instrument(instrument_token=token, trading_symbol=symbol, name='NIFTY', underlying='NIFTY',
        exchange='NSE' if kind == 'INDEX' else 'NFO', segment='INDICES' if kind == 'INDEX' else 'NFO-OPT',
        instrument_type=kind, strike=strike, expiry=expiry, lot_size=10 if expiry else 0, tick_size=.05)


def configuration(**overrides):
    return BacktestInput(trading_date=DAY, instrument='NIFTY', levels=[24950], data_source='ZERODHA_HISTORICAL',
        market_open_time='09:15', market_close_time='09:35', entry_block_after_open_minutes=0,
        entry_block_before_close_minutes=1, mandatory_exit_before_close_minutes=1,
        stop_strategy='LEGACY', **overrides)


class HistoryBroker:
    authenticated = True
    def __init__(self):
        self.calls = []
        self.option_low, self.option_high = 99, 101
        self.missing = self.partial = self.future_high = None
        self.warmup_missing = False

    async def historical_candles(self, token, start, end, interval='minute'):
        self.calls.append((token, start, end, interval))
        if token == self.missing:
            raise ValueError('Option candle history unavailable')
        if interval == '5minute':
            if self.warmup_missing:
                return []
            prior = start+timedelta(days=9, hours=5)
            return [[(prior+timedelta(minutes=5*i)).isoformat(), 100, 102, 98, 100, 1] for i in range(14)]
        result = []
        for i in range(int((end-start).total_seconds()) // 60):
            timestamp = start+timedelta(minutes=i)
            if token == 1:
                price = 24800 if i < 2 else 24950
                row = [timestamp.isoformat(), price, price+5, price-5, price, 0]
            else:
                low, high = (self.option_low, self.option_high) if i == 5 else (99, 101)
                if self.future_high and i > 5:
                    high = self.future_high
                row = [timestamp.isoformat(), 100, high, low, 100, 20]
            result.append(row)
        if token == self.partial:
            result.pop(4)
        return list(reversed(result))


def setup(tmp_path):
    path = tmp_path / 'paper.sqlite3'
    initialize_database(path)
    broker = HistoryBroker()
    instruments = ZerodhaInstrumentService(path, broker)
    records = [record(1, 'NIFTY 50', 'INDEX'), record(2, PE, 'PE', 25000, '2026-10-13'),
               record(3, CE, 'CE', 24900, '2026-10-13')]
    instruments.install(records)
    instruments.last_sync = DAY+'T08:00:00+05:30'
    with connect(path) as connection:
        connection.execute('INSERT INTO zerodha_instrument_catalogues VALUES (?, ?, ?)',
                           (DAY, instruments.last_sync, json.dumps([r.model_dump(mode='json') for r in records])))
    loader = ZerodhaHistoricalDataLoader(tmp_path / 'historical', instruments, broker, lambda: NOW)
    runner = BacktestRunner(tmp_path / 'backtests')
    runner.zerodha_loader = loader
    return loader, runner, broker, instruments


def test_loader_normalization_dated_catalogue_cache_and_reproducibility(tmp_path):
    loader, runner, broker, instruments = setup(tmp_path)
    instruments.install([record(999, 'WRONG', 'PE', 25000, '2026-10-20')])
    async def exercise():
        bundle, again = await loader.load(configuration()), await loader.load(configuration())
        assert len(broker.calls) == 5
        assert bundle.contracts[0].instrument_token == 2
        assert bundle.coverage['symbols']['NIFTY']['received_minutes'] == 20
        assert again.coverage['symbols'][PE]['cached']
        assert bundle.data_resolution == '1_MINUTE_OHLC'
        assert [c.timestamp for c in bundle.minute_candles[:20]] == sorted(c.timestamp for c in bundle.minute_candles[:20])
        one, two = await runner.run(configuration(), bundle=bundle), await runner.run(configuration(), bundle=again)
        assert one['dataset_hash'] == two['dataset_hash']
        assert one['trades'] == two['trades']
    asyncio.run(exercise())


@pytest.mark.parametrize('strategy', ['LEGACY', 'ATR'])
def test_shared_entry_exits_costs_r_and_paper_isolation(tmp_path, strategy):
    loader, runner, broker, _ = setup(tmp_path)
    broker.option_low = 85
    result = asyncio.run(runner.run(configuration(exit_strategy=strategy, transaction_cost_per_order=2)))
    assert result['status'] == 'COMPLETED', result
    trade, = result['trades']
    assert trade['entry_time'] == DAY+'T09:18:00+05:30'
    assert trade['signal_timestamp'] == trade['entry_time']
    assert trade['entry_price'] == 100
    assert trade['exit_time'] == DAY+'T09:21:00+05:30'
    assert trade['exit_price'] == 85 and trade['highest_price'] == 101
    assert trade['initial_stop_loss'] == (94 if strategy == 'ATR' else 90)
    assert trade['option_atr_at_entry'] == 4  # Shared executor also snapshots ATR for LEGACY.
    assert result['gross_pnl'] == -150 and result['net_pnl'] == -154
    assert result['transaction_costs'] == 4
    assert result['average_r'] == pytest.approx(-154 / (60 if strategy == 'ATR' else 100))
    assert result['execution_model'] == 'CANDLE_APPROXIMATION'
    assert result['settings_snapshot']['exit_strategy'] == strategy
    assert runner.get(result['id']) == result
    with connect(loader.instruments.path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM trades').fetchone()[0] == 0
        assert connection.execute('SELECT COUNT(*) FROM signals').fetchone()[0] == 0
        assert json.loads(connection.execute('SELECT settings FROM exit_settings').fetchone()[0])['default_exit_strategy'] == 'LEGACY'


def test_conservative_intraminute_trailing_and_no_future_atr(tmp_path):
    _, runner, broker, _ = setup(tmp_path)
    broker.option_low, broker.option_high, broker.future_high = 95, 150, 10000
    result = asyncio.run(runner.run(configuration()))
    assert result['status'] == 'COMPLETED', result
    trade, = result['trades']
    assert trade['highest_price'] == 150 and trade['current_stop_loss'] == 135
    assert trade['exit_price'] == 95 and trade['exit_reason'] == 'TRAILING_STOP_LOSS'
    assert any(e['event_type'] == 'STOP_UPDATED' for e in result['timeline'])
    atr = asyncio.run(runner.run(configuration(exit_strategy='ATR')))
    assert atr['trades'][0]['option_atr_at_entry'] == 4


def test_initial_low_stop_wins_ambiguous_high(tmp_path):
    _, runner, broker, _ = setup(tmp_path)
    broker.option_low, broker.option_high = 85, 150
    result = asyncio.run(runner.run(configuration()))
    assert result['trades'][0]['highest_price'] == 101
    assert result['trades'][0]['exit_reason'] == 'TRAILING_STOP_LOSS'  # Prior completed high raised the shared stop.
    assert result['trades'][0]['current_stop_loss'] == 90.9


@pytest.mark.parametrize('failure', ['missing', 'partial'])
def test_selected_missing_data_fails_with_coverage(tmp_path, failure):
    _, runner, broker, _ = setup(tmp_path)
    setattr(broker, failure, 2)
    result = asyncio.run(runner.run(configuration()))
    assert result['status'] == 'FAILED' and result['total_trades'] == 0
    assert result['historical_data_coverage']['symbols'][PE]['complete'] is False
    assert result['data_warnings']
    assert 'history unavailable' in result['error_message'] or 'coverage incomplete' in result['error_message']


def test_no_index_data_and_invalid_dates_do_not_cache_or_fabricate(tmp_path):
    loader, _, broker, _ = setup(tmp_path)
    broker.partial = 1
    with pytest.raises(ValueError, match='coverage incomplete'):
        asyncio.run(loader.load(configuration()))
    with connect(loader.directory / 'zerodha-history.sqlite3') as connection:
        assert connection.execute('SELECT COUNT(*) FROM history_cache').fetchone()[0] == 0
    with pytest.raises(ValueError, match='weekend'):
        asyncio.run(loader.load(configuration().model_copy(update={'trading_date': datetime(2026, 10, 10).date()})))
    with pytest.raises(ValueError, match='completed trading session'):
        asyncio.run(loader.load(configuration().model_copy(update={'trading_date': datetime(2026, 10, 13).date()})))


def test_current_catalogue_cannot_replace_missing_historical_day(tmp_path):
    loader, _, _, instruments = setup(tmp_path)
    with connect(instruments.path) as connection:
        connection.execute('DELETE FROM zerodha_instrument_catalogues')
    instruments.last_sync = NOW.isoformat()
    with pytest.raises(ValueError, match='Current instruments cannot prove'):
        asyncio.run(loader.load(configuration()))
    instruments.last_sync = '2026-10-11T10:00:00+05:30'
    with pytest.raises(ValueError, match='catalogue unavailable'):
        loader.catalogue(datetime(2026, 10, 9).date())
    instruments.last_sync = DAY+'T08:00:00+05:30'
    assert loader.catalogue(datetime(2026, 10, 9).date())[0] == instruments.records
    instruments.last_sync = '2026-10-08T10:00:00+05:30'
    with pytest.raises(ValueError, match='catalogue unavailable'):
        loader.catalogue(datetime(2026, 10, 9).date())


def test_missing_strike_never_selects_other_expiry(tmp_path):
    _, runner, _, instruments = setup(tmp_path)
    rows = [record(1, 'NIFTY 50', 'INDEX'), record(3, CE, 'CE', 24900, '2026-10-13'),
            record(4, 'LATER-PE', 'PE', 25000, '2026-10-20')]
    with connect(instruments.path) as connection:
        connection.execute('UPDATE zerodha_instrument_catalogues SET records=?',
                           (json.dumps([r.model_dump(mode='json') for r in rows]),))
    result = asyncio.run(runner.run(configuration()))
    assert result['status'] == 'FAILED' and result['total_trades'] == 0
    assert result['option_selections'][0]['failure_reason'] == 'MISSING_OPTION_CONTRACT'


def test_atr_insufficient_warmup_preserves_shared_skip(tmp_path):
    _, runner, broker, _ = setup(tmp_path)
    broker.warmup_missing = True
    result = asyncio.run(runner.run(configuration(exit_strategy='ATR')))
    assert result['status'] == 'COMPLETED' and result['total_trades'] == 0
    assert result['entry_results'][0]['failure_reason'] == 'OPTION_ATR_UNAVAILABLE'


def test_cutoff_and_mandatory_exit_use_boundary_open(tmp_path):
    _, runner, _, _ = setup(tmp_path)
    result = asyncio.run(runner.run(configuration()))
    trade, = result['trades']
    assert trade['exit_time'] == DAY+'T09:34:00+05:30'
    assert trade['exit_price'] == 100 and trade['exit_reason'] == 'MARKET_CLOSE'
    assert result['open_trades'] == 0
    cutoff = asyncio.run(runner.run(configuration().model_copy(update={'entry_block_before_close_minutes': 17})))
    assert cutoff['total_trades'] == 0
    assert cutoff['entry_results'][0]['failure_reason'] == 'NEW_TRADE_CUTOFF_REACHED'


def test_request_validation_and_api_no_fallback(client):
    request = dict(trading_date=DAY, instrument='NIFTY', levels=[24950], data_source='ZERODHA_HISTORICAL')
    for invalid in [{'fixture': 'nifty-demo'}, {'instrument': 'SENSEX'}, {'levels': [-1]}, {'mandatory_exit_before_close_minutes': 3.5}]:
        assert client.post('/backtests/run', json={**request, **invalid}).status_code == 422
    response = client.post('/backtests/run', json={**request, 'trading_date': '2026-09-11'})
    assert response.status_code == 422 and 'Zerodha' in response.text
    assert client.get('/backtests').json() == []


def test_connector_rate_retry_auth_and_read_only(monkeypatch):
    async def no_sleep(seconds):
        pass
    monkeypatch.setattr('app.zerodha.connector.asyncio.sleep', no_sleep)
    calls, statuses = [], [429, 503, 200]
    def reply(request):
        calls.append(request)
        return httpx.Response(statuses.pop(0), json={'status': 'success', 'data': {'candles': []}})
    async def exercise():
        connector = KiteConnector(MarketSettings(api_key='test', access_token='test'),
            httpx.AsyncClient(base_url='https://mock.invalid', transport=httpx.MockTransport(reply)))
        start = datetime(2026, 10, 9, 3, 45, tzinfo=timezone.utc)
        assert await connector.historical_candles(1, start, start+timedelta(hours=6)) == []
        assert len(calls) == 3 and all(r.method == 'GET' for r in calls)
        assert calls[0].url.params['from'] == DAY+' 09:15:00'
        statuses.append(403)
        with pytest.raises(ValueError, match='session expired'):
            await connector.historical_candles(1, start, start)
        assert not connector.authenticated
        await connector.close()
    asyncio.run(exercise())


def test_historical_api_compare_freezes_archive_and_settings(client, tmp_path):
    loader, runner, broker, _ = setup(tmp_path)
    client.app.state.backtest_runner = runner
    config = configuration().model_dump(mode='json', exclude={'start_time', 'end_time', 'dataset', 'fixture'})
    # Empty contracts/candles are valid for the broker source.
    response = client.post('/backtests/compare', json=config)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['execution_model'] == 'CANDLE_APPROXIMATION'
    assert len(result['runs']) == 7
    assert len({r['dataset_hash'] for r in result['runs']}) == 1
    assert all(r['status'] == 'COMPLETED' for r in result['runs'])
    assert len(broker.calls) == 5
    assert client.get('/reports/paper-trading').json()['total_trades'] == 0


def test_expired_contract_only_uses_validated_cached_prices(tmp_path):
    loader, _, broker, instruments = setup(tmp_path)
    async def exercise():
        await loader.load(configuration())
        count = len(broker.calls)
        loader.clock = lambda: NOW+timedelta(days=30)
        bundle = await loader.load(configuration())
        assert len(broker.calls) == count
        assert bundle.coverage['symbols'][PE]['cached']
        with connect(loader.directory / 'zerodha-history.sqlite3') as connection:
            connection.execute('DELETE FROM history_cache')
        missing = await loader.load(configuration())
        assert 'expired contract' in missing.option_data_errors[PE]
    asyncio.run(exercise())


def test_full_october_ninth_session_with_banknifty(tmp_path):
    loader, runner, broker, instruments = setup(tmp_path)
    rows = [record(1, 'NIFTY BANK', 'INDEX'), record(2, 'BANK-PE', 'PE', 60100, '2026-10-28'),
            record(3, 'BANK-CE', 'CE', 59900, '2026-10-28')]
    rows = [r.model_copy(update={'underlying': 'BANKNIFTY', 'name': 'BANKNIFTY'}) for r in rows]
    with connect(instruments.path) as connection:
        connection.execute('UPDATE zerodha_instrument_catalogues SET records=?',
                           (json.dumps([r.model_dump(mode='json') for r in rows]),))
    original = broker.historical_candles
    async def candles(token, start, end, interval='minute'):
        result = await original(token, start, end, interval)
        if token == 1:
            for row in result:
                offset = int((datetime.fromisoformat(row[0])-start).total_seconds()) // 60
                price = 59800 if offset < 12 else 60000
                row[1:5] = [price, price+5, price-5, price]
        return result
    broker.historical_candles = candles
    config = BacktestInput(trading_date=DAY, instrument='BANKNIFTY', levels=[60000], data_source='ZERODHA_HISTORICAL')
    result = asyncio.run(runner.run(config))
    assert result['status'] == 'COMPLETED', result
    trade, = result['trades']
    assert trade['option_symbol'] == 'BANK-PE' and trade['strike'] == 60100
    assert trade['entry_time'] == DAY+'T09:28:00+05:30'
    assert trade['exit_time'] == DAY+'T15:27:00+05:30'
    assert result['historical_data_coverage']['symbols']['BANKNIFTY']['received_minutes'] == 375


@pytest.mark.parametrize('distance,expected', [(100, 1), (200, 0)])
def test_candle_replay_preserves_approach_distance(tmp_path, distance, expected):
    _, runner, _, _ = setup(tmp_path)
    result = asyncio.run(runner.run(configuration(minimum_approach_distance_enabled=True,
                                                  minimum_approach_distance_points=distance)))
    assert result['status'] == 'COMPLETED' and result['total_trades'] == expected
    assert result['signals'][0]['approach_distance'] == 150


def test_candle_replay_preserves_initial_arming_and_ce_direction(tmp_path):
    _, runner, broker, _ = setup(tmp_path)
    unarmed = asyncio.run(runner.run(configuration(index_settings={'NIFTY': {'initial_arm_distance_points': 500}})))
    assert unarmed['total_trades'] == 0 and not unarmed['signals']
    original = broker.historical_candles
    async def candles(token, start, end, interval='minute'):
        rows = await original(token, start, end, interval)
        if token == 1:
            for row in rows:
                if row[4] == 24800:
                    row[1:5] = [25100, 25105, 25095, 25100]
        return rows
    broker.historical_candles = candles
    runner.zerodha_loader.directory = tmp_path / 'from-above'
    result = asyncio.run(runner.run(configuration()))
    assert result['status'] == 'COMPLETED'
    assert result['signals'][0]['direction'] == 'FROM_ABOVE'
    assert result['trades'][0]['option_symbol'] == CE


def test_catalogue_migration_preserves_legacy_dump_before_new_sync(tmp_path):
    _, _, broker, instruments = setup(tmp_path)
    with connect(instruments.path) as connection:
        connection.execute('DELETE FROM zerodha_instrument_catalogues')
        connection.executemany('INSERT INTO zerodha_instruments VALUES (?, ?, ?)',
            [(r.exchange, r.trading_symbol, r.model_dump_json()) for r in instruments.records])
        connection.execute('INSERT INTO zerodha_sync VALUES (1, ?)', (DAY+'T08:00:00+05:30',))
    reloaded = ZerodhaInstrumentService(instruments.path, broker)
    with connect(instruments.path) as connection:
        saved = connection.execute('SELECT records FROM zerodha_instrument_catalogues WHERE trading_date=?', (DAY,)).fetchone()
    assert len(json.loads(saved[0])) == 3
    assert reloaded.last_sync.startswith(DAY)


def test_post_session_catalogue_is_not_a_reliable_expiry_universe(tmp_path):
    loader, _, _, instruments = setup(tmp_path)
    with connect(instruments.path) as connection:
        connection.execute('UPDATE zerodha_instrument_catalogues SET observed_at=?', (DAY+'T16:00:00+05:30',))
    with pytest.raises(ValueError, match='observed after the session'):
        asyncio.run(loader.load(configuration()))
