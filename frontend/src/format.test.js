import test from 'node:test';
import assert from 'node:assert/strict';
import { formatPrice, formatExitReason, levelStatus } from './format.js';

test('exit reasons have readable labels without reclassifying historical values', () => {
  assert.equal(formatExitReason('STOP_LOSS'), 'Stop Loss');
  assert.equal(formatExitReason('TRAILING_STOP_LOSS'), 'Trailing Stop Loss');
  assert.equal(formatExitReason('MARKET_CLOSING_EXIT'), 'Market Closing Exit');
  assert.equal(formatExitReason('MANUAL_SQUARE_OFF'), 'Manual Square Off');
  assert.equal(formatExitReason(null), '—');
  assert.equal(formatExitReason('LEGACY_REASON'), 'LEGACY REASON');
});

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

test('trading dates roll over at Kolkata midnight regardless of browser timezone', async () => {
  const { tradingDate, levelsForDate } = await import('./format.js');
  assert.equal(tradingDate(new Date('2026-09-14T18:29:59Z')), '2026-09-14');
  assert.equal(tradingDate(new Date('2026-09-14T18:30:00Z')), '2026-09-15');
  const rows = [{ id: 1, level_date: '2026-09-14', status: 'EXPIRED' },
    { id: 2, level_date: '2026-09-15', status: 'ACTIVE' },
    { id: 3, level_date: '2026-09-16', status: 'ACTIVE' }];
  assert.deepEqual(levelsForDate(rows, '2026-09-15').map(row => row.id), [2]);
  assert.deepEqual(levelsForDate(rows, '2026-09-15', 'ALL'), rows);
  assert.equal(levelStatus({ enabled: false, status: 'EXPIRED' }, null), 'EXPIRED');
});
