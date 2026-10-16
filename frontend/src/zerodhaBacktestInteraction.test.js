import test from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { JSDOM } from 'jsdom';
import { createServer } from 'vite';

async function setup(t, send, storedJob) {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost' });
  if (storedJob) dom.window.sessionStorage.setItem('market-signal-backtest-job', JSON.stringify(storedJob));
  const restore = [];
  for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document,
    navigator: dom.window.navigator, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })) {
    const prior = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    restore.push(() => prior ? Object.defineProperty(globalThis, name, prior) : delete globalThis[name]);
  }
  t.mock.method(globalThis, 'fetch', send);
  const { createRoot } = await import('react-dom/client');
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  const { default: Page } = await server.ssrLoadModule('/src/BacktestPage.jsx');
  const root = createRoot(document.getElementById('root'));
  t.after(async () => { await act(() => root.unmount()); await server.close(); dom.window.close(); restore.forEach(fn => fn()); });
  await act(() => root.render(React.createElement(Page)));
  return dom;
}
const response = value => ({ ok: true, status: 200, json: async () => value });
const saved = path => [{ id: 1, instrument: 'NIFTY', price: 25000, level_date: new URL(path, 'http://localhost').searchParams.get('level_date'), timeframe: null }];
const settings = { exit_strategy: 'ATR', latest_completed_session: '2026-10-09', zerodha_historical_available: true };

