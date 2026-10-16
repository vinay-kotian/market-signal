import test from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { createServer } from 'vite';
import { JSDOM } from 'jsdom';
import { levelsForDate, levelsForRange } from './format.js';
import { applyLiveEvent } from './liveFeed.js';
import { parseLevels, eventsForTrade } from './backtestInput.js';
import { loadReport, exportReport, loadStrategyComparison } from './reportFilters.js';

const response = value => ({ ok: true, status: 200, json: async () => value });

test('level ranges use inclusive trading dates and retain current dashboard and all-date scopes', () => {
  const levels = [
    { id: 1, price: 100, instrument: 'NIFTY', level_date: '2026-10-16', created_at: '2026-10-14T10:00:00Z' },
    { id: 2, price: 9, instrument: 'NIFTY', level_date: '2026-10-14', created_at: '2026-10-16T10:00:00Z' },
    { id: 3, price: 20, instrument: 'SENSEX', level_date: '2026-10-15' },
    { id: 4, price: 2, instrument: 'NIFTY', level_date: '2026-10-17' },
  ];
  const range = { fromDate: '2026-10-14', toDate: '2026-10-15' };
  assert.deepEqual(levelsForRange(levels, range).map(row => row.id), [2, 3]);
  assert.deepEqual(levelsForRange(levels, range).filter(row => row.instrument === 'NIFTY').map(row => row.id), [2]);
  assert.deepEqual(levelsForRange(levels, { fromDate: '2026-10-15', toDate: '2026-10-15' }).map(row => row.id), [3]);
  assert.deepEqual(levelsForRange(levels, { fromDate: '2026-10-12', toDate: '2026-10-13' }), []);
  assert.deepEqual(levelsForDate(levels, '2026-10-16').map(row => row.id), [1]);
  assert.equal(levelsForDate(levels, '2026-10-16', 'ALL').length, 4);
  const updated = applyLiveEvent({ levels }, { type: 'LEVEL_UPDATED', data: { level: { ...levels[0], level_date: '2026-10-15' } } });
  assert.deepEqual(levelsForRange(updated.levels, range).map(row => row.id), [2, 3, 1]);
  assert.deepEqual(levelsForRange([...updated.levels].reverse(), range).map(row => row.id), [2, 3, 1]);
  assert.equal(levels[0].level_date, '2026-10-16');
});

