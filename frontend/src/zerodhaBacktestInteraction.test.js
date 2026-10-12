import test from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
import { createServer } from 'vite';

async function setup(t, send) {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost' });
  const restore = [];
  for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document,
    navigator: dom.window.navigator, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })) {
    const prior = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    restore.push(() => prior ? Object.defineProperty(globalThis, name, prior) : delete globalThis[name]);
  }
  t.mock.method(globalThis, 'fetch', send);
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  const { default: Page } = await server.ssrLoadModule('/src/BacktestPage.jsx');
  const root = createRoot(document.getElementById('root'));
  t.after(async () => { await act(() => root.unmount()); await server.close(); dom.window.close(); restore.forEach(fn => fn()); });
  await act(() => root.render(React.createElement(Page)));
  return dom;
}
const response = value => ({ ok: true, status: 200, json: async () => value });
const settings = { exit_strategy: 'ATR', latest_completed_session: '2026-10-09', zerodha_historical_available: true };

test('Zerodha backtest submits selected date/strategy, shows loading and broker error, preserves demo', async t => {
  const writes = []; let resolveRun;
  const dom = await setup(t, async (path, options = {}) => {
    if (path.endsWith('/backtests/settings')) return response(settings);
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
  const dom = await setup(t, async (path, options = {}) => response(path.endsWith('/settings') ? settings : options.method === 'POST' ? result : []));
  await act(() => document.querySelector('form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })));
  assert.match(document.body.textContent, /1_MINUTE_OHLC/);
  assert.match(document.body.textContent, /CANDLE_APPROXIMATION/);
  assert.match(document.body.textContent, /375\/375 minutes/);
  assert.match(document.body.textContent, /ATR warmup unavailable/);
  assert.match(document.body.textContent, /Gross P&L 100/);
  assert.match(document.body.textContent, /Transaction costs 4/);
});
