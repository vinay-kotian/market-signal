import { useDateRange } from './useDateRange';
import React, { useEffect, useState } from 'react';
import DateRangeFilter from './DateRangeFilter';
import { rangeQuery } from './dateRange';
import { request } from './api';
import { formatPrice } from './format';

export default function OptionSelectionsTable({ selections: updates, refreshKey, tradeUpdates }) {
  const [range, setRange] = useDateRange(), [selections, setSelections] = useState(null);
  const [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const [page, setPage] = useState(1), [total, setTotal] = useState(0);
  const onRetry = () => setRetry(value => value + 1);
  useEffect(() => {
    const controller = new AbortController();
    setSelections(null); setError('');
    const query = rangeQuery(range); query.set('page', page); query.set('page_size', 20);
    request(`/option-selections/history?${query}`, { signal: controller.signal })
      .then(history => {
        if (controller.signal.aborted) return;
        const lastPage = Math.max(1, Math.ceil(history.total / history.page_size));
        if (page > lastPage) { setPage(lastPage); return; }
        setSelections(history.items); setTotal(history.total);
      })
      .catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [range.fromDate, range.toDate, updates, retry, page, refreshKey, tradeUpdates]);
  return <section className="ms-signals" aria-label="Recent option selections">
    <div className="ms-sectionhead"><span>Recent option selections</span><span className="ms-sub">Newest first · paper only</span></div>
    <div className="ms-history-filters"><DateRangeFilter range={range} onApply={(next, preset) => { setRange(next, preset); setPage(1); }} /></div>
    {error && <div className="ms-error" role="alert">Selections unavailable. {error} <button className="ms-link" onClick={onRetry}>Retry</button></div>}
    {selections === null && !error ? <p className="ms-sub">Loading option selections…</p> :
      <div className="ms-tablewrap"><table>
        <thead><tr><th>Instrument / signal</th><th>Contract / expiry</th><th className="ms-num">ATM → ITM</th><th>Entry premium</th><th>Selected (IST)</th><th>Result</th></tr></thead>
        <tbody>{(selections ?? []).map(selection => <tr key={selection.id}>
          <td>{selection.instrument}<small className="ms-time">Signal #{selection.signal_id} · {selection.option_type}</small></td>
          <td><span className="ms-contract">{selection.option_symbol ?? 'No matching contract'}</span><small className="ms-time">{selection.expiry ?? 'No expiry'} · Depth {selection.itm_depth}</small></td>
          <td className="ms-num">{formatPrice(selection.atm_strike)} → {formatPrice(selection.itm_strike)}</td>
          <td className="ms-num">{formatPrice(selection.entry_premium)}</td>
          <td>{new Date(selection.timestamp).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}</td>
          <td><span className={`ms-status ${selection.status === 'SELECTED' ? 'triggered' : 'rejected'}`}>{selection.status}</span>{selection.failure_reason && <small className="ms-reason">{selection.failure_reason.replaceAll('_', ' ').toLowerCase()}</small>}</td>
        </tr>)}{selections?.length === 0 && <tr><td colSpan="6" className="ms-empty">No option selections recorded in the selected date range.</td></tr>}</tbody>
      </table></div>}
    {selections && <div className="ms-report-pagination">
      <button type="button" className="ms-button" disabled={page === 1} onClick={() => setPage(value => value - 1)}>Previous</button>
      <span>Page {page} · {total} selections</span>
      <button type="button" className="ms-button" disabled={page * 20 >= total} onClick={() => setPage(value => value + 1)}>Next</button>
    </div>}
  </section>;
}
