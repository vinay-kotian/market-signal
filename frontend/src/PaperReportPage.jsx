import React, { useEffect, useState } from 'react';
import { request } from './api';
import { formatPrice } from './format';

export default function PaperReportPage({ refreshKey }) {
  const [view, setView] = useState('STRATEGY');
  const [report, setReport] = useState(null);
  const [history, setHistory] = useState(null);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  const [instrument, setInstrument] = useState('');
  const [draft, setDraft] = useState('');
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setHistory(null); setError(''); setReport(null);
    const query = new URLSearchParams({ page, page_size: 20 });
    if (status) query.set('status', status);
    if (instrument) query.set('instrument', instrument);
    Promise.all([
      request(`/reports/paper-trading?view=${view}`, { signal: controller.signal }),
      request(`/trades/history?${query}`, { signal: controller.signal }),
    ]).then(([summary, rows]) => { setReport(summary); setHistory(rows); })
      .catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [page, status, instrument, refreshKey, retry, view]);

  useEffect(() => {
    setDetail(null); setDetailError('');
    if (selected === null) return;
    const controller = new AbortController();
    request(`/trades/${selected}`, { signal: controller.signal }).then(setDetail)
      .catch(error => { if (!controller.signal.aborted) setDetailError(error.message); });
    return () => controller.abort();
  }, [selected, refreshKey, retry]);

  return <section aria-label="Paper trading report">
    <label>Report view <select value={view} onChange={event => setView(event.target.value)}><option value="STRATEGY">STRATEGY · included trades</option><option value="RAW">RAW · all PAPER trades</option></select></label>
    <p className="ms-sub">Performance uses closed trades in the selected view. History always preserves all PAPER trades; history filters do not change the summary.</p>
    {error && <p className="ms-error" role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
    {!report && !error && <p role="status">Loading report…</p>}
    {report && <>
      <dl className="ms-report-summary">{[
        ['Total Trades', report.total_trades], ['Win Rate', `${formatPrice(report.win_rate)}%`],
        ['Net P&L', formatPrice(report.net_pnl)], ['Profit Factor', report.profit_factor === null ? 'N/A' : formatPrice(report.profit_factor)],
      ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <dl className="ms-report-metrics">{[
        ['Recorded trades', report.recorded_trades], ['Included trades', report.included_trades], ['Excluded trades', report.excluded_trades],
        ['Open', report.open_trades], ['Closed', report.closed_trades],
        ['Winning', report.winning_trades], ['Losing', report.losing_trades], ['Breakeven', report.breakeven_trades],
        ['Gross profit', formatPrice(report.gross_profit)], ['Gross loss', formatPrice(report.gross_loss)],
        ['Average profit', formatPrice(report.average_profit)], ['Average loss', formatPrice(report.average_loss)],
        ['Maximum profit', formatPrice(report.maximum_profit)], ['Maximum loss', formatPrice(report.maximum_loss)],
      ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <p className="ms-sub">Loss metrics are positive amounts. Win rate excludes breakeven trades. Profit factor is N/A when there are no losses.</p>
    </>}
    <div className="ms-sectionhead">Trade history</div>
    <form className="ms-report-filters" onSubmit={event => { event.preventDefault(); setInstrument(draft.trim().toUpperCase()); setPage(1); setSelected(null); }}>
      <label>Status<select value={status} onChange={event => { setStatus(event.target.value); setPage(1); setSelected(null); }}><option value="">All statuses</option><option>OPEN</option><option>CLOSED</option></select></label>
      <label>Instrument<input value={draft} onChange={event => setDraft(event.target.value)} placeholder="e.g. NIFTY" /></label>
      <button className="ms-button">Apply filter</button>
    </form>
    {!history && !error && <p role="status">Loading history…</p>}
    {history && <>
      <div className="ms-tablewrap"><table>
        <thead><tr>{['Date / trade', 'Instrument', 'Trigger level', 'Option', 'Quantity', 'Entry', 'Exit', 'P&L', 'P&L %', 'Status', 'Exit reason'].map(label => <th key={label}>{label}</th>)}</tr></thead>
        <tbody>{history.items.map(trade => <tr key={trade.trade_id} onClick={() => setSelected(trade.trade_id)} className="ms-history-row" aria-selected={selected === trade.trade_id}>
          <td><button className="ms-link" onClick={() => setSelected(trade.trade_id)} aria-label={`View trade ${trade.trade_id} timeline`}>#{trade.trade_id}</button><small className="ms-time">{new Date(trade.entry_time).toLocaleString()}</small></td>
          <td>{trade.instrument}</td><td>{formatPrice(trade.trigger_level)}</td><td>{trade.option_symbol}</td><td>{trade.quantity}</td>
          <td>{formatPrice(trade.entry_price)}</td><td>{formatPrice(trade.exit_price)}</td><td>{formatPrice(trade.realised_pnl)}</td><td>{formatPrice(trade.realised_pnl_percentage)}</td><td>{trade.status}<small className="ms-time">{trade.validity_status} · {trade.exclude_from_strategy_metrics ? 'Excluded' : 'Included'}</small></td><td>{trade.exit_reason?.replaceAll('_', ' ') ?? '—'}</td>
        </tr>)}{history.items.length === 0 && <tr><td colSpan="11">No matching trades.</td></tr>}</tbody>
      </table></div>
      <div className="ms-report-pagination"><button className="ms-button" disabled={page === 1} onClick={() => { setPage(page - 1); setSelected(null); }}>Previous</button><span>Page {page} · {history.total} trades</span><button className="ms-button" disabled={page * history.page_size >= history.total} onClick={() => { setPage(page + 1); setSelected(null); }}>Next</button></div>
    </>}
    {selected !== null && <section className="ms-report-timeline" aria-label={`Trade ${selected} timeline`}>
      <div className="ms-sectionhead"><span>Trade #{selected} · event timeline</span><button className="ms-link" onClick={() => setSelected(null)}>Close timeline</button></div>
      {detailError && <p className="ms-error" role="alert">{detailError} <button onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
      {!detail && !detailError && <p role="status">Loading timeline…</p>}
      {detail && <>
        <p>{detail.trade.option_symbol} · {detail.trade.status} · Signal #{detail.trade.signal_id} · Selection #{detail.trade.option_selection_id}</p>
        <TradeClassification key={`${detail.trade.trade_id}-${retry}`} trade={detail.trade} onSaved={() => setRetry(value => value + 1)} />
        <p className="ms-sub">Persisted trade events, in time order. Earlier level/signal/selection events are not recorded in this trade timeline.</p>
        <ol>{detail.events.map(event => <li key={event.id}><strong>{event.event_type.replaceAll('_', ' ')}</strong><div>{new Date(event.timestamp).toLocaleString()} · Price {formatPrice(event.price)}</div>{event.current_stop != null && <div>Stop: {formatPrice(event.previous_stop)} → {formatPrice(event.current_stop)}</div>}{event.reconstructed && <small>Reconstructed from a legacy trade record</small>}</li>)}</ol>
        {detail.events.length === 0 && <p>No persisted events.</p>}
      </>}
    </section>}
  </section>;
}


function TradeClassification({ trade, onSaved }) {
  const [status, setStatus] = useState(trade.validity_status);
  const [reason, setReason] = useState(trade.validity_reason ?? '');
  const [excluded, setExcluded] = useState(trade.exclude_from_strategy_metrics);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  async function save(event) {
    event.preventDefault(); setSaving(true); setError('');
    try {
      await request(`/trades/${trade.trade_id}/classification`, {
        method: 'PATCH', body: JSON.stringify({ validity_status: status, reason, exclude_from_strategy_metrics: excluded }),
      });
      onSaved();
    } catch (error) { setError(error.message); }
    finally { setSaving(false); }
  }
  return <section aria-label="Trade classification">
    <p>Strategy version: <strong>{trade.strategy_version}</strong> · {trade.validity_status} · {trade.exclude_from_strategy_metrics ? 'Excluded from strategy metrics' : 'Included in strategy metrics'}</p>
    <p>Reason: {trade.validity_reason || 'None'}</p>
    <form className="ms-report-filters" onSubmit={save}>
      <label>Validity status<select value={status} disabled={saving} onChange={event => setStatus(event.target.value)}>
        {['VALID', 'INVALID_STRATEGY_BUG', 'INVALID_DATA_ISSUE', 'INVALID_EXECUTION_ISSUE', 'MANUAL_REVIEW'].map(value => <option key={value}>{value}</option>)}
      </select></label>
      <label>Reason<textarea value={reason} maxLength={4000} disabled={saving} onChange={event => setReason(event.target.value)} /></label>
      <label><input type="checkbox" checked={excluded} disabled={saving} onChange={event => setExcluded(event.target.checked)} />Exclude from strategy metrics</label>
      <button className="ms-button" disabled={saving}>{saving ? 'Saving…' : 'Save classification'}</button>
    </form>
    {error && <p className="ms-error" role="alert">{error}</p>}
    <details><summary>Settings snapshot at entry</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(trade.settings_snapshot, null, 2)}</pre></details>
  </section>;
}
