import { useDateRange } from './useDateRange';
import DateRangeFilter from './DateRangeFilter';
import { presetRange, rangeQuery } from './dateRange';
import React, { useEffect, useState } from 'react';
import { request } from './api';
import { formatPrice } from './format';

export default function SignalsTable({ signals, refreshKey }) {
  const [range, setRange] = useDateRange();
  const [instrument, setInstrument] = useState('');
  const [instrumentDraft, setInstrumentDraft] = useState('');
  const [result, setResult] = useState('');
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setRows(null); setError('');
    const query = rangeQuery(range);
    if (instrument) query.set('instrument', instrument);
    if (result) query.set('valid', result === 'VALID' ? 'true' : 'false');
    request(`/signals?${query}`, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setRows(data); })
      .catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [range.fromDate, range.toDate, instrument, result, signals, retry, refreshKey]);
  const onRetry = () => setRetry(value => value + 1);
  return <section className="ms-signals" aria-label="Recent signals">
    <div className="ms-sectionhead"><span>Recent signals</span><span className="ms-sub">Latest 100 matches · newest first</span></div>
    <form className="ms-signal-filters" onSubmit={event => { event.preventDefault(); setInstrument(instrumentDraft.trim().toUpperCase()); }}>
      <DateRangeFilter label="Date" range={range} onApply={setRange} />
      <label>Instrument<input value={instrumentDraft} onChange={event => setInstrumentDraft(event.target.value)} placeholder="All instruments" /></label>
      <label>Result<select value={result} onChange={event => setResult(event.target.value)}><option value="">All results</option><option value="VALID">Valid</option><option value="REJECTED">Rejected</option></select></label>
      <div className="ms-filter-actions"><button className="ms-button" type="submit">Apply</button>
      <button className="ms-link" type="button" onClick={() => { setRange(presetRange(), 'TODAY'); setInstrument(''); setInstrumentDraft(''); setResult(''); }}>Reset</button>
      </div>
    </form>
    <p className="ms-sub ms-filter-note">Asia/Kolkata{instrument ? ` · ${instrument}` : ''}</p>
    {error && <div className="ms-error" role="alert">Signals unavailable. {error} <button className="ms-link" onClick={onRetry}>Retry</button></div>}
    {rows === null && !error ? <p className="ms-sub">Loading signals…</p> :
      <div className="ms-tablewrap"><table>
        <thead><tr><th>Instrument / date & time</th><th className="ms-num">Level</th><th>Direction</th><th className="ms-num">Distance · pts</th><th>Result</th></tr></thead>
        <tbody>{(rows ?? []).map(signal => <tr key={signal.id}>
          <td>{signal.instrument}<small className="ms-time">{new Date(signal.timestamp).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}</small></td>
          <td className="ms-num">{formatPrice(signal.level)}</td>
          <td>{signal.direction?.replaceAll('_', ' ') ?? 'Unknown'}</td>
          <td className="ms-num">{formatPrice(signal.approach_distance)}</td>
          <td><span className={`ms-status ${signal.valid ? 'triggered' : 'rejected'}`}>{signal.valid ? 'VALID' : 'REJECTED'}</span>
            {signal.rejection_reason && <small className="ms-reason">{signal.rejection_reason === 'INSUFFICIENT_PRICE_HISTORY' ? 'Insufficient price history' : 'Minimum distance not met'}</small>}
          </td>
        </tr>)}{rows?.length === 0 && <tr><td colSpan="5" className="ms-empty">No signals match these filters.</td></tr>}</tbody>
      </table></div>}
  </section>;
}
