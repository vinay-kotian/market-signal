import test from 'node:test';
import assert from 'node:assert/strict';
import { applyBulkClassification } from './bulkClassification.js';

const payload = { trade_ids: [1, 2, 3], validity_status: 'INVALID_STRATEGY_BUG',
  reason: 'Rearm bug', exclude_from_strategy_metrics: true };

test('bulk classification confirms exact count and action before sending', async () => {
  let confirmed = false;
  const result = await applyBulkClassification(payload, message => {
    assert.equal(message, '3 trades will be marked INVALID_STRATEGY_BUG and excluded from strategy metrics.');
    confirmed = true; return true;
  }, async (url, options) => {
    assert.ok(confirmed);
    assert.equal(url, '/trades/classification/bulk');
    assert.equal(options.method, 'PATCH');
    assert.deepEqual(JSON.parse(options.body), payload);
    return [1, 2, 3];
  });
  assert.deepEqual(result, [1, 2, 3]);
});

test('cancel and empty selection never send a mutation', async () => {
  const send = () => assert.fail('Must not send');
  assert.equal(await applyBulkClassification(payload, () => false, send), null);
  await assert.rejects(applyBulkClassification({ ...payload, trade_ids: [] }, () => assert.fail('Must not confirm'), send), /Select at least one/);
});

test('restoration confirms inclusion and freezes unique targets', async () => {
  const input = { ...payload, trade_ids: [1, 1], validity_status: 'VALID', exclude_from_strategy_metrics: false };
  await applyBulkClassification(input, message => {
    assert.equal(message, '1 trade will be marked VALID and included in strategy metrics.');
    input.trade_ids.push(2); return true;
  }, async (_, options) => {
    assert.deepEqual(JSON.parse(options.body).trade_ids, [1]);
    return [1];
  });
});
