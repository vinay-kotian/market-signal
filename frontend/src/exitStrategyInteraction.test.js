import test from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { createServer } from 'vite';
import { JSDOM } from 'jsdom';
import { loadReport, exportReport, loadTradeHistory } from './reportFilters.js';

const configuration = { atr_enabled: true, default_exit_strategy: 'LEGACY', instrument_overrides: {},
  atr_period: 14, atr_timeframe: '5minute', atr_initial_multiplier: 1.5, atr_trailing_mode: 'OFF',
  atr_trailing_multiplier: 2, atr_trailing_percentage: 10, atr_max_sl_percent: 15,
  atr_breakeven_activation_mode: 'OFF', atr_breakeven_activation_threshold: 1, atr_breakeven_lock_percent: 0 };
const initial = { configuration, daily: { trading_date: '2026-09-14', default_exit_strategy: null, instrument_overrides: {} },
  next_trade_overrides: {}, effective: { NIFTY: 'LEGACY' } };

async function setup(t, fetch, component = '/src/ExitStrategySettings.jsx') {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost' });
  const restore = [];
  for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document,
    navigator: dom.window.navigator, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })) {
    const prior = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    restore.push(() => prior ? Object.defineProperty(globalThis, name, prior) : delete globalThis[name]);
  }
  t.mock.method(globalThis, 'fetch', fetch);
  const { createRoot } = await import('react-dom/client');
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  const { default: Settings } = await server.ssrLoadModule(component);
  const root = createRoot(document.getElementById('root'));
  t.after(async () => { await act(() => root.unmount()); await server.close(); dom.window.close(); restore.forEach(fn => fn()); });
  await act(() => root.render(React.createElement(Settings)));
  const select = label => [...document.querySelectorAll('label')].find(node => node.textContent.startsWith(label))?.querySelector('select');
  const choose = async (label, value) => { const field = select(label); assert.ok(field); await act(() => { field.value = value; field.dispatchEvent(new dom.window.Event('change', { bubbles: true })); }); };
  const submit = async text => { const button = [...document.querySelectorAll('button')].find(node => node.textContent === text); assert.ok(button); await act(() => button.closest('form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }))); };
  return { select, choose, submit, dom };
}
const response = value => ({ ok: true, status: 200, json: async () => value });

test('exit settings save persistent and daily selections separately, and disable ATR selection', async t => {
  let saved = structuredClone(initial); const writes = [];
  const ui = await setup(t, async (path, options = {}) => {
    if (path.endsWith('/legacy')) return response({ stop_strategy: 'PROGRESSIVE', initial_stop_loss_pct: 10 });
    if (options.method === 'PUT') {
      const data = JSON.parse(options.body); writes.push({ path, data });
      if (path.endsWith('/daily')) saved.daily = data; else saved.configuration = data;
    }
    return response(saved);
  });
  assert.equal(ui.select('Persistent default').value, 'LEGACY');
  await ui.choose("Today's default", 'ATR');
  await ui.choose('NIFTY today', 'LEGACY');
  await ui.submit("Save today's selection");
  assert.ok(writes[0].path.endsWith('/daily'));
  assert.equal(writes[0].data.trading_date, '2026-09-14');
  assert.equal(writes[0].data.default_exit_strategy, 'ATR');
  assert.equal(writes[0].data.instrument_overrides.NIFTY, 'LEGACY');
  assert.equal(saved.configuration.default_exit_strategy, 'LEGACY');
  const toggle = document.querySelector('[role="switch"]');
  await act(() => toggle.click());
  assert.equal(ui.select('Persistent default').querySelector('option[value="ATR"]').disabled, true);
  await ui.submit('Save exit settings');
  assert.equal(writes[1].data.atr_enabled, false);
  assert.equal(writes[1].data.atr_initial_multiplier, 1.5);
});

test('exit settings retain unsaved choices and show server validation errors', async t => {
  const ui = await setup(t, async (path, options = {}) => {
    if (options.method === 'PUT') return { ok: false, status: 422, json: async () => ({ detail: 'ATR is disabled for new selections' }) };
    return response(path.endsWith('/legacy') ? { stop_strategy: 'PROGRESSIVE' } : initial);
  });
  await ui.choose('Persistent default', 'ATR'); await ui.submit('Save exit settings');
  assert.match(document.querySelector('[role="alert"]').textContent, /ATR is disabled/);
  assert.equal(ui.select('Persistent default').value, 'ATR');
});

test('strategy filter applies to reports, all matching IDs, trade history and CSV', async () => {
  const paths = []; const send = async path => { paths.push(path); return {}; };
  const filters = { fromDate: '2026-09-14', toDate: '2026-09-14', view: 'RAW', page: 1, strategyType: 'ATR' };
  await loadReport(filters, { send }); await loadTradeHistory(filters, { send });
  await exportReport(filters, { apiKey: 'example', send });
  assert.equal(paths.length, 5);
  for (const path of paths) assert.equal(new URL(path, 'http://localhost').searchParams.get('strategy_type'), 'ATR');
});


test('exit settings refresh the dated selection after IST midnight', async t => {
  t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-09-14T18:29:00Z') });
  t.after(() => t.mock.timers.reset());
  let day = '2026-09-14';
  const ui = await setup(t, async path => response(path.endsWith('/legacy') ? { stop_strategy: 'PROGRESSIVE' } : {
    ...initial, daily: { ...initial.daily, trading_date: day, default_exit_strategy: day === '2026-09-14' ? 'ATR' : null },
  }));
  assert.equal(ui.select("Today's default").value, 'ATR');
  day = '2026-09-15';
  t.mock.timers.setTime(new Date('2026-09-14T18:30:00Z').getTime());
  await act(() => window.dispatchEvent(new ui.dom.window.Event('focus')));
  assert.equal(ui.select("Today's default").value, '');
  assert.match(document.body.textContent, /Today's selection · 2026-09-15/);
});

test('backtest comparison sends selected ATR configuration and transaction costs', async t => {
  const writes = [];
  const atr = Object.fromEntries(Object.entries(configuration).filter(([key]) => key.startsWith('atr_') && key !== 'atr_enabled'));
  const ui = await setup(t, async (path, options = {}) => {
    if (path.endsWith('/settings')) return response({ exit_configuration: atr });
    if (options.method === 'POST') {
      writes.push({ path, data: JSON.parse(options.body) });
      return response({ runs: [], trading_date: '2026-09-14', instrument: 'NIFTY' });
    }
    return response([]);
  }, '/src/BacktestPage.jsx');
  await ui.choose('Exit strategy', 'ATR');
  const fee = [...document.querySelectorAll('label')].find(node => node.textContent === 'Transaction cost per order').querySelector('input');
  await act(() => {
    Object.getOwnPropertyDescriptor(ui.dom.window.HTMLInputElement.prototype, 'value').set.call(fee, '2.5');
    fee.dispatchEvent(new ui.dom.window.Event('input', { bubbles: true }));
  });
  const button = [...document.querySelectorAll('button')].find(node => node.textContent === 'Compare Current and six ATR multipliers');
  await act(() => button.click());
  assert.ok(writes[0].path.endsWith('/backtests/compare'));
  assert.equal(writes[0].data.exit_strategy, 'ATR');
  assert.equal(writes[0].data.transaction_cost_per_order, 2.5);
  assert.equal(writes[0].data.exit_configuration.atr_initial_multiplier, 1.5);
  assert.ok(document.querySelector('[aria-label="Exit strategy comparison"]'));
});
