import test from 'node:test';
import assert from 'node:assert/strict';
import { formatPrice, levelStatus } from './format.js';

test('missing distances remain unknown, not zero', () => {
  assert.equal(formatPrice(null), '—');
  assert.equal(formatPrice(0), '0.00');
});

test('disabled and unavailable status take precedence over event history', () => {
  assert.equal(levelStatus({ enabled: false }, null), 'DISABLED');
  assert.equal(levelStatus({ enabled: true }, null), 'UNAVAILABLE');
});

test('old triggers do not apply to edited level configuration', () => {
  const level = { id: 1, enabled: true, instrument: 'NIFTY', price: 25000, updated_at: '2026-09-14T10:00:00Z' };
  const event = { level_id: 1, instrument: 'NIFTY', level_price: 25000, triggered_at: '2026-09-14T09:00:00Z' };
  assert.equal(levelStatus(level, [event]), 'WAITING');
  assert.equal(levelStatus(level, [{ ...event, triggered_at: '2026-09-14T11:00:00Z' }]), 'TRIGGERED');
});