test('Zerodha backtest submits selected date/strategy, shows loading and broker error, preserves demo', async t => {
  const writes = []; let resolveRun;
  const dom = await setup(t, async (path, options = {}) => {
    if (path.endsWith('/backtests/settings')) return response(settings);
    if (path.includes('/levels?')) return response(saved(path));
    if (options.method === 'POST') { writes.push(JSON.parse(options.body)); return new Promise(resolve => { resolveRun = resolve; }); }
    return response([]);
  });
  const source = [...document.querySelectorAll('label')].find(n => n.textContent.startsWith('Price data')).querySelector('select');
  assert.equal(source.value, 'zerodha');
  assert.equal(document.querySelector('input[type="date"]').value, '2026-10-09');
  assert.match(document.body.textContent, /conservative candle assumptions/);
  await act(() => document.querySelector('form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })));
  assert.equal(writes[0].data_source, 'ZERODHA_HISTORICAL');
  assert.equal(writes[0].exit_strategy, 'ATR');
  assert.equal(writes[0].trading_date, '2026-10-09');
  assert.match(document.body.textContent, /Loading backtest/);
  assert.equal(document.querySelector('fieldset').disabled, true);
  await act(() => resolveRun({ ok: false, status: 422, json: async () => ({ detail: 'Historical option catalogue unavailable' }) }));
  assert.match(document.querySelector('[role="alert"]').textContent, /catalogue unavailable/);
  assert.equal(document.querySelector('fieldset').disabled, false);
  await act(() => { source.value = 'demo'; source.dispatchEvent(new dom.window.Event('change', { bubbles: true })); });
  await act(() => document.querySelector('form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })));
  assert.equal(writes[1].data_source, 'SIMULATED');
  assert.equal(writes[1].fixture, 'nifty-demo');
  assert.equal(writes[1].trading_date, '2026-09-14');
  await act(() => resolveRun({ ok: false, status: 422, json: async () => ({ detail: 'test finished' }) }));
});

test('historical result displays coverage, warnings, gross/net costs and approximation', async t => {
  const result = { id: 'run', status: 'COMPLETED', instrument: 'NIFTY', trading_date: '2026-10-09',
    data_source: 'ZERODHA_HISTORICAL', data_resolution: '1_MINUTE_OHLC', execution_model: 'CANDLE_APPROXIMATION',
    settings_snapshot: settings, historical_data_coverage: { catalogue_observed_at: '2026-10-09',
      symbols: { NIFTY: { complete: true, received_minutes: 375, expected_minutes: 375 } }, assumptions: ['No intraminute index path inferred'] },
    data_warnings: ['ATR warmup unavailable'], trades: [], signals: [], entry_results: [], option_selections: [], timeline: [],
    costs_supported: true, gross_pnl: 100, transaction_costs: 4, net_pnl: 96, ticks_processed: 375 };
  const dom = await setup(t, async (path, options = {}) => response(path.endsWith('/settings') ? settings : path.includes('/levels?') ? saved(path) : path.endsWith('/result') ? result : path.includes('/backtests/jobs') ? { id: 'job', kind: 'RUN', status: 'COMPLETED' } : []));
  await act(() => document.querySelector('form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })));
  assert.match(document.body.textContent, /1_MINUTE_OHLC/);
  assert.match(document.body.textContent, /CANDLE_APPROXIMATION/);
  assert.match(document.body.textContent, /375\/375 minutes/);
  assert.match(document.body.textContent, /ATR warmup unavailable/);
  assert.match(document.body.textContent, /Gross P&L 100/);
  assert.match(document.body.textContent, /Transaction costs 4/);
});

async function change(dom, selector, value) {
  const field = typeof selector === 'string' ? document.querySelector(selector) : selector;
  assert.ok(field);
  const prototype = field.tagName === 'TEXTAREA' ? dom.window.HTMLTextAreaElement.prototype
    : field.tagName === 'SELECT' ? dom.window.HTMLSelectElement.prototype : dom.window.HTMLInputElement.prototype;
  await act(() => {
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(field, value);
    field.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    field.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  });
}

test('backtest auto-loads levels for date and index, keeps edits and submits them without changing saved levels', async t => {
  const writes = [], lookups = [];
  const records = [
    { id: 1, instrument: 'NIFTY', level_date: '2026-10-09', price: 25000, timeframe: '5m' },
    { id: 2, instrument: 'NIFTY', level_date: '2026-10-09', price: 25000, timeframe: '1h' },
    { id: 3, instrument: 'BANKNIFTY', level_date: '2026-10-09', price: 51000, timeframe: null },
    { id: 4, instrument: 'BANKNIFTY', level_date: '2026-10-08', price: 51200, timeframe: '15m' },
  ];
  const dom = await setup(t, async (path, options = {}) => {
    if (path.endsWith('/backtests/settings')) return response(settings);
    if (path.includes('/levels?')) { lookups.push(path); return response(records); }
    if (options.method === 'POST') {
      writes.push({ path, body: JSON.parse(options.body) });
      return { ok: false, status: 422, json: async () => ({ detail: 'No historical data fixture for this UI test' }) };
    }
    return response([]);
  });
  assert.equal(document.querySelector('textarea').value, '25000@5m\n25000@1h');
  await change(dom, 'textarea', '25100@15m');
  const count = lookups.length;
  await change(dom, 'select:has(option[value="LEGACY"])', 'LEGACY');
  assert.equal(document.querySelector('textarea').value, '25100@15m');
  assert.equal(lookups.length, count);
  await act(() => document.querySelector('form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })));
  assert.deepEqual(writes[0].body.levels, [{ price: 25100, timeframe: '15m' }]);
  assert.ok(writes.every(write => write.path.includes('/backtests/')));
  assert.equal(document.querySelector('textarea').value, '25100@15m');
  await act(() => [...document.querySelectorAll('button')].find(node => node.textContent === 'Reload saved levels').click());
  assert.equal(document.querySelector('textarea').value, '25000@5m\n25000@1h');
  await change(dom, [...document.querySelectorAll('label')].find(node => node.textContent.startsWith('Instrument')).querySelector('select'), 'BANKNIFTY');
  assert.equal(document.querySelector('textarea').value, '51000');
  await change(dom, 'input[type="date"]', '2026-10-08');
  assert.equal(document.querySelector('textarea').value, '51200@15m');
  await change(dom, 'input[type="date"]', '2026-10-07');
  assert.equal(document.querySelector('textarea').value, '');
  assert.match(document.body.textContent, /No saved levels for BANKNIFTY on 2026-10-07/);
});

test('slow saved-level responses cannot overwrite edits or another date, and load errors allow manual entry', async t => {
  let pending = [], fail = false;
  const dom = await setup(t, async path => {
    if (path.endsWith('/backtests/settings')) return response(settings);
    if (path.includes('/levels?')) {
      if (fail) return { ok: false, status: 503, json: async () => ({ detail: 'Levels unavailable' }) };
      return new Promise(resolve => pending.push({ path, resolve }));
    }
    return response([]);
  });
  assert.equal([...document.querySelectorAll('button')].find(node => node.textContent === 'Run Backtest').disabled, true);
  await change(dom, 'textarea', '25200@1d');
  await act(() => { pending.forEach(item => item.resolve(response(saved(item.path)))); });
  assert.equal(document.querySelector('textarea').value, '25200@1d');
  assert.match(document.body.textContent, /Edited levels will be used/);
  pending = [];
  await change(dom, 'input[type="date"]', '2026-10-08');
  await change(dom, 'input[type="date"]', '2026-10-07');
  const latest = pending.find(item => item.path.includes('2026-10-07'));
  await act(() => latest.resolve(response([{ ...saved(latest.path)[0], price: 24000 }])));
  await act(() => pending.filter(item => item !== latest).forEach(item => item.resolve(response(saved(item.path)))));
  assert.equal(document.querySelector('textarea').value, '24000');
  fail = true;
  await change(dom, 'input[type="date"]', '2026-10-06');
  assert.match(document.body.textContent, /Could not load saved levels: Levels unavailable/);
  assert.equal(document.querySelector('textarea').value, '');
  await change(dom, 'textarea', '26000');
  assert.equal([...document.querySelectorAll('button')].find(node => node.textContent === 'Run Backtest').disabled, false);
  assert.equal(document.querySelector('textarea').value, '26000');
});


test('Backtest reconnects to its saved job after page reload without a new submission', async t => {
  const paths = [];
  const result = { id: 'resumed', status: 'COMPLETED', instrument: 'NIFTY', trading_date: '2026-10-09',
    settings_snapshot: settings, trades: [], signals: [], entry_results: [], option_selections: [], timeline: [] };
  await setup(t, async (path, options = {}) => {
    paths.push({ path, method: options.method });
    if (path.endsWith('/backtests/settings')) return response(settings);
    if (path.endsWith('/result')) return response(result);
    if (path.includes('/backtests/jobs/')) return response({ status: 'COMPLETED', message: 'Backtest completed' });
    if (path.includes('/levels?')) return response(saved(path));
    return response([]);
  }, { id: 'existing', kind: 'RUN' });
  assert.ok(paths.some(item => item.path === '/api/backtests/jobs/existing'));
  assert.ok(paths.every(item => item.method !== 'POST'));
  assert.match(document.querySelector('[aria-label="Backtest results"]').textContent, /resumed/);
  assert.equal(window.sessionStorage.getItem('market-signal-backtest-job'), null);
});
