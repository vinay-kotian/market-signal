import test from 'node:test';
import assert from 'node:assert/strict';
import { parseLevels, parseHistoricalDataset, eventsForTrade } from './backtestInput.js';

test('multiple levels accept lines, spaces and commas; deduplicate', () => {
  assert.deepEqual(parseLevels('59800\n60000, 60250 60000'), [59800, 60000, 60250]);
  for (const text of ['', '0', '-3', 'NaN', '60000 nope', 'Infinity']) assert.throws(() => parseLevels(text));
});
test('upload requires option catalogue as well as recorded ticks', () => {
  assert.throws(() => parseHistoricalDataset('[]'));
  assert.throws(() => parseHistoricalDataset('{"ticks":[{}],"contracts":[]}'));
  assert.deepEqual(parseHistoricalDataset('{"ticks":[{}],"contracts":[{}]}'), { ticks: [{}], contracts: [{}] });
});
test('trade timeline includes its signals, level observations and session boundaries', () => {
  const events = [{ id: 1, event_type: 'MARKET_OPEN', payload: {} },
    { id: 2, trade_id: null, payload: { level: 60000 } },
    { id: 3, trade_id: 1, payload: {} }, { id: 4, trade_id: 2, payload: {} }];
  assert.deepEqual(eventsForTrade(events, { trade_id: 1, trigger_level: 60000 }).map(e => e.id), [1, 2, 3]);
  assert.equal(eventsForTrade(events).length, 4);
});