async function setup(t, path, props = {}, fetch = async () => response(['5m', '15m', '1h', '1d']), name = 'default') {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost' });
  const restore = [];
  for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document,
    navigator: dom.window.navigator, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })) {
    const prior = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    restore.push(() => prior ? Object.defineProperty(globalThis, key, prior) : delete globalThis[key]);
  }
  t.mock.method(globalThis, 'fetch', fetch);
  const { createRoot } = await import('react-dom/client');
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  const mod = await server.ssrLoadModule(path);
  const root = createRoot(document.getElementById('root'));
  t.after(async () => { await act(() => root.unmount()); await server.close(); dom.window.close(); restore.forEach(fn => fn()); });
  await act(() => root.render(React.createElement(mod[name], props)));
  return { dom, async change(selector, value) {
    const field = document.querySelector(selector);
    assert.ok(field);
    await act(() => {
      Object.getOwnPropertyDescriptor(field.tagName === 'SELECT' ? dom.window.HTMLSelectElement.prototype : dom.window.HTMLInputElement.prototype, 'value').set.call(field, value);
      field.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
      field.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
    });
  }, async submit() { await act(() => document.querySelector('form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }))); } };
}

test('level form edits date, price and structured timeframe in one payload', async t => {
  const saves = [];
  const ui = await setup(t, '/src/LevelForm.jsx', { level: { id: 1, instrument: 'NIFTY', price: 25000,
    enabled: true, level_date: '2026-09-14', timeframe: '5m' }, onSave: value => saves.push(value) });
  assert.equal(document.querySelector('input[type="date"]').disabled, false);
  await ui.change('input[type="date"]', '2026-09-15');
  await ui.change('input[type="number"]', '25100');
  await ui.change('select:has(option[value="1h"])', '1h');
  await ui.submit();
  assert.deepEqual(saves, [{ instrument: 'NIFTY', price: 25100, enabled: true, level_date: '2026-09-15', timeframe: '1h' }]);
});

test('legacy timeframe stays unknown and configured choices are available for creation', async t => {
  const saves = [];
  const ui = await setup(t, '/src/LevelForm.jsx', { instrument: 'NIFTY', onSave: value => saves.push(value) },
    async () => response(['5m', '15m', '1h', '1d', '30m']));
  const select = document.querySelector('select:has(option[value="30m"])');
  assert.equal(select.value, '');
  await ui.change('input[type="number"]', '25000');
  await ui.submit();
  assert.equal(saves[0].timeframe, null);
  await ui.change('select:has(option[value="30m"])', '30m');
  await ui.submit();
  assert.equal(saves[1].timeframe, '30m');
});

test('numeric ordering and date/instrument filters survive events, deletion and refresh', () => {
  let state = { levels: [
    { id: 1, price: 100, instrument: 'NIFTY', level_date: '2026-09-14' },
    { id: 2, price: 9, instrument: 'NIFTY', level_date: '2026-09-14' },
    { id: 3, price: 20, instrument: 'SENSEX', level_date: '2026-09-14' },
  ] };
  const rows = () => levelsForDate(state.levels, '2026-09-14').filter(row => row.instrument === 'NIFTY');
  assert.deepEqual(rows().map(row => row.price), [9, 100]);
  state = applyLiveEvent(state, { type: 'LEVEL_UPDATED', data: { level: { ...state.levels[0], price: 2 } } });
  assert.deepEqual(rows().map(row => row.price), [2, 9]);
  state = applyLiveEvent(state, { type: 'LEVEL_UPDATED', data: { level: { ...state.levels[0], level_date: '2026-09-15' } } });
  assert.deepEqual(rows().map(row => row.price), [9]);
  assert.deepEqual(levelsForDate(state.levels, '2026-09-14', 'ALL').map(row => row.price), [2, 9, 20]);
  state = applyLiveEvent(state, { type: 'LEVEL_DELETED', data: { id: 2 } });
  assert.deepEqual(rows(), []);
  state = { levels: [...state.levels].reverse() };
  assert.deepEqual(levelsForDate(state.levels, '2026-09-14', 'ALL').map(row => row.price), [2, 20]);
});

test('report summary, history, bulk IDs, comparison and CSV share timeframe scope', async () => {
  const paths = [];
  const send = async path => { paths.push(path); return {}; };
  const filters = { view: 'RAW', fromDate: '2026-09-14', toDate: '2026-09-14', page: 1, timeframe: '1h' };
  await loadReport(filters, { send });
  await loadStrategyComparison(filters, { send });
  await exportReport(filters, { send, apiKey: 'test' });
  assert.equal(paths.length, 5);
  assert.ok(paths.every(path => new URL(path, 'http://localhost').searchParams.get('timeframe') === '1h'));
});

const trade = { trade_id: 1, signal_id: 1, level_id: 1, option_selection_id: 1, instrument: 'NIFTY',
  trigger_level: 25000, timeframe: '15m', option_symbol: 'SIMPE', entry_time: '2026-09-14T10:00:00+05:30',
  status: 'OPEN', trade_mode: 'PAPER', strategy_type: 'LEGACY' };

test('trade tables display recorded and historical unknown timeframes', async t => {
  await setup(t, '/src/TradesPage.jsx', { trades: [trade, { ...trade, trade_id: 2, timeframe: null }] }, undefined, 'TradesTable');
  assert.ok([...document.querySelectorAll('th')].some(node => node.textContent === 'Timeframe'));
  assert.equal(document.querySelectorAll('tbody tr')[0].children[1].textContent, '15m');
  assert.equal(document.querySelectorAll('tbody tr')[1].children[1].textContent, 'Not recorded');
});

test('Reports shows timeframe in history and detail, and applies the selector', async t => {
  const paths = [];
  const ui = await setup(t, '/src/PaperReportPage.jsx', {}, async path => {
    paths.push(path);
    if (path.includes('/levels/timeframes')) return response(['5m', '15m', '1h', '1d']);
    if (path.includes('/trades/history/ids')) return response([1]);
    if (path.includes('/trades/history')) return response({ items: [trade], total: 1, page_size: 20 });
    if (path.endsWith('/trades/1')) return response({ trade, events: [] });
    return response({});
  });
  const headers = [...document.querySelectorAll('.ms-report-table th')].map(node => node.textContent);
  assert.equal(headers[3], 'Timeframe');
  assert.equal(document.querySelector('.ms-report-table tbody tr').children[3].textContent, '15m');
  await act(() => document.querySelector('[aria-label="View trade 1 timeline"]').click());
  assert.match(document.querySelector('[aria-label="Trade 1 timeline"]').textContent, /Timeframe: 15m/);
  paths.length = 0;
  await ui.change('select:has(option[value="UNKNOWN"])', 'UNKNOWN');
  const scoped = paths.filter(path => !path.includes('/levels/'));
  assert.ok(scoped.length >= 3);
  assert.ok(scoped.every(path => new URL(path, 'http://localhost').searchParams.get('timeframe') === 'UNKNOWN'));
});

test('backtest inputs retain same-price different durations and reports display the snapshot', async t => {
  assert.deepEqual(parseLevels('25000@5m,25000@1h 25000@5m 25000'), [
    { price: 25000, timeframe: '5m' }, { price: 25000, timeframe: '1h' }, 25000]);
  assert.throws(() => parseLevels('25000@bad'));
  const result = { status: 'COMPLETED', instrument: 'NIFTY', trading_date: '2026-09-14',
    trades: [trade], signals: [], option_selections: [], entry_results: [], timeline: [] };
  await setup(t, '/src/BacktestPage.jsx', { result, setSelectedTrade: () => {} }, undefined, 'BacktestResults');
  assert.equal(document.querySelector('table thead tr').children[2].textContent, 'Timeframe');
  assert.equal(document.querySelector('table tbody tr').children[2].textContent, '15m');
  const timeline = [{ id: 1, trade_id: null, payload: { level_id: 1, level: 25000, timeframe: '15m' } },
    { id: 2, trade_id: null, payload: { level_id: 2, level: 25000, timeframe: '1h' } }];
  assert.deepEqual(eventsForTrade(timeline, trade).map(row => row.id), [1]);
});
