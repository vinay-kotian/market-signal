import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { authenticationStatus, initialPage } from './connectionState.js';

test('callback path opens Connection; auth errors are not connected', () => {
  assert.equal(initialPage('/connection'), 'connection');
  assert.equal(initialPage('/'), 'dashboard');
  assert.equal(authenticationStatus(null), 'NOT_CONNECTED');
  assert.equal(authenticationStatus({ auth_status: 'AUTH_REQUIRED' }), 'AUTH_REQUIRED');
  assert.equal(authenticationStatus({ auth_status: 'CONNECTED' }, 'Request failed'), 'ERROR');
});

test('Connection renders one-click login and enables sync only after authentication', async () => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { default: ConnectionPage } = await server.ssrLoadModule('/src/ConnectionPage.jsx');
    const base = { market_data_mode: 'ZERODHA', login_url: 'http://127.0.0.1:8000/zerodha/login', connection_status: 'SYNC_REQUIRED' };
    const render = auth_status => renderToStaticMarkup(React.createElement(ConnectionPage, { connection: { ...base, auth_status }, onRefresh() {} }));
    const connected = render('CONNECTED');
    assert.match(connected, /Zerodha session connected/);
    assert.match(connected, /href="http:\/\/127.0.0.1:8000\/zerodha\/login"/);
    assert.match(connected, /<button class="ms-button">Sync instruments<\/button>/);
    assert.doesNotMatch(connected, /request_token|Request token|type="password"/);
    assert.match(render('AUTH_REQUIRED'), /<button[^>]*disabled=""[^>]*>Sync instruments/);
    assert.match(render('ERROR'), /Zerodha login could not be completed/);
  } finally { await server.close(); }
});


test('new live level automatically selects the first synced instrument', async () => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { default: LevelForm } = await server.ssrLoadModule('/src/LevelForm.jsx');
    const html = renderToStaticMarkup(React.createElement(LevelForm, {
      instrument: '', instrumentOptions: ['NIFTY', 'BANKNIFTY'], live: true,
    }));
    assert.match(html, /<option value="NIFTY" selected="">NIFTY/);
    assert.match(html, /<option value="BANKNIFTY">BANKNIFTY/);
  } finally { await server.close(); }
});

test('Settings renders separate per-index distance inputs', async () => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { default: SettingsPage } = await server.ssrLoadModule('/src/SettingsPage.jsx');
    const html = renderToStaticMarkup(React.createElement(SettingsPage, {
      indexes: [{ instrument: 'NIFTY', initial_arm_distance_points: 30, updated_at: 'a' },
        { instrument: 'BANKNIFTY', initial_arm_distance_points: 50, updated_at: 'b' }],
      onRefresh() {},
    }));
    assert.match(html, /NIFTY Initial Arm Distance/);
    assert.match(html, /BANKNIFTY Initial Arm Distance/);
    assert.match(html, /value="30"/);
    assert.match(html, /value="50"/);
    assert.equal(initialPage('/settings'), 'settings');
  } finally { await server.close(); }
});
