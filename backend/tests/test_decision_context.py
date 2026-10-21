"""Explanatory metadata is additive and never substitutes current settings."""
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import create_app
from app.database import connect, initialize_database
from app.settings import SignalSettings
from test_paper_trades import add_level, publish
from test_position_monitor import enter
from test_atr_exit import configure
from test_backtests import post, SYMBOL


def test_signal_records_actual_threshold_and_survives_settings_change(tmp_path):
    settings = SignalSettings(minimum_approach_distance_enabled=True, minimum_approach_distance_points=120)
    app = create_app(tmp_path/'signals.sqlite3', signal_settings=settings)
    with TestClient(app) as client:
        add_level(client); publish(client, [24900, 25000])
        signal, = client.get('/signals').json()
        assert signal['rejection_reason'] == 'MINIMUM_DISTANCE_NOT_MET'
        assert signal['approach_distance'] == 100
        context = signal['decision_context']
        assert context['settings_snapshot']['minimum_approach_distance_points'] == 120
        assert context['approach_sample_count'] == 1
        app.state.signal_engine.settings = SignalSettings(minimum_approach_distance_points=1)
        assert client.get('/signals').json()[0]['decision_context'] == context


def test_atr_rejection_records_its_own_five_minute_requirement(client):
    configure(client, default_exit_strategy='ATR', atr_period=14)
    add_level(client); publish(client, [24900, 25000])
    failure, = client.get('/trade-entry-results').json()
    assert failure['failure_reason'] == 'OPTION_ATR_UNAVAILABLE'
    assert failure['decision_context']['completed_candle_count'] == 0
    assert failure['decision_context']['required_candle_count'] == 14
    assert failure['decision_context']['atr_candle_timeframe'] == '5minute'
    assert failure['decision_context']['strategy_type'] == 'ATR'


def test_fixed_fallback_records_minimum_without_changing_stop(client):
    configure(client, default_exit_strategy='ATR_FIXED')
    trade = enter(client)
    assert trade['initial_stop_loss'] == 80
    assert trade['strategy3_entry']['pre_entry_candle_count'] == 0
    assert trade['strategy3_entry']['fallback_reason'] == 'INSUFFICIENT_PRE_ENTRY_CANDLES'
    context = trade['decision_context']
    assert context['completed_candle_count'] == 0 and context['required_candle_count'] == 2
    assert context['atr_candle_timeframe'] == 'minute'
    assert context['strategy_config_snapshot']['fallback_sl_pct'] == 20
    configure(client, strategy3={'fallback_sl_pct': 5, 'min_pre_entry_candles': 8})
    assert client.get('/trades').json()[0]['decision_context'] == context


def test_risk_rejection_records_calculated_values_not_a_tighter_stop(client):
    configure(client, default_exit_strategy='ATR_FIXED', strategy3={'max_initial_risk_pct': 10})
    add_level(client); publish(client, [24900, 25000])
    failure, = client.get('/trade-entry-results').json()
    assert failure['failure_reason'] == 'MAX_INITIAL_RISK_EXCEEDED'
    context = failure['decision_context']
    assert context['initial_stop'] == 80 and context['initial_risk_percent'] == 20
    assert context['attempted_stop_source'] == 'FALLBACK'
    assert context['strategy_config_snapshot']['max_initial_risk_pct'] == 10
    assert client.get('/trades').json() == []


def test_success_records_override_source_without_changing_settings_snapshot(client):
    client.put('/settings/exit-strategy/next-trade/NIFTY', json={'strategy': 'ATR_FIXED'})
    trade = enter(client)
    assert trade['decision_context']['strategy_selection'] == {'source': 'NEXT_TRADE_OVERRIDE', 'strategy': 'ATR_FIXED'}
    assert 'exit_selection' not in trade['settings_snapshot']
    assert client.get('/settings/exit-strategy').json()['next_trade_overrides'] == {}


