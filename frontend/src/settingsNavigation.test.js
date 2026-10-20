import test from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { createServer } from 'vite';
import { JSDOM } from 'jsdom';

const config = { atr_enabled: true, default_exit_strategy: 'LEGACY', instrument_overrides: {},
  atr_period: 14, atr_initial_multiplier: 1.5, strategy3: { atr_period: 14, atr_multiplier: .75 } };
const snapshot = { configuration: config, daily: { trading_date: '2026-10-20', default_exit_strategy: null, instrument_overrides: {} },
  next_trade_overrides: {}, effective: { NIFTY: 'LEGACY' } };
const ids = ['connection', 'trading-time', 'index-rules', 'exit-strategy', 'exit-atr', 'exit-fixed', 'exit-daily', 'exit-legacy', 'notifications'];

async function setup(t, { hash = '', delayExit = false } = {}) {
  const dom = new JSDOM('<div id="root"></div>', { url: `http://localhost/settings${hash}` });
  const restore = [];
  for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement, MutationObserver: dom.window.MutationObserver, Event: dom.window.Event, IS_REACT_ACT_ENVIRONMENT: true })) {
    const old = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    restore.push(() => old ? Object.defineProperty(globalThis, name, old) : delete globalThis[name]);
  }
  let nextFrame = 0, releaseExit;
  const frames = new Map(), positions = new Map(ids.map((id, i) => [id, 200+i*300]));
  const scrolls = [];
  dom.window.requestAnimationFrame = fn => { frames.set(++nextFrame, fn); return nextFrame; };
  dom.window.cancelAnimationFrame = id => frames.delete(id);
  dom.window.HTMLElement.prototype.getBoundingClientRect = function () {
    return { top: positions.get(this.id) ?? 0, height: 0, bottom: (positions.get(this.id) ?? 0)+100 };
  };
  dom.window.HTMLElement.prototype.scrollIntoView = function () {
    const shift = (positions.get(this.id) ?? 0)-32;
    for (const [key, value] of positions) positions.set(key, value-shift);
    scrolls.push(this.id);
    dom.window.dispatchEvent(new dom.window.Event('scroll'));
  };
  const ready = delayExit ? new Promise(resolve => { releaseExit = resolve; }) : Promise.resolve();
  const writes = [];
  t.mock.method(globalThis, 'fetch', async (path, options = {}) => {
    if (options.method) writes.push(path);
    if (path === '/api/settings/exit-strategy') { await ready; return response(snapshot); }
    if (path.endsWith('/legacy')) return response({ stop_strategy: 'LEGACY', stop_loss_percentage: 10 });
    if (path.endsWith('/telegram')) return response({ enabled: false, url: '' });
    if (path.endsWith('/trading-time')) return response({ configuration: { market_open_time: '09:15:00', market_close_time: '15:30:00',
      entry_block_after_open_minutes: 15, entry_block_before_close_minutes: 15, mandatory_exit_before_close_minutes: 3 } });
    return response({});
  });
  const { createRoot } = await import('react-dom/client');
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  const { default: SettingsPage } = await server.ssrLoadModule('/src/SettingsPage.jsx');
  const root = createRoot(document.getElementById('root'));
  await act(() => root.render(React.createElement(SettingsPage, { indexes: [{ instrument: 'NIFTY', initial_arm_distance_points: 50 }], onRefresh() {} })));
  async function flush() {
    for (let i = 0; i < 8 && frames.size; i++) await act(async () => {
      const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(fn => fn()); await Promise.resolve();
    });
  }
  await flush();
  t.after(async () => { releaseExit?.(); await act(() => root.unmount()); await server.close(); dom.window.close(); restore.forEach(fn => fn()); });
  const current = () => document.querySelector('nav[aria-label="Settings sections"] [aria-current="location"]')?.getAttribute('href');
  async function click(id) { await act(() => document.querySelector(`nav a[href="#${id}"]`).click()); await flush(); }
  return { dom, positions, flush, current, click, writes, scrolls, releaseExit };
}
const response = value => ({ ok: true, status: 200, json: async () => structuredClone(value) });

test('sidebar navigation opens strategy panels, focuses destinations and preserves unsaved fields', async t => {
  const ui = await setup(t);
  assert.equal(document.querySelectorAll('nav[aria-label="Settings sections"] a').length, 9);
  assert.equal(ui.current(), '#connection');
  const input = document.querySelector('[aria-label="NIFTY Initial Arm Distance"]');
  await act(() => {
    Object.getOwnPropertyDescriptor(ui.dom.window.HTMLInputElement.prototype, 'value').set.call(input, '77');
    input.dispatchEvent(new ui.dom.window.Event('input', { bubbles: true }));
  });
  await ui.click('exit-fixed');
  assert.equal(document.getElementById('exit-fixed').open, true);
  assert.equal(document.activeElement.id, 'exit-fixed');
  assert.equal(ui.current(), '#exit-fixed');
  assert.equal(window.location.hash, '#exit-fixed');
  await ui.click('index-rules');
  assert.equal(document.querySelector('[aria-label="NIFTY Initial Arm Distance"]'), input);
  assert.equal(input.value, '77');
  assert.deepEqual(ui.writes, []);
});

test('manual scrolling highlights the current section and mobile selector navigates to it', async t => {
  const ui = await setup(t);
  for (const [id, i] of ids.map((id, i) => [id, i])) ui.positions.set(id, (i-2)*300+32);
  await act(() => window.dispatchEvent(new ui.dom.window.Event('scroll'))); await ui.flush();
  assert.equal(ui.current(), '#index-rules');
  const select = document.querySelector('.ms-settings-mobile-nav select');
  assert.equal(select.value, 'index-rules');
  await act(() => { select.value = 'exit-legacy'; select.dispatchEvent(new ui.dom.window.Event('change', { bubbles: true })); }); await ui.flush();
  assert.equal(document.getElementById('exit-legacy').open, true);
  assert.equal(ui.current(), '#exit-legacy');
});

test('deep links wait for strategy loading and history navigation follows the hash', async t => {
  const ui = await setup(t, { hash: '#exit-fixed', delayExit: true });
  assert.equal(ui.scrolls.length, 0);
  await act(async () => { ui.releaseExit(); await Promise.resolve(); }); await ui.flush();
  assert.equal(ui.current(), '#exit-fixed');
  assert.equal(document.getElementById('exit-fixed').open, true);
  await act(() => { window.history.replaceState({}, '', '#connection'); window.dispatchEvent(new ui.dom.window.PopStateEvent('popstate')); }); await ui.flush();
  assert.equal(ui.current(), '#connection');
  assert.equal(document.activeElement.id, 'connection');
});
