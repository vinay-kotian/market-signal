import test from 'node:test';
import assert from 'node:assert/strict';
import { exportReport, saveCsv } from './reportFilters.js';
import { request } from './api.js';

const range = { fromDate: '2026-10-03', toDate: '2026-10-06' };

test('export sends selected range, mode, view and filters without pagination', async () => {
  for (const mode of ['PAPER', 'BACKTEST']) {
    const blob = new Blob(['trade_id\r\n1\r\n'], { type: 'text/csv' });
    const result = await exportReport({ ...range, mode, view: 'STRATEGY', status: 'CLOSED', instrument: 'NIFTY', page: 2 }, {
      apiKey: 'secret',
      send: async (path, options) => {
        const url = new URL(path, 'http://test');
        assert.equal(url.pathname, '/reports/export');
        assert.deepEqual(Object.fromEntries(url.searchParams), {
          view: 'STRATEGY', from_date: range.fromDate, to_date: range.toDate,
          status: 'CLOSED', instrument: 'NIFTY', mode,
        });
        assert.deepEqual(options, { headers: { 'X-API-Key': 'secret' }, responseType: 'blob' });
        assert.ok(!path.includes('secret'));
        return blob;
      },
    });
    assert.equal(result.blob, blob);
    assert.equal(result.filename, `trading-report-${mode}-2026-10-03-2026-10-06.csv`);
  }
});

test('export rejects incomplete ranges or missing credentials before requesting', async () => {
  let calls = 0;
  const options = { send: async () => { calls++; } };
  await assert.rejects(exportReport({ ...range, view: 'RAW', fromDate: '' }, options), /From Date/);
  await assert.rejects(exportReport({ ...range, view: 'RAW' }, options), /API key/);
  assert.equal(calls, 0);
});

test('CSV requests reuse API error handling and return a blob on success', async t => {
  const blob = new Blob(['trade_id\r\n']);
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/reports/export');
    assert.equal(options.headers['X-API-Key'], 'secret');
    assert.equal(options.responseType, undefined);
    return { ok: true, blob: async () => blob };
  });
  assert.equal(await request('/reports/export', { headers: { 'X-API-Key': 'secret' }, responseType: 'blob' }), blob);
  t.mock.method(globalThis, 'fetch', async () => ({ ok: false, status: 401,
    json: async () => ({ detail: 'Invalid or missing API key' }) }));
  await assert.rejects(exportReport({ ...range, view: 'RAW' }, { apiKey: 'wrong' }), /Invalid or missing API key/);
  t.mock.method(globalThis, 'fetch', async () => { throw new Error('Network unavailable'); });
  await assert.rejects(exportReport({ ...range, view: 'RAW' }, { apiKey: 'secret' }), /Network unavailable/);
});

test('download uses an attachment link and releases its object URL', t => {
  const blob = new Blob(['trade_id\r\n']);
  const link = { click() { this.clicked = true; }, remove() { this.removed = true; } };
  t.mock.method(URL, 'createObjectURL', value => { assert.equal(value, blob); return 'blob:csv'; });
  let revoked;
  t.mock.method(URL, 'revokeObjectURL', value => { revoked = value; });
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'document');
  Object.defineProperty(globalThis, 'document', { configurable: true, value: {
    createElement: tag => { assert.equal(tag, 'a'); return link; }, body: { appendChild() {} },
  } });
  t.after(() => previous ? Object.defineProperty(globalThis, 'document', previous) : delete globalThis.document);
  saveCsv({ blob, filename: 'report.csv' });
  assert.equal(link.download, 'report.csv');
  assert.equal(link.href, 'blob:csv');
  assert.ok(link.clicked && link.removed);
  assert.equal(revoked, undefined);
  t.mock.timers.tick(1000);
  assert.equal(revoked, 'blob:csv');
});
