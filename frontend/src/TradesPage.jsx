import { useDateRange } from './useDateRange';
import React, { useEffect, useState } from 'react';
import DateRangeFilter from './DateRangeFilter';
import { reportRangeError, loadTradeHistory } from './reportFilters';
import { formatPrice, formatExitReason } from './format';

export default function TradesPage({ refreshKey, tradeUpdates, results, resultsError, onRetry }) {
  const [range, setRange] = useDateRange();
  const [page, setPage] = useState(1);
  const [history, setHistory] = useState(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const validation = reportRangeError(range);
  const { fromDate, toDate } = range;
  useEffect(() => {
    const controller = new AbortController();
    setHistory(null); setError('');
    if (validation) return () => controller.abort();
    loadTradeHistory({ fromDate, toDate, page }, { signal: controller.signal })
      .then(rows => {
        if (controller.signal.aborted) return;
        const lastPage = Math.max(1, Math.ceil(rows.total / rows.page_size));
        if (page > lastPage) { setPage(lastPage); return; }
        setHistory(rows);
      })
      .catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [fromDate, toDate, page, validation, refreshKey, tradeUpdates, retry]);
  const failures = (results ?? []).filter(result => result.status === 'FAILED');
  return <section aria-label="Paper trades">
    <div className="ms-sectionhead"><span>Paper trades</span><span className="ms-sub">Open and closed · selected entry dates</span></div>
    <DateRangeFilter range={range} onApply={(next, preset) => { setRange(next, preset); setPage(1); }} />
    <p className="ms-sub">All PAPER trades entered within the selected dates in Asia/Kolkata, including trades excluded from strategy metrics.</p>
    {error && !validation && <div className="ms-error" role="alert">Trades unavailable. {error} <button className="ms-link" onClick={() => setRetry(value => value + 1)}>Retry</button></div>}
    {!history && !error && !validation && <p role="status">Loading trades…</p>}
    {history && !validation && <>
      <TradesTable trades={history.items} />
      <div className="ms-report-pagination">
        <button className="ms-button" disabled={page === 1} onClick={() => setPage(value => value - 1)}>Previous</button>
        <span>Page {page} · {history.total} trades</span>
        <button className="ms-button" disabled={page * history.page_size >= history.total} onClick={() => setPage(value => value + 1)}>Next</button>
      </div>
    </>}
    {resultsError && <div className="ms-error" role="alert">Entry results unavailable. {resultsError} <button className="ms-link" onClick={onRetry}>Retry</button></div>}
    {failures.length > 0 && <div className="ms-signals"><div className="ms-sectionhead">Entry failures</div><ul>{failures.map(result => <li key={result.option_selection_id}>Selection #{result.option_selection_id}: {result.failure_reason.replaceAll('_', ' ').toLowerCase()}</li>)}</ul></div>}
  </section>;
}

export function TradesTable({ trades }) {
  return <div className="ms-tablewrap"><table>
      <thead><tr><th>Instrument / level</th><th>Option</th><th className="ms-num">Quantity</th><th className="ms-num">Entry / stop</th><th>Entry time</th><th>Status / mode</th><th className="ms-num">Exit / P&amp;L</th><th>Exit reason</th></tr></thead>
      <tbody>{(trades ?? []).map(trade => <tr key={trade.trade_id}>
        <td>{trade.instrument}<small className="ms-time">Level {formatPrice(trade.trigger_level)}</small></td>
        <td><span className="ms-contract">{trade.option_symbol}</span><small className="ms-time">Trade #{trade.trade_id} · Signal #{trade.signal_id}</small></td>
        <td className="ms-num">{trade.quantity}<small className="ms-time">{trade.number_of_lots} × {trade.lot_size}</small></td>
        <td className="ms-num">{formatPrice(trade.entry_price)}<small className="ms-time">High {formatPrice(trade.highest_price)}</small><small className="ms-time">Stop {formatPrice(trade.current_stop_loss)}</small><small className="ms-time">Initial {formatPrice(trade.initial_stop_loss)}</small>{trade.settings_snapshot?.stop_strategy === 'PROGRESSIVE' && <small className="ms-time">{trade.profit_lock_activated ? `Profit locked · Trail ${trade.trailing_pct}% · Step ${trade.trailing_step}` : 'Awaiting profit trigger'}</small>}</td>
        <td><small className="ms-time">{new Date(trade.entry_time).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}</small></td>
        <td><span className={`ms-status ${trade.status === 'CLOSED' ? 'disabled' : 'triggered'}`}>{trade.status}</span><small className="ms-time">{trade.trade_mode}</small>{trade.settings_snapshot?.stop_strategy !== 'PROGRESSIVE' && <small className="ms-time">Breakeven: {trade.breakeven_activated ? 'Active' : trade.breakeven_protection_enabled ? 'Waiting' : 'Disabled'}</small>}</td>
        <td className="ms-num">{formatPrice(trade.exit_price)}<small className="ms-time">P&amp;L {formatPrice(trade.realised_pnl)}{trade.realised_pnl_percentage == null ? '' : ` (${formatPrice(trade.realised_pnl_percentage)}%)`}</small></td>
        <td title={trade.exit_reason ?? undefined}>{formatExitReason(trade.exit_reason)}</td>
      </tr>)}{trades?.length === 0 && <tr><td colSpan="8" className="ms-empty">No paper trades match the selected date range.</td></tr>}</tbody>
    </table></div>;
}
