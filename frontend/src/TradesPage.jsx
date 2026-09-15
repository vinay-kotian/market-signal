import React from 'react';
import { formatPrice } from './format';

export default function TradesPage({ trades, results, error, resultsError, onRetry }) {
  const failures = (results ?? []).filter(result => result.status === 'FAILED');
  return <section aria-label="Paper trades">
    <div className="ms-sectionhead"><span>Paper trades</span><span className="ms-sub">Open and closed · latest 100</span></div>
    {error && <div className="ms-error" role="alert">Trades unavailable. {error} <button className="ms-link" onClick={onRetry}>Retry</button></div>}
    {trades === null && !error ? <p>Loading trades…</p> : <div className="ms-tablewrap"><table>
      <thead><tr><th>Instrument / level</th><th>Option</th><th className="ms-num">Quantity</th><th className="ms-num">Entry / stop</th><th>Entry time</th><th>Status / mode</th><th className="ms-num">Exit / P&amp;L</th><th>Exit reason</th></tr></thead>
      <tbody>{(trades ?? []).map(trade => <tr key={trade.trade_id}>
        <td>{trade.instrument}<small className="ms-time">Level {formatPrice(trade.trigger_level)}</small></td>
        <td><span className="ms-contract">{trade.option_symbol}</span><small className="ms-time">Trade #{trade.trade_id} · Signal #{trade.signal_id}</small></td>
        <td className="ms-num">{trade.quantity}<small className="ms-time">{trade.number_of_lots} × {trade.lot_size}</small></td>
        <td className="ms-num">{formatPrice(trade.entry_price)}<small className="ms-time">High {formatPrice(trade.highest_price)}</small><small className="ms-time">Stop {formatPrice(trade.current_stop_loss)}</small><small className="ms-time">Initial {formatPrice(trade.initial_stop_loss)}</small></td>
        <td><small className="ms-time">{new Date(trade.entry_time).toLocaleString()}</small></td>
        <td><span className={`ms-status ${trade.status === 'CLOSED' ? 'disabled' : 'triggered'}`}>{trade.status}</span><small className="ms-time">{trade.trade_mode}</small><small className="ms-time">Breakeven: {trade.breakeven_activated ? 'Active' : trade.breakeven_protection_enabled ? 'Waiting' : 'Disabled'}</small></td>
        <td className="ms-num">{formatPrice(trade.exit_price)}<small className="ms-time">P&amp;L {formatPrice(trade.realised_pnl)}{trade.realised_pnl_percentage == null ? '' : ` (${formatPrice(trade.realised_pnl_percentage)}%)`}</small></td>
        <td title={trade.exit_reason ?? undefined}>{trade.exit_reason === 'MARKET_CLOSING_EXIT' ? 'Market closing exit' : trade.exit_reason?.replaceAll('_', ' ') ?? '—'}</td>
      </tr>)}{trades?.length === 0 && <tr><td colSpan="8" className="ms-empty">No paper trades yet. Entries require a successful option selection, a simulated quote, and an active trading window.</td></tr>}</tbody>
    </table></div>}
    {resultsError && <div className="ms-error" role="alert">Entry results unavailable. {resultsError} <button className="ms-link" onClick={onRetry}>Retry</button></div>}
    {failures.length > 0 && <div className="ms-signals"><div className="ms-sectionhead">Entry failures</div><ul>{failures.map(result => <li key={result.option_selection_id}>Selection #{result.option_selection_id}: {result.failure_reason.replaceAll('_', ' ').toLowerCase()}</li>)}</ul></div>}
  </section>;
}
