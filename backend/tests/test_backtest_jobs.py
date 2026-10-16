"""Short HTTP jobs preserve isolated replay rules and results."""
import threading
import time
from app.backtest_jobs import BacktestJobs
from app.database import connect
from test_backtests import CONTRACTS, dataset


def config():
    return dict(trading_date='2026-09-14', instrument='NIFTY', levels=[25000], contracts=CONTRACTS, dataset=dataset())


def finish(client, job):
    for _ in range(500):
        response = client.get('/backtests/jobs/' + job['id'])
        assert response.status_code == 200
        if response.json()['status'] in ('COMPLETED', 'FAILED'):
            return response.json()
        time.sleep(.01)
    raise AssertionError('Job did not finish')


def test_slow_replay_accepts_and_keeps_health_responsive(client, monkeypatch):
    started, release = threading.Event(), threading.Event()
    runner = client.app.state.backtest_runner
    original = runner.run

    async def slow(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return await original(*args, **kwargs)

    monkeypatch.setattr(runner, 'run', slow)
    response = client.post('/backtests/jobs', json=config())
    assert response.status_code == 202
    job = response.json()
    try:
        assert started.wait(3)
        assert client.get('/health').status_code == 200
        assert client.get('/levels').status_code == 200
        assert client.get('/backtests/jobs/' + job['id']).json()['status'] == 'RUNNING'
        assert client.get('/backtests/jobs/' + job['id'] + '/result').status_code == 409
        duplicate = client.post('/backtests/jobs', json=config())
        assert duplicate.status_code == 202 and duplicate.json()['id'] == job['id']
        different = config()
        different['levels'] = [25100]
        assert client.post('/backtests/jobs', json=different).status_code == 409
    finally:
        release.set()
    assert finish(client, job)['status'] == 'COMPLETED'
    result = client.get('/backtests/jobs/' + job['id'] + '/result').json()
    assert result['status'] == 'COMPLETED' and len(result['trades']) == 1
    assert result['trades'][0]['trade_mode'] == 'BACKTEST'
    assert client.get('/backtests/' + result['id']).json() == result
    assert client.get('/trades').json() == []


def test_failure_is_persisted_and_status_does_not_restart(client, monkeypatch):
    calls = []

    async def unavailable(config):
        calls.append(config)
        raise ValueError('Historical catalogue unavailable for the selected date')

    monkeypatch.setattr(client.app.state.backtest_runner, 'prepare_dataset', unavailable)
    job = client.post('/backtests/jobs', json=config()).json()
    failed = finish(client, job)
    assert failed['status'] == 'FAILED' and 'catalogue unavailable' in failed['error']
    assert client.get('/backtests/jobs/' + job['id']).json() == failed
    assert len(calls) == 1
    assert client.get('/backtests/jobs/' + job['id'] + '/result').status_code == 409


def test_comparison_shares_data_and_preserves_seven_candidates(client):
    job = client.post('/backtests/jobs?compare=true', json=config()).json()
    assert finish(client, job)['status'] == 'COMPLETED'
    result = client.get('/backtests/jobs/' + job['id'] + '/result').json()
    assert len(result['runs']) == 7
    assert len({row['dataset_hash'] for row in result['runs']}) == 1
    assert [row['strategy'] for row in result['runs']] == ['LEGACY'] + ['ATR'] * 6


def test_validation_and_missing_jobs(client):
    assert client.post('/backtests/jobs', json={'levels': []}).status_code == 422
    assert client.get('/backtests/jobs/not-a-uuid').status_code == 422
    assert client.get('/backtests/jobs/00000000-0000-0000-0000-000000000001').status_code == 404


def test_restart_marks_interrupted_and_preserves_completed(client):
    job = client.post('/backtests/jobs', json=config()).json()
    assert finish(client, job)['status'] == 'COMPLETED'
    jobs = client.app.state.backtest_jobs
    with connect(jobs.path) as c:
        c.execute("INSERT INTO backtest_jobs VALUES ('interrupted', 'hash', 'RUN', 'RUNNING', 'Loading', NULL, NULL, 'now', 'now')")
    restarted = BacktestJobs(client.app.state.backtest_runner)
    assert restarted.get('interrupted')['status'] == 'FAILED'
    assert 'restarted' in restarted.get('interrupted')['error']
    assert restarted.get(job['id'])['status'] == 'COMPLETED'
    assert restarted.result(job['id'])['status'] == 'COMPLETED'


def test_history_ignores_a_run_database_still_being_initialized(client):
    from uuid import uuid4
    runner = client.app.state.backtest_runner
    run_id = uuid4()
    path = runner.directory / str(run_id) / 'results.sqlite3'
    path.parent.mkdir()
    with connect(path) as c:
        c.execute('CREATE TABLE partial (id INTEGER)')
    assert client.get('/backtests').status_code == 200
    assert client.get('/backtests/' + str(run_id)).status_code == 404
