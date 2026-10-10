import test from 'node:test';
import assert from 'node:assert/strict';
import React, { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createServer } from 'vite';
import { JSDOM } from 'jsdom';

async function setup(t) {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost' });
  t.mock.method(globalThis, 'fetch', async () => { throw new Error('Unexpected request'); });
  const restoreGlobals = [];
  for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document,
    HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true,
    requestAnimationFrame: callback => { callback(); } })) {
    const prior = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    restoreGlobals.push(() => prior ? Object.defineProperty(globalThis, name, prior) : delete globalThis[name]);
  }
  // JSDOM has no layout engine; supply visible rectangles for keyboard focus tests.
  dom.window.HTMLElement.prototype.getClientRects = () => [{ width: 40, height: 40 }];
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  const root = createRoot(document.getElementById('root'));
  t.after(async () => {
    t.mock.timers.reset();
    await act(() => root.unmount()); await server.close(); dom.window.close();
    restoreGlobals.forEach(restore => restore());
  });
  t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-10-10T04:30:00Z') });
  const click = async node => { assert.ok(node); await act(() => node.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))); };
  const button = text => [...document.querySelectorAll('button')].find(node => node.textContent === text);
  return { server, root, click, button, dom };
}

test('calendar drafts custom ranges, same-day selection, presets, future restriction and cancellation', async t => {
  const { server, root, click, button } = await setup(t);
  const { default: Filter } = await server.ssrLoadModule('/src/DateRangeFilter.jsx');
  const applied = [], changed = [];
  function Harness() {
    const [range, setRange] = useState({ fromDate: '2026-10-10', toDate: '2026-10-10' });
    return React.createElement(Filter, { range, onChange: next => changed.push(next), onApply(next) { applied.push(next); setRange(next); } });
  }
  await act(() => root.render(React.createElement(Harness)));
  await click(button('Today ▾'));
  assert.equal(document.querySelectorAll('.ms-date-months section').length, 2);
  assert.ok(document.querySelector('[data-day="2026-10-11"]').disabled);
  await click(document.querySelector('[data-day="2026-10-03"]'));
  assert.ok(button('Apply').disabled);
  assert.equal(applied.length, 0);
  await click(document.querySelector('[data-day="2026-10-06"]'));
  assert.equal(document.querySelectorAll('.ms-date-between').length, 2);
  await click(button('Apply'));
  assert.deepEqual(applied[0], { fromDate: '2026-10-03', toDate: '2026-10-06' });
  assert.equal(document.activeElement.textContent, '3 Oct 2026 – 6 Oct 2026 ▾');
  await click(document.activeElement);
  await click(document.querySelector('[data-day="2026-10-05"]'));
  await click(document.querySelector('[data-day="2026-10-05"]'));
  await click(button('Apply'));
  assert.deepEqual(applied[1], { fromDate: '2026-10-05', toDate: '2026-10-05' });
  await click(document.activeElement);
  await click(button('Yesterday'));
  assert.equal(document.querySelector('[data-day="2026-10-09"]').getAttribute('aria-pressed'), 'true');
  await click(button('Cancel'));
  assert.equal(applied.length, 2);
  await click(document.activeElement);
  await click(button('Yesterday')); await click(button('Apply'));
  assert.equal(button('Yesterday ▾').getAttribute('aria-expanded'), 'false');
  assert.ok(changed.length >= 6);
});

test('single-day calendar supports month navigation, arrow keys, escape and focus trapping', async t => {
  const { server, root, click, button, dom } = await setup(t);
  const { default: Filter } = await server.ssrLoadModule('/src/DateRangeFilter.jsx');
  let applied;
  await act(() => root.render(React.createElement(Filter, { singleDay: true,
    range: { fromDate: '2026-10-10', toDate: '2026-10-10' }, onApply: next => { applied = next; } })));
  await click(button('Today ▾'));
  assert.equal(document.activeElement.textContent, 'Today');
  await act(() => document.activeElement.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true })));
  assert.equal(document.activeElement.textContent, 'Apply');
  await click(document.querySelector('[aria-label="Previous month"]'));
  const day = document.querySelector('[data-day="2026-09-30"]'); day.focus();
  await act(() => day.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })));
  assert.equal(document.activeElement.dataset.day, '2026-10-01');
  await click(document.activeElement); await click(button('Apply'));
  assert.deepEqual(applied, { fromDate: '2026-10-01', toDate: '2026-10-01' });
  await click(button('Today ▾'));
  await act(() => document.activeElement.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  assert.equal(document.querySelector('[role="dialog"]'), null);
  assert.equal(document.activeElement.textContent, 'Today ▾');
});

test('selection history applies once, preserves dates on pagination and refresh, and keeps dashboard sections independent', async t => {
  const { server, root, click, button } = await setup(t);
  const { default: Selections } = await server.ssrLoadModule('/src/OptionSelectionsTable.jsx');
  const { default: Signals } = await server.ssrLoadModule('/src/SignalsTable.jsx');
  const urls = [];
  globalThis.fetch = async path => {
    urls.push(new URL(path, 'http://localhost'));
    return { ok: true, json: async () => path.includes('option-selections') ? { items: [], total: 25, page_size: 20 } : [] };
  };
  function Harness({ refreshKey = 0 }) { return React.createElement(React.Fragment, null,
    React.createElement(Selections, { refreshKey }), React.createElement(Signals, { refreshKey })); }
  await act(() => root.render(React.createElement(Harness)));
  assert.equal(urls.length, 2);
  await click(button('Today ▾'));
  await click(document.querySelector('[data-day="2026-10-02"]'));
  await click(document.querySelector('[data-day="2026-10-06"]'));
  assert.equal(urls.length, 2);
  await click(button('Apply'));
  assert.equal(urls.length, 3);
  await click(button('Next'));
  assert.equal(urls.length, 4);
  assert.equal(urls.at(-1).searchParams.get('page'), '2');
  await act(() => root.render(React.createElement(Harness, { refreshKey: 1 })));
  const selections = urls.filter(url => url.pathname.includes('option-selections'));
  assert.equal(selections.length, 4);
  for (const url of selections.slice(1)) {
    assert.equal(url.searchParams.get('from_date'), '2026-10-02');
    assert.equal(url.searchParams.get('to_date'), '2026-10-06');
  }
  assert.equal(urls.filter(url => url.pathname.endsWith('/signals')).length, 2);
});

