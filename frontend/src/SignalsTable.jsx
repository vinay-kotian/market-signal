import React from 'react';
import { formatPrice } from './format';

export default function SignalsTable({ signals, error, onRetry }) {
  return <section className="ms-signals" aria-label="Recent signals">
    <div className="ms-sectionhead"><span>Recent signals</span><span className="ms-sub">All instruments · newest first</span></div>
    {error && <div className="ms-error" role="alert">Signals unavailable. {error} <button className="ms-link" onClick={onRetry}>Retry</button></div>}
    {signals === null && !error ? <p className="ms-sub">Loading signals…</p> :
      <div className="ms-tablewrap"><table>
        <thead><tr><th>Instrument / time</th><th className="ms-num">Level</th><th>Direction</th><th className="ms-num">Distance · pts</th><th>Result</th></tr></thead>
        <tbody>{(signals ?? []).map(signal => <tr key={signal.id}>
          <td>{signal.instrument}<small className="ms-time">{new Date(signal.timestamp).toLocaleTimeString()}</small></td>
          <td className="ms-num">{formatPrice(signal.level)}</td>
          <td>{signal.direction?.replaceAll('_', ' ') ?? 'Unknown'}</td>
          <td className="ms-num">{formatPrice(signal.approach_distance)}</td>
          <td><span className={`ms-status ${signal.valid ? 'triggered' : 'rejected'}`}>{signal.valid ? 'VALID' : 'REJECTED'}</span>
            {signal.rejection_reason && <small className="ms-reason">{signal.rejection_reason === 'INSUFFICIENT_PRICE_HISTORY' ? 'Insufficient price history' : 'Minimum distance not met'}</small>}
          </td>
        </tr>)}{signals?.length === 0 && <tr><td colSpan="5" className="ms-empty">No signals yet. Send prices that touch or cross an enabled level.</td></tr>}</tbody>
      </table></div>}
  </section>;
}
