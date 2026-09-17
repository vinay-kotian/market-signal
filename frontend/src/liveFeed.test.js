import test from 'node:test';
import assert from 'node:assert/strict';
import { createLiveFeed, marketSocketUrl, applyLiveEvent } from './liveFeed.js';

const flush = () => new Promise(resolve => setImmediate(resolve));
const event = (type, data) => ({ type, data, timestamp: '2026-09-17T04:30:00Z' });

function harness(loadSnapshot = async () => ({ trades: [], prices: {} })) {
  const sockets = [], timers = new Map(), statuses = [], events = [], snapshots = [];
  let next = 0;
  class Socket {
    constructor(url) { this.url = url; sockets.push(this); }
    close() { this.onclose?.(); }
    message(value) { this.onmessage({ data: JSON.stringify(value) }); }
  }
  const client = createLiveFeed({ url: 'wss://stockpi.vkotian.com/ws/market',
    WebSocketClass: Socket, loadSnapshot,
    onSnapshot: data => snapshots.push(data), onEvent: data => events.push(data),
    onStatus: status => statuses.push(status),
    schedule(fn, ms) { const id = ++next; timers.set(id, { fn, ms }); return id; },
    cancel(id) { timers.delete(id); },
  });
  function advance(ms) {
    const entry = [...timers].find(([, timer]) => timer.ms === ms);
    assert.ok(entry, `timer ${ms} exists`);
    timers.delete(entry[0]); entry[1].fn();
  }
  return { client, sockets, timers, statuses, events, snapshots, advance };
}

test('same-origin websocket URL uses wss in production and ws locally', () => {
  assert.equal(marketSocketUrl({ protocol: 'https:', host: 'stockpi.vkotian.com' }), 'wss://stockpi.vkotian.com/ws/market');
  assert.equal(marketSocketUrl({ protocol: 'http:', host: 'localhost:5173' }), 'ws://localhost:5173/ws/market');
});

test('one socket, backoff reconnect, one REST snapshot per open, stop cancels reconnect', async () => {
  const h = harness();
  h.client.start();
  h.sockets[0].onopen(); await flush();
  assert.equal(h.snapshots.length, 1);
  h.sockets[0].message(event('MARKET_PRICE_UPDATED', { instrument: 'NIFTY', price: 25000 }));
  assert.equal(h.snapshots.length, 1); // Deltas never fetch REST.
  h.sockets[0].close(); h.advance(1000);
  assert.equal(h.sockets.length, 2);
  h.sockets[1].close(); h.advance(2000);
  h.sockets[2].onopen(); await flush();
  assert.equal(h.snapshots.length, 2);
  h.sockets[2].message(event('HEARTBEAT', {}));
  assert.equal(h.events.length, 1);
  h.sockets[2].close(); h.advance(1000); // Healthy feed resets backoff.
  h.client.stop();
  assert.equal(h.timers.size, 0);
  assert.equal(h.statuses.at(-1), 'DISCONNECTED');
});

test('buffer socket deltas during REST snapshot and merge by identity', async () => {
  let resolve;
  const h = harness(() => new Promise(done => { resolve = done; }));
  h.client.start(); h.sockets[0].onopen();
  h.sockets[0].message(event('STOP_UPDATED', { trade_id: 1, current_stop_loss: 108 }));
  assert.equal(h.events.length, 0);
  resolve({ trades: [{ trade_id: 1, current_stop_loss: 90 }] }); await flush();
  let state = h.snapshots[0];
  for (const item of h.events) state = applyLiveEvent(state, item);
  assert.deepEqual(state.trades, [{ trade_id: 1, current_stop_loss: 108 }]);
  state = applyLiveEvent(state, event('STOP_UPDATED', state.trades[0]));
  assert.equal(state.trades.length, 1);
  h.client.stop();
});

test('stale snapshot from an earlier socket cannot overwrite recovery', async () => {
  const pending = [];
  const h = harness(() => new Promise(resolve => pending.push(resolve)));
  h.client.start(); h.sockets[0].onopen();
  h.sockets[0].close(); h.advance(1000); h.sockets[1].onopen();
  pending[1]({ version: 2 }); await flush();
  pending[0]({ version: 1 }); await flush();
  assert.deepEqual(h.snapshots, [{ version: 2 }]);
  h.client.stop();
});

test('silent connection watchdog reconnects, malformed messages ignored', () => {
  const h = harness(); h.client.start(); h.sockets[0].onopen();
  h.sockets[0].onmessage({ data: 'invalid json' });
  h.sockets[0].message({ unrelated: true });
  assert.equal(h.events.length, 0);
  h.advance(45000); assert.equal(h.statuses.at(-1), 'RECONNECTING');
  h.client.stop();
});

test('incremental events update dashboard, level states, trades and connection', () => {
  let state = { connection: { market_data_mode: 'ZERODHA', prices: { NIFTY: 24900 } }, levels: [{ id: 1, status: 'ACTIVE' }] };
  for (const e of [
    event('MARKET_PRICE_UPDATED', { instrument: 'NIFTY', price: 25000, change: 100, last_tick_at: 'now', ticks_received: 2 }),
    event('LEVEL_DISARMED', { level: { id: 1, status: 'DISARMED' } }),
    event('SIGNAL_CREATED', { id: 1, valid: true }),
    event('TRADE_OPENED', { trade_id: 1, status: 'OPEN' }),
    event('TRADE_CLOSED', { trade_id: 1, status: 'CLOSED', realised_pnl: 80 }),
    event('ZERODHA_CONNECTION_STATUS', { connection_status: 'DISCONNECTED' }),
  ]) state = applyLiveEvent(state, e);
  assert.equal(state.prices.NIFTY.change, 100);
  assert.equal(state.connection.prices.NIFTY, 25000);
  assert.equal(state.connection.connection_status, 'DISCONNECTED');
  assert.equal(state.levels[0].status, 'DISARMED');
  assert.equal(state.trades.length, 1);
  assert.equal(state.trades[0].status, 'CLOSED');
  assert.equal(state.signals[0].valid, true);
});
