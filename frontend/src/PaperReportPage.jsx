import React, { useEffect, useState } from 'react';
import { supportedIndices } from './indices';
import { request } from './api';
import { formatPrice } from './format';
import BulkTradeClassification from './BulkTradeClassification';
import { validityStatuses } from './bulkClassification';

export default function PaperReportPage({ refreshKey }) {
  const [view, setView] = useState('STRATEGY');
  const [reports, setReports] = useState(null);
  const report = reports?.[view];
  const [date, setDate] = useState('');
  const [dayTrades, setDayTrades] = useState(null);
  const [checked, setChecked] = useState([]);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [notice, setNotice] = useState('');
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
    setHistory(null); setDayTrades(null); setError(''); setReports(null);
    const query = new URLSearchParams({ page, page_size: 20 });
    if (status) query.set('status', status);
    if (instrument) query.set('instrument', instrument);
    Promise.all([
      request('/reports/paper-trading?view=RAW', { signal: controller.signal }),
      request('/reports/paper-trading?view=STRATEGY', { signal: controller.signal }),
      request(date ? `/trades/by-date?date=${date}` : `/trades/history?${query}`, { signal: controller.signal }),
    ]).then(([raw, strategy, rows]) => {
      if (controller.signal.aborted) return;
      setReports({ RAW: raw, STRATEGY: strategy });
      if (date) {
        setDayTrades(rows);
        const filtered = rows.filter(trade => (!status || trade.status === status) && (!instrument || trade.instrument.toUpperCase() === instrument));
        setHistory({ items: filtered.slice((page - 1) * 20, page * 20), total: filtered.length, page_size: 20 });
      } else setHistory(rows);
    })
      .catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [page, status, instrument, refreshKey, retry, date]);

  useEffect(() => {
    setDetail(null); setDetailError('');
    if (selected === null) return;
    const controller = new AbortController();
    request(`/trades/${selected}`, { signal: controller.signal }).then(setDetail)
      .catch(error => { if (!controller.signal.aborted) setDetailError(error.message); });
    return () => controller.abort();
  }, [selected, refreshKey, retry]);

  useEffect(() => { setChecked([]); }, [date, status, instrument, refreshKey, retry]);
  const matching = (dayTrades ?? []).filter(trade => (!status || trade.status === status) && (!instrument || trade.instrument.toUpperCase() === instrument));
  const allChecked = matching.length > 0 && matching.every(trade => checked.includes(trade.trade_id));

  return <section aria-label="Paper trading report">
    <label className="ms-report-view">Report view <select value={view} onChange={event => setView(event.target.value)}><option value="STRATEGY">STRATEGY · included trades</option><option value="RAW">RAW · all PAPER trades</option></select></label>
    <p className="ms-sub">Performance uses closed trades in the selected view. History always preserves all PAPER trades. Summary metrics cover all dates; the filters below affect only the trade table and bulk selection.</p>
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
    {notice && <p role="status">{notice}</p>}
    <fieldset className="ms-trade-filters" disabled={bulkBusy}>
    <form className="ms-report-filters" onSubmit={event => { event.preventDefault(); setChecked([]); setInstrument(draft.trim().toUpperCase()); setPage(1); setSelected(null); }}>
      <label>Trading date (Asia/Kolkata)<input type="date" value={date} onChange={event => { setDate(event.target.value); setPage(1); setSelected(null); setChecked([]); setNotice(''); }} /></label>
      <label>Status<select value={status} onChange={event => { setStatus(event.target.value); setChecked([]); setPage(1); setSelected(null); }}><option value="">All statuses</option><option>OPEN</option><option>CLOSED</option></select></label>
      <label>Instrument<input list="report-instruments" value={draft} onChange={event => setDraft(event.target.value)} placeholder="All indices" /><datalist id="report-instruments">{supportedIndices.map(symbol => <option key={symbol} value={symbol} />)}</datalist></label>
      <button className="ms-button">Apply filter</button>
    </form>
    </fieldset>
    {!date && <p className="ms-sub">Choose a trading date to select and classify trades in bulk.</p>}
    {date && <>
      <label className="ms-check"><input type="checkbox" checked={allChecked} disabled={bulkBusy || !matching.length} onChange={event => setChecked(event.target.checked ? matching.map(trade => trade.trade_id) : [])} />Select All · {matching.length} matching trades across all pages</label>
      <BulkTradeClassification key={date} tradeIds={checked} ready={Boolean(history)} busy={bulkBusy} onBusy={setBulkBusy} onSaved={count => { setChecked([]); setNotice(`Classification saved for ${count} trades.`); setRetry(value => value + 1); }} />
    </>}
    {!history && !error && <p role="status">Loading history…</p>}
    {history && <>
      <div className="ms-tablewrap"><table>
        <thead><tr>{date && <th>Select</th>}{['Date / trade', 'Instrument', 'Trigger level', 'Option', 'Quantity', 'Entry', 'Exit', 'P&L', 'P&L %', 'Status', 'Exit reason'].map(label => <th key={label}>{label}</th>)}</tr></thead>
        <tbody>{history.items.map(trade => <tr key={trade.trade_id} onClick={() => setSelected(trade.trade_id)} className="ms-history-row" aria-selected={selected === trade.trade_id}>
          {date && <td onClick={event => event.stopPropagation()}><input className="ms-checkbox" type="checkbox" aria-label={`Select trade ${trade.trade_id}`} checked={checked.includes(trade.trade_id)} disabled={bulkBusy} onChange={event => setChecked(ids => event.target.checked ? [...ids, trade.trade_id] : ids.filter(id => id !== trade.trade_id))} /></td>}
          <td><button className="ms-link" onClick={() => setSelected(trade.trade_id)} aria-label={`View trade ${trade.trade_id} timeline`}>#{trade.trade_id}</button><small className="ms-time">{new Date(trade.entry_time).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}</small></td>
          <td>{trade.instrument}</td><td>{formatPrice(trade.trigger_level)}</td><td>{trade.option_symbol}</td><td>{trade.quantity}</td>
          <td>{formatPrice(trade.entry_price)}</td><td>{formatPrice(trade.exit_price)}</td><td>{formatPrice(trade.realised_pnl)}</td><td>{formatPrice(trade.realised_pnl_percentage)}</td><td>{trade.status}<small className="ms-time">{trade.validity_status} · {trade.exclude_from_strategy_metrics ? 'Excluded' : 'Included'}</small></td><td>{trade.exit_reason?.replaceAll('_', ' ') ?? '—'}</td>
        </tr>)}{history.items.length === 0 && <tr><td colSpan={date ? 12 : 11}>No matching trades.</td></tr>}</tbody>
      </table></div>
      <div className="ms-report-pagination"><button className="ms-button" disabled={bulkBusy || page === 1} onClick={() => { setPage(page - 1); setSelected(null); }}>Previous</button><span>Page {page} · {history.total} trades</span><button className="ms-button" disabled={bulkBusy || page * history.page_size >= history.total} onClick={() => { setPage(page + 1); setSelected(null); }}>Next</button></div>
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
        {validityStatuses.map(value => <option key={value}>{value}</option>)}
      </select></label>
      <label>Reason<textarea value={reason} maxLength={4000} disabled={saving} onChange={event => setReason(event.target.value)} /></label>
      <label><input type="checkbox" checked={excluded} disabled={saving} onChange={event => setExcluded(event.target.checked)} />Exclude from strategy metrics</label>
      <button className="ms-button" disabled={saving}>{saving ? 'Saving…' : 'Save classification'}</button>
    </form>
    {error && <p className="ms-error" role="alert">{error}</p>}
    <details><summary>Settings snapshot at entry</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(trade.settings_snapshot, null, 2)}</pre></details>
  </section>;
}
