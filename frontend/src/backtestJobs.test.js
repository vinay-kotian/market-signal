import test from 'node:test';
import assert from 'node:assert/strict';
import { startBacktestJob, followBacktestJob, waitForPoll } from './backtestJobs.js';

test('submission returns a job and polls short GET requests until the final result', async () => {
  const paths = [], progress = [], accepted = [];
  let polls = 0, waits = 0;
  const result = { id: 'run', status: 'COMPLETED', trades: [] };
  const config = { instrument: 'NIFTY', levels: [25000] };
  const response = await startBacktestJob(config, { compare: true,
    onAccepted: job => accepted.push(job.id), onProgress: message => progress.push(message),
    wait: async () => { waits++; }, send: async (path, options = {}) => {
      paths.push(path);
      if (options.method === 'POST') { assert.deepEqual(JSON.parse(options.body), config); return { id: 'job', kind: 'COMPARE' }; }
      if (path.endsWith('/result')) return result;
      return ++polls < 3 ? { status: 'RUNNING', message: 'Replaying' } : { status: 'COMPLETED', message: 'Done' };
    } });
  assert.deepEqual(response, result);
  assert.deepEqual(accepted, ['job']);
  assert.equal(paths[0], '/backtests/jobs?compare=true');
  assert.equal(waits, 2);
  assert.deepEqual(progress, ['Replaying', 'Replaying', 'Done']);
  assert.equal(paths.at(-1), '/backtests/jobs/job/result');
});

test('reconnecting to a persisted job never submits another backtest', async () => {
  const paths = [];
  const result = await followBacktestJob('existing', { send: async path => {
    paths.push(path);
    return path.endsWith('/result') ? { status: 'COMPLETED', trades: [] } : { status: 'COMPLETED' };
  } });
  assert.equal(result.status, 'COMPLETED');
  assert.deepEqual(paths, ['/backtests/jobs/existing', '/backtests/jobs/existing/result']);
});

test('historical failures surface their useful reason and stop polling', async () => {
  await assert.rejects(followBacktestJob('job', { send: async () => ({ status: 'FAILED', error: 'Historical catalogue unavailable' }) }),
    error => error.terminal && error.message === 'Historical catalogue unavailable');
});

test('leaving the page aborts polling without cancelling server work or resubmitting', async () => {
  const controller = new AbortController();
  let calls = 0;
  await assert.rejects(followBacktestJob('job', { signal: controller.signal, send: async () => {
    calls++; controller.abort(); return { status: 'RUNNING' };
  } }), { name: 'AbortError' });
  assert.equal(calls, 1);
  await assert.rejects(waitForPoll(controller.signal), { name: 'AbortError' });
});
