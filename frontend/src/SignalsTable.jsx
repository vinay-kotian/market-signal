import React, { useEffect, useState } from 'react';
import { request } from './api';
import { formatPrice, tradingDate } from './format';

export default function SignalsTable({ signals, today = tradingDate() }) {
  const [dateMode, setDateMode] = useState('TODAY');
  const [customDate, setCustomDate] = useState(today);
  const [instrument, setInstrument] = useState('');
  const [instrumentDraft, setInstrumentDraft] = useState('');
  const [result, setResult] = useState('');
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const date = dateMode === 'TODAY' ? today : dateMode === 'CUSTOM' ? customDate : '';
  useEffect(() => {
    const controller = new AbortController();
    setRows(null); setError('');
    const query = new URLSearchParams();
    if (date) query.set('signal_date', date);
    if (instrument) query.set('instrument', instrument);
    if (result) query.set('valid', result === 'VALID' ? 'true' : 'false');
    request(`/signals?${query}`, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setRows(data); })
      .catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [date, instrument, result, signals, retry]);
  const onRetry = () => setRetry(value => value + 1);
  return <section className="ms-signals" aria-label="Recent signals">
    <div className="ms-sectionhead"><span>Recent signals</span><span className="ms-sub">Latest 100 matches · newest first</span></div>
    <form className="ms-signal-filters" onSubmit={event => { event.preventDefault(); setInstrument(instrumentDraft.trim().toUpperCase()); }}>
      <label>Date<select value={dateMode} onChange={event => setDateMode(event.target.value)}><option value="TODAY">Today</option><option value="ALL">All dates</option><option value="CUSTOM">Choose date</option></select></label>
      {dateMode === 'CUSTOM' && <label>Trading date<input type="date" required value={customDate} onChange={event => { if (event.target.value) setCustomDate(event.target.value); }} /></label>}
      <label>Instrument<input value={instrumentDraft} onChange={event => setInstrumentDraft(event.target.value)} placeholder="All instruments" /></label>
      <label>Result<select value={result} onChange={event => setResult(event.target.value)}><option value="">All results</option><option value="VALID">Valid</option><option value="REJECTED">Rejected</option></select></label>
      <button className="ms-button" type="submit">Apply</button>
      <button className="ms-link" type="button" onClick={() => { setDateMode('TODAY'); setInstrument(''); setInstrumentDraft(''); setResult(''); }}>Reset</button>
      <span className="ms-sub">Asia/Kolkata{instrument ? ` · ${instrument}` : ''}</span>
    </form>
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
