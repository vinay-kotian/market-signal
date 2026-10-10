import test from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { JSDOM } from 'jsdom';
import { createServer } from 'vite';

async function setup(t, fetch) {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost' });
  const restore = [];
  for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    restore.push(() => previous ? Object.defineProperty(globalThis, name, previous) : delete globalThis[name]);
  }
  t.mock.method(globalThis, 'fetch', fetch);
  const { createRoot } = await import('react-dom/client');
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  const { default: Settings } = await server.ssrLoadModule('/src/TelegramSettings.jsx');
  const root = createRoot(document.getElementById('root'));
  t.after(async () => { await act(() => root.unmount()); await server.close(); dom.window.close(); restore.forEach(fn => fn()); });
  await act(() => root.render(React.createElement(Settings)));
  const toggle = () => document.querySelector('[role="switch"]');
  const click = async node => { await act(async () => node.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))); };
  return { toggle, click };
}

test('Telegram toggle loads saved state and persists on/off immediately', async t => {
  const calls = [];
  const { toggle, click } = await setup(t, async (path, options = {}) => {
    calls.push({ path, options });
    return { ok: true, json: async () => options.body ? JSON.parse(options.body) : { enabled: false } };
  });
  assert.equal(calls[0].path, '/api/settings/telegram');
  assert.equal(toggle().checked, false);
  await click(toggle());
  assert.equal(toggle().checked, true);
  assert.equal(calls[1].options.method, 'PUT');
  assert.deepEqual(JSON.parse(calls[1].options.body), { enabled: true });
  assert.match(document.body.textContent, /Telegram entry alerts enabled/);
  await click(toggle());
  assert.equal(toggle().checked, false);
  assert.deepEqual(JSON.parse(calls[2].options.body), { enabled: false });
});

test('save failure keeps prior setting and displays an error', async t => {
  const { toggle, click } = await setup(t, async (path, options = {}) => options.method === 'PUT'
    ? { ok: false, json: async () => ({ detail: 'Save unavailable' }) }
    : { ok: true, json: async () => ({ enabled: true }) });
  await click(toggle());
  assert.equal(toggle().checked, true);
  assert.equal(toggle().disabled, false);
  assert.match(document.querySelector('[role="alert"]').textContent, /Save unavailable/);
});

test('load failure shows retry and recovers saved setting', async t => {
  let requests = 0;
  const { toggle, click } = await setup(t, async () => ++requests === 1
    ? { ok: false, json: async () => ({ detail: 'Load unavailable' }) }
    : { ok: true, json: async () => ({ enabled: true }) });
  assert.equal(toggle(), null);
  assert.match(document.querySelector('[role="alert"]').textContent, /Load unavailable/);
  await click(document.querySelector('button'));
  assert.equal(toggle().checked, true);
});
