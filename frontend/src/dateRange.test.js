import test from 'node:test';
import assert from 'node:assert/strict';
import { addDays, monthDays, presetRange, rangeError, rangeQuery, selectDay, shiftMonth } from './dateRange.js';

test('presets use IST calendar days across midnight, month and year rollover', () => {
  assert.deepEqual(presetRange('TODAY', new Date('2026-10-09T18:30:00Z')), { fromDate: '2026-10-10', toDate: '2026-10-10' });
  assert.deepEqual(presetRange('YESTERDAY', new Date('2026-10-09T18:29:59.999Z')), { fromDate: '2026-10-08', toDate: '2026-10-08' });
  assert.equal(presetRange('YESTERDAY', new Date('2026-12-31T18:30:00Z')).fromDate, '2026-12-31');
  assert.equal(addDays('2024-03-01', -1), '2024-02-29');
});
test('two clicks select inclusive ranges, including same-day and reversed clicks', () => {
  const first = selectDay({}, '2026-10-05', false);
  assert.deepEqual(first, { fromDate: '2026-10-05', toDate: '' });
  assert.deepEqual(selectDay(first, '2026-10-05', true), { fromDate: '2026-10-05', toDate: '2026-10-05' });
  assert.deepEqual(selectDay(first, '2026-10-09', true), { fromDate: '2026-10-05', toDate: '2026-10-09' });
  assert.deepEqual(selectDay(first, '2026-10-02', true), { fromDate: '2026-10-02', toDate: '2026-10-05' });
  assert.deepEqual(selectDay(first, '2026-10-02', false, true), { fromDate: '2026-10-02', toDate: '2026-10-02' });
});
test('empty, malformed, impossible, reversed and future ranges cannot create API queries', () => {
  for (const range of [{ fromDate: '', toDate: '' }, { fromDate: 'bad', toDate: 'bad' },
    { fromDate: '2026-02-30', toDate: '2026-03-01' }, { fromDate: '2026-10-09', toDate: '2026-10-08' },
    { fromDate: '9999-01-01', toDate: '9999-01-01' }]) {
    assert.ok(rangeError(range, '2026-10-10'));
    assert.throws(() => rangeQuery(range));
  }
});
test('calendar month grids cover leap days and navigation across years', () => {
  assert.equal(monthDays('2024-02').filter(Boolean).length, 29);
  assert.equal(monthDays('2026-10')[0], null);
  assert.equal(shiftMonth('2026-12', 1), '2027-01');
  assert.equal(shiftMonth('2026-01', -1), '2025-12');
});
