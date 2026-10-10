import test from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { JSDOM } from 'jsdom';
import { createServer } from 'vite';
import { loadStrategyComparison } from './reportFilters.js';

const metrics = { total_trades: 4, win_rate: 50, net_pnl: 250, profit_factor: 2,
  max_drawdown: 50, average_r: null, average_r_sample_size: 0, sl_hits: 1 };
const saved = { strategies: { LEGACY: metrics, ATR: { ...metrics, average_r: 1.25, average_r_sample_size: 4 } } };
const props = { fromDate: '2026-10-03', toDate: '2026-10-03', view: 'RAW', status: '', instrument: '', refreshKey: 0 };

test('comparison queries share dates, view and instrument without strategy or pagination restrictions', async () => {
  let path;
  await loadStrategyComparison({ ...props, strategyType: 'ATR', page: 2, instrument: 'NIFTY', status: 'CLOSED' }, { send: async value => { path = value; } });
  const url = new URL(path, 'http://localhost');
  assert.equal(url.pathname, '/reports/strategy-comparison');
  assert.equal(url.searchParams.get('from_date'), props.fromDate);
  assert.equal(url.searchParams.get('to_date'), props.toDate);
  assert.equal(url.searchParams.get('view'), 'RAW');
  assert.equal(url.searchParams.get('status'), 'CLOSED');
  assert.equal(url.searchParams.get('instrument'), 'NIFTY');
  assert.equal(url.searchParams.has('strategy_type'), false);
  assert.equal(url.searchParams.has('page'), false);
  await assert.rejects(loadStrategyComparison({ ...props, fromDate: '2026-10-04' }, { send: () => { throw Error('unexpected request'); } }), /From Date/);
});

test('comparison renders metrics, refreshes dates and handles failure/retry and invalid ranges', async t => {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost' });
  const restore = [];
  for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document,
    navigator: dom.window.navigator, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })) {
    const prior = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    restore.push(() => prior ? Object.defineProperty(globalThis, name, prior) : delete globalThis[name]);
  }
  const calls = []; let fail = false;
  t.mock.method(globalThis, 'fetch', async path => {
    calls.push(path);
    return { ok: !fail, status: fail ? 500 : 200, json: async () => fail ? { detail: 'Report unavailable' } : saved };
  });
  const { createRoot } = await import('react-dom/client');
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  const { default: Comparison } = await server.ssrLoadModule('/src/StrategyPerformanceComparison.jsx');
  const root = createRoot(document.getElementById('root'));
  t.after(async () => { await act(() => root.unmount()); await server.close(); dom.window.close(); restore.forEach(fn => fn()); });
  await act(() => root.render(React.createElement(Comparison, props)));
  assert.equal(document.querySelectorAll('tbody tr').length, 7);
  assert.match(document.body.textContent, /LEGACY.*ATR/);
  assert.match(document.body.textContent, /Average R—1.25/);
  assert.match(document.body.textContent, /excludes brokerage and slippage/);
  fail = true;
  await act(() => root.render(React.createElement(Comparison, { ...props, toDate: '2026-10-04' })));
  assert.match(calls.at(-1), /to_date=2026-10-04/);
  assert.match(document.querySelector('[role="alert"]').textContent, /Report unavailable/);
  assert.equal(document.querySelector('table'), null);
  fail = false; await act(() => document.querySelector('button').click());
  assert.ok(document.querySelector('table'));
  const count = calls.length;
  await act(() => root.render(React.createElement(Comparison, { ...props, fromDate: '2026-10-05' })));
  assert.equal(calls.length, count);
  assert.equal(document.querySelector('table'), null);
});