def test_incomplete_backtest_has_machine_code_and_original_message(client):
    response = post(client, exit_strategy='ATR_FIXED')
    assert response.status_code == 201
    result = response.json()
    assert result['status'] == 'DATA_INCOMPLETE'
    assert result['error_code'] == 'INCOMPLETE_EXIT_COVERAGE'
    assert result['error_message'].startswith('DATA_INCOMPLETE:')
    assert result['trades'][0]['exit_price'] is None
    assert result['trades'][0]['decision_context']['strategy_type'] == 'ATR_FIXED'


def test_old_records_default_to_empty_metadata_without_backfill(tmp_path):
    path = tmp_path/'old.sqlite3'
    # Model an old signals/results table before metadata existed.
    with connect(path) as c:
        c.execute('''CREATE TABLE signals (id INTEGER PRIMARY KEY, trigger_id INTEGER, level_id INTEGER,
            instrument TEXT, level REAL, trigger_price REAL, direction TEXT, approach_distance REAL,
            valid INTEGER, rejection_reason TEXT, timestamp TEXT)''')
        c.execute("INSERT INTO signals VALUES (1,1,1,'NIFTY',25000,25000,NULL,NULL,0,'INSUFFICIENT_PRICE_HISTORY','2026-09-14T10:00:00+05:30')")
        c.execute('''CREATE TABLE trade_entry_results (option_selection_id INTEGER PRIMARY KEY,trade_id INTEGER,
            status TEXT, failure_reason TEXT,timestamp TEXT)''')
        c.execute("INSERT INTO trade_entry_results VALUES (1,NULL,'FAILED','OPTION_ATR_UNAVAILABLE','2026-09-14T10:00:00+05:30')")
    initialize_database(path)
    initialize_database(path)
    from app.signal_repository import SignalRepository
    from app.trade_repository import TradeRepository
    assert SignalRepository(path).recent()[0].decision_context == {}
    assert TradeRepository(path).recent_results()[0].decision_context == {}


def test_chart_arm_threshold_and_signal_context_are_recorded_not_current(client):
    from test_position_monitor import tick
    tick(client, 'NIFTY', 24900)
    level = client.post('/levels', json={'instrument':'NIFTY','price':25000,'enabled':True}).json()
    tick(client, 'NIFTY', 25000)
    records = client.get('/instruments/NIFTY/events?date=2026-09-14').json()['events']
    arm = next(event for event in records if event['event_type'] == 'LEVEL_ARMED')
    assert arm['initial_arm_distance_points'] == 30
    generated = next(event for event in records if event['event_type'] == 'SIGNAL_GENERATED')
    assert generated['decision_context']['approach_sample_count'] == 1
    assert generated['approach_distance'] == 100
    client.put('/settings/indexes/NIFTY', json={'initial_arm_distance_points': 80})
    after = client.get('/instruments/NIFTY/events?date=2026-09-14').json()['events']
    assert next(event for event in after if event['id'] == arm['id'])['initial_arm_distance_points'] == 30
    trade = client.get('/trades').json()[0]
    option_events = client.get(f"/instruments/{trade['option_symbol']}/events?date=2026-09-14").json()['events']
    entry_event = next(event for event in option_events if event['event_type'] == 'TRADE_ENTRY')
    assert entry_event['trade_context']['strategy_type'] == trade['strategy_type']
    assert entry_event['trade_context']['strategy_config_snapshot'] == trade['strategy_config_snapshot']


def test_historical_warning_codes_are_additive_and_index_existing_messages(tmp_path):
    import asyncio
    from test_zerodha_backtests import setup, configuration
    loader, _, broker, _ = setup(tmp_path)
    original = broker.historical_candles
    async def with_missing_warmup(token, start, end, interval):
        if interval == '5minute':
            raise ValueError('Read-only warmup unavailable')
        return await original(token, start, end, interval)
    broker.historical_candles = with_missing_warmup
    loop = asyncio.new_event_loop()
    try:
        bundle = loop.run_until_complete(loader.load(configuration()))
    finally:
        loop.close()
    assert bundle.warning_details
    for detail in bundle.warning_details:
        assert detail.code == 'ATR_WARMUP_UNAVAILABLE'
        assert detail.message == bundle.warnings[detail.warning_index]
        assert detail.context['option_symbol']
