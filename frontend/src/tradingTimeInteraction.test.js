import test from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { createServer } from 'vite';
import { JSDOM } from 'jsdom';

const defaults = { market_open_time: '09:15:00', market_close_time: '15:30:00',
  entry_block_after_open_minutes: 10, entry_block_before_close_minutes: 10,
  mandatory_exit_before_close_minutes: 3 };

async function setup(t, fetch) {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost' });
  const restore = [];
  for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document,
    HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })) {
    const prior = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    restore.push(() => prior ? Object.defineProperty(globalThis, name, prior) : delete globalThis[name]);
  }
  t.mock.method(globalThis, 'fetch', fetch);
  // Load the DOM renderer after a document exists so React listens for input events.
  const { createRoot } = await import('react-dom/client');
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  const { default: Settings } = await server.ssrLoadModule('/src/TradingTimeSettings.jsx');
  const root = createRoot(document.getElementById('root'));
  t.after(async () => { await act(() => root.unmount()); await server.close(); dom.window.close(); restore.forEach(fn => fn()); });
  const button = () => document.querySelector('button[type="submit"]');
  const edit = async (label, value) => {
    const input = [...document.querySelectorAll('label')].find(node => node.textContent === label)?.querySelector('input');
    assert.ok(input);
    await act(() => {
      Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value').set.call(input, value);
      input.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
      input.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
    });
  };
  await act(() => root.render(React.createElement(Settings)));
  return { edit, button, dom };
}

test('time settings load persisted values, preview edits immediately and save only valid configuration', async t => {
  const calls = [];
  const { edit, button, dom } = await setup(t, async (path, options = {}) => {
    calls.push({ path, options });
    return { ok: true, json: async () => ({ configuration: options.body ? JSON.parse(options.body) : defaults }) };
  });
  assert.equal(calls.length, 1);
  assert.match(document.body.textContent, /09:25 – 15:20/);
  assert.match(document.body.textContent, /15:27/);
  await edit('Market Close Time', '16:00');
  assert.match(document.body.textContent, /09:25 – 15:50/);
  assert.match(document.body.textContent, /15:57/);
  assert.equal(calls.length, 1); // Preview needs no API roundtrip.
  await edit('Entry Block After Open — minutes', '-1');
  assert.ok(button().disabled);
  assert.match(document.querySelector('[role="alert"]').textContent, /non-negative/);
  await act(() => document.querySelector('form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })));
  assert.equal(calls.length, 1);
  await edit('Entry Block After Open — minutes', '20');
  assert.match(document.body.textContent, /09:35 – 15:50/);
  await act(() => button().dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
  assert.equal(calls.length, 2);
  assert.equal(calls[1].options.method, 'PUT');
  assert.equal(JSON.parse(calls[1].options.body).entry_block_after_open_minutes, 20);
  assert.match(document.body.textContent, /Saved\. PAPER/);
});

test('time settings show server validation errors and retain unsaved edits', async t => {
  const { edit, button, dom } = await setup(t, async (path, options = {}) => options.method === 'PUT'
    ? { ok: false, json: async () => ({ detail: 'Validation failed on server' }) }
    : { ok: true, json: async () => ({ configuration: defaults }) });
  await edit('Market Close Time', '16:00');
  await act(() => button().dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
  assert.match(document.querySelector('[role="alert"]').textContent, /Validation failed on server/);
  assert.match(document.body.textContent, /15:57/);
  assert.ok(!button().disabled);
});