test('preset hook follows IST midnight while an explicit historical date stays fixed', async t => {
  const { server, root, click, button } = await setup(t);
  t.mock.timers.reset();
  t.mock.timers.enable({ apis: ['Date', 'setInterval'], now: new Date('2026-10-09T18:29:59.500Z') });
  const { useDateRange } = await server.ssrLoadModule('/src/useDateRange.js');
  function Harness() {
    const [range, apply] = useDateRange();
    return React.createElement('button', { onClick: () => apply({ fromDate: '2026-10-03', toDate: '2026-10-03' }, 'CUSTOM') }, range.fromDate);
  }
  await act(() => root.render(React.createElement(Harness)));
  assert.ok(button('2026-10-09'));
  await act(() => t.mock.timers.tick(1000));
  assert.ok(button('2026-10-10'));
  await click(button('2026-10-10'));
  await act(() => t.mock.timers.tick(86400000));
  assert.ok(button('2026-10-03'));
});

test('empty controlled range opens safely and requires a valid selection before Apply', async t => {
  const { server, root, click, button } = await setup(t);
  const { default: Filter } = await server.ssrLoadModule('/src/DateRangeFilter.jsx');
  const applied = [];
  await act(() => root.render(React.createElement(Filter, { range: { fromDate: '', toDate: '' }, onApply: next => applied.push(next) })));
  await click(button('Choose dates ▾'));
  assert.ok(button('Apply').disabled);
  assert.equal(applied.length, 0);
  await click(button('Reset')); await click(button('Apply'));
  assert.deepEqual(applied, [{ fromDate: '2026-10-10', toDate: '2026-10-10' }]);
});

test('calendar repositions on viewport resize and page scroll without losing its selected range', async t => {
  const { server, root, click, button, dom } = await setup(t);
  const { default: Filter } = await server.ssrLoadModule('/src/DateRangeFilter.jsx');
  Object.defineProperty(dom.window, 'innerWidth', { configurable: true, writable: true, value: 1400 });
  Object.defineProperty(dom.window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  Object.defineProperty(dom.window.HTMLElement.prototype, 'offsetWidth', { configurable: true, get: () => 600 });
  Object.defineProperty(dom.window.HTMLElement.prototype, 'scrollHeight', { configurable: true, get: () => 470 });
  await act(() => root.render(React.createElement(Filter, { range: { fromDate: '2026-10-03', toDate: '2026-10-06' } })));
  const trigger = button('3 Oct 2026 – 6 Oct 2026 ▾');
  trigger.getBoundingClientRect = () => ({ left: 1100, top: 300, bottom: 340 });
  await click(trigger);
  const panel = document.querySelector('[role="dialog"]');
  assert.equal(panel.style.left, '788px');
  assert.equal(panel.style.top, '348px');
  dom.window.innerHeight = 680;
  await act(() => dom.window.dispatchEvent(new dom.window.Event('resize')));
  assert.equal(panel.style.top, '198px');
  assert.equal(panel.style.maxHeight, '656px');
  trigger.getBoundingClientRect = () => ({ left: 300, top: 100, bottom: 140 });
  await act(() => dom.window.dispatchEvent(new dom.window.Event('scroll')));
  assert.equal(panel.style.left, '300px');
  assert.equal(panel.style.top, '148px');
  assert.equal(document.querySelectorAll('.ms-date-between').length, 2);
});

test('Reports CSV button uses the shared custom range and shows download errors', async t => {
  const { server, root, click, button, dom } = await setup(t);
  const urls = [];
  t.mock.method(globalThis, 'fetch', async url => {
    urls.push(url);
    const data = url.includes('/trades/history/ids') ? []
      : url.includes('/trades/history') ? { items: [], total: 0, page_size: 20 }
      : { total_trades: 0, win_rate: 0, net_pnl: 0, profit_factor: null };
    return { ok: true, json: async () => data };
  });
  const { default: Reports } = await server.ssrLoadModule('/src/PaperReportPage.jsx');
  await act(() => root.render(React.createElement(Reports, { refreshKey: 0 })));
  await click(button('Today ▾'));
  await click(document.querySelector('[data-day="2026-10-03"]'));
  await click(document.querySelector('[data-day="2026-10-06"]'));
  await click(button('Apply'));
  assert.ok(button('3 Oct 2026 – 6 Oct 2026 ▾'));
  assert.equal(document.querySelector('input[type="password"]').autocomplete, 'off');
  assert.ok(!button('Download CSV').disabled);
  await act(async () => button('Download CSV').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
  assert.match(document.querySelector('[role="alert"]').textContent,
    /CSV export failed: Enter the API key to download CSV/);
  assert.ok(!button('Download CSV').disabled);
  assert.ok(!urls.some(url => url.includes('/reports/export')));
});
