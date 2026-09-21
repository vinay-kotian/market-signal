import React, { useState } from 'react';
import { request } from './api';
import { applyBulkClassification, validityStatuses } from './bulkClassification';

export default function BulkTradeClassification({ tradeIds, ready, busy, onBusy, onSaved }) {
  const [status, setStatus] = useState('INVALID_STRATEGY_BUG');
  const [reason, setReason] = useState('');
  const [excluded, setExcluded] = useState(true);
  const [error, setError] = useState('');
  async function apply(event) {
    event.preventDefault(); setError(''); onBusy(true);
    try {
      const result = await applyBulkClassification({ trade_ids: tradeIds,
        validity_status: status, reason, exclude_from_strategy_metrics: excluded },
      message => window.confirm(message), request);
      if (result !== null) onSaved(result.length);
    } catch (error) { setError(error.message); }
    finally { onBusy(false); }
  }
  return <section className="ms-bulk-classification" aria-label="Bulk trade classification">
    <p>{tradeIds.length} trades selected</p>
    <form className="ms-report-filters" onSubmit={apply}>
      <label>Classification<select value={status} disabled={busy} onChange={event => setStatus(event.target.value)}>{validityStatuses.map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Reason<textarea value={reason} maxLength={4000} disabled={busy} onChange={event => setReason(event.target.value)} /></label>
      <label className="ms-check"><input type="checkbox" checked={excluded} disabled={busy} onChange={event => setExcluded(event.target.checked)} />Exclude from strategy metrics</label>
      <button className="ms-button" disabled={busy || !ready || !tradeIds.length}>{busy ? 'Applying…' : 'Apply Classification'}</button>
    </form>
    {error && <p className="ms-error" role="alert">{error}</p>}
  </section>;
}
