"""Persisted, single-job background execution for the deployed single-worker app."""
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.database import connect


class BacktestJobs:
    def __init__(self, runner):
        self.runner = runner
        self.path = runner.directory / 'jobs.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.task = None
        with connect(self.path) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS backtest_jobs (
                id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, kind TEXT NOT NULL,
                status TEXT NOT NULL, message TEXT NOT NULL, result TEXT, error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            c.execute("""UPDATE backtest_jobs SET status='FAILED', error=?, message=?
                WHERE status IN ('QUEUED', 'RUNNING')""",
                ('Backend restarted before the backtest finished. Submit the run again.', 'Backtest interrupted'))

    def submit(self, config, compare=False):
        kind = 'COMPARE' if compare else 'RUN'
        identity = hashlib.sha256((kind + json.dumps(config.model_dump(mode='json'), sort_keys=True)).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with connect(self.path) as c:
            c.execute('BEGIN IMMEDIATE')
            active = c.execute("SELECT * FROM backtest_jobs WHERE status IN ('QUEUED', 'RUNNING') LIMIT 1").fetchone()
            if active:
                if active['request_hash'] == identity:
                    return self.get(active['id'])
                raise ValueError('Another backtest is running. Wait for it to finish before starting a different run.')
            job_id = str(uuid4())
            c.execute('INSERT INTO backtest_jobs VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)',
                      (job_id, identity, kind, 'QUEUED', 'Backtest queued', now, now))
        self.task = asyncio.create_task(self._run(job_id, config, compare))
        return self.get(job_id)

    def update(self, job_id, *, status='RUNNING', message, result=None, error=None):
        with connect(self.path) as c:
            c.execute('UPDATE backtest_jobs SET status=?, message=?, result=?, error=?, updated_at=? WHERE id=?',
                      (status, message, json.dumps(result) if result is not None else None, error,
                       datetime.now(timezone.utc).isoformat(), job_id))

    async def _run(self, job_id, config, compare):
        from app.backtests import execute_backtest
        try:
            result = await execute_backtest(self.runner, config, compare=compare, threaded=True,
                progress=lambda message: self.update(job_id, message=message))
            if not compare and result['status'] == 'FAILED':
                self.update(job_id, status='FAILED', message='Backtest failed',
                            error=result.get('error_message') or 'Backtest failed')
            else:
                self.update(job_id, status='COMPLETED', message='Backtest completed',
                            result=result if compare else {'run_id': result['id']})
        except asyncio.CancelledError:
            self.update(job_id, status='FAILED', message='Backtest interrupted',
                        error='Backend stopped before the backtest finished. Submit the run again.')
            raise
        except Exception as error:
            logging.getLogger(__name__).exception('Background backtest failed: %s', job_id)
            self.update(job_id, status='FAILED', message='Backtest failed',
                        error=str(error) if isinstance(error, ValueError) else 'Backtest failed unexpectedly. Check backend logs and retry.')

    def get(self, job_id):
        with connect(self.path) as c:
            row = c.execute('SELECT id, kind, status, message, error, created_at, updated_at FROM backtest_jobs WHERE id=?', (str(job_id),)).fetchone()
            return dict(row) if row else None

    def result(self, job_id):
        with connect(self.path) as c:
            row = c.execute("SELECT kind, result FROM backtest_jobs WHERE id=? AND status='COMPLETED'", (str(job_id),)).fetchone()
        if row is None:
            return None
        result = json.loads(row['result'])
        return self.runner.get(result['run_id']) if row['kind'] == 'RUN' else result

    async def close(self):
        # Let local replay finish before closing its parent app; it owns isolated DBs.
        if self.task and not self.task.done():
            await self.task
