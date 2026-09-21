export const validityStatuses = ['VALID', 'INVALID_STRATEGY_BUG', 'INVALID_DATA_ISSUE',
  'INVALID_EXECUTION_ISSUE', 'MANUAL_REVIEW'];

export async function applyBulkClassification(payload, confirm, send) {
  const snapshot = { ...payload, trade_ids: [...new Set(payload.trade_ids)] };
  if (!snapshot.trade_ids.length) throw new Error('Select at least one trade.');
  const count = snapshot.trade_ids.length;
  const message = `${count} ${count === 1 ? 'trade' : 'trades'} will be marked ${snapshot.validity_status} and ${snapshot.exclude_from_strategy_metrics ? 'excluded from' : 'included in'} strategy metrics.`;
  if (!confirm(message)) return null;
  return send('/trades/classification/bulk', { method: 'PATCH', body: JSON.stringify(snapshot) });
}
