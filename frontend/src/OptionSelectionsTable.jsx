import React from 'react';
import { formatPrice } from './format';

export default function OptionSelectionsTable({ selections, error, onRetry }) {
  return <section className="ms-signals" aria-label="Recent option selections">
    <div className="ms-sectionhead"><span>Recent option selections</span><span className="ms-sub">Simulated contracts · paper only</span></div>
    {error && <div className="ms-error" role="alert">Selections unavailable. {error} <button className="ms-link" onClick={onRetry}>Retry</button></div>}
    {selections === null && !error ? <p className="ms-sub">Loading option selections…</p> :
      <div className="ms-tablewrap"><table>
        <thead><tr><th>Instrument / signal</th><th>Contract / expiry</th><th className="ms-num">ATM → ITM</th><th>Result</th></tr></thead>
        <tbody>{(selections ?? []).map(selection => <tr key={selection.id}>
          <td>{selection.instrument}<small className="ms-time">Signal #{selection.signal_id} · {selection.option_type}</small></td>
          <td><span className="ms-contract">{selection.option_symbol ?? 'No matching contract'}</span><small className="ms-time">{selection.expiry ?? 'No expiry'} · Depth {selection.itm_depth}</small></td>
          <td className="ms-num">{formatPrice(selection.atm_strike)} → {formatPrice(selection.itm_strike)}</td>
          <td><span className={`ms-status ${selection.status === 'SELECTED' ? 'triggered' : 'rejected'}`}>{selection.status}</span>{selection.failure_reason && <small className="ms-reason">{selection.failure_reason.replaceAll('_', ' ').toLowerCase()}</small>}</td>
        </tr>)}{selections?.length === 0 && <tr><td colSpan="4" className="ms-empty">No option selections yet. A valid signal starts contract selection.</td></tr>}</tbody>
      </table></div>}
  </section>;
}
