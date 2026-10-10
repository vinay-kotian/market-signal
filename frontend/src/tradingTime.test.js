import test from 'node:test';
import assert from 'node:assert/strict';
import { tradingTimePreview } from './tradingTime.js';

export const configuration = { market_open_time: '09:15', market_close_time: '15:30',
  entry_block_after_open_minutes: 10, entry_block_before_close_minutes: 10,
  mandatory_exit_before_close_minutes: 3 };

test('default trading windows match IST entry and exit configuration', () => {
  assert.deepEqual(tradingTimePreview(configuration), { error: '', entryFrom: '09:25', entryUntil: '15:20', exitStarts: '15:27' });
});
test('preview updates from session times and buffers, including seconds', () => {
  assert.deepEqual(tradingTimePreview({ ...configuration, market_open_time: '10:00', market_close_time: '14:00',
    entry_block_after_open_minutes: 30, entry_block_before_close_minutes: 20, mandatory_exit_before_close_minutes: 5 }),
  { error: '', entryFrom: '10:30', entryUntil: '13:40', exitStarts: '13:55' });
  assert.equal(tradingTimePreview({ ...configuration, entry_block_after_open_minutes: 10.5 }).entryFrom, '09:25:30');
});
test('invalid combinations produce clear errors instead of misleading windows', () => {
  for (const changes of [{ market_open_time: '' }, { market_open_time: '25:00' }, { market_close_time: '09:15' },
    { entry_block_after_open_minutes: -1 }, { entry_block_before_close_minutes: '' },
    { entry_block_after_open_minutes: 365 }, { mandatory_exit_before_close_minutes: 0 },
    { mandatory_exit_before_close_minutes: 375 }, { mandatory_exit_before_close_minutes: 11 }]) {
    const result = tradingTimePreview({ ...configuration, ...changes });
    assert.ok(result.error);
    assert.equal(result.entryFrom, undefined);
  }
});
