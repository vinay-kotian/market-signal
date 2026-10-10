import { useDateRange } from './useDateRange';
import React, { useEffect, useState } from 'react';
import { supportedIndices } from './indices';
import { request } from './api';
import { formatPrice, formatExitReason } from './format';
import DateRangeFilter from './DateRangeFilter';
import StrategyPerformanceComparison from './StrategyPerformanceComparison';
import BulkTradeClassification from './BulkTradeClassification';
import { validityStatuses } from './bulkClassification';
import { reportRangeError, loadReport, exportReport, saveCsv } from './reportFilters';

export default function PaperReportPage({ refreshKey }) {
  const [view, setView] = useState('STRATEGY');
  const [report, setReport] = useState(null);
  const [range, setRange] = useDateRange();
  const { fromDate, toDate } = range;
  const validation = reportRangeError(range);
  const [matchingIds, setMatchingIds] = useState([]);
  const [checked, setChecked] = useState([]);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [history, setHistory] = useState(null);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  const [strategyType, setStrategyType] = useState('');
  const [instrument, setInstrument] = useState('');
  const [draft, setDraft] = useState('');
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [retry, setRetry] = useState(0);
  const [exportKey, setExportKey] = useState('');
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState('');

  async function downloadCsv() {
    setExportBusy(true); setExportError('');
    try {
      saveCsv(await exportReport({ fromDate, toDate, mode: 'PAPER', view, status, instrument, strategyType }, { apiKey: exportKey }));
    } catch (error) { setExportError(`CSV export failed: ${error.message}`); }
    finally { setExportBusy(false); }
  }

  useEffect(() => {
    const controller = new AbortController();
    setHistory(null); setMatchingIds([]); setError(''); setReport(null);
    if (validation) return () => controller.abort();
    loadReport({ view, fromDate, toDate, status, instrument, strategyType, page }, { signal: controller.signal })
      .then(({ report, history, matchingIds }) => {
        if (controller.signal.aborted) return;
        const lastPage = Math.max(1, Math.ceil(history.total / history.page_size));
        if (page > lastPage) { setPage(lastPage); return; }
        setReport(report); setHistory(history); setMatchingIds(matchingIds);
      })
      .catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [page, status, instrument, strategyType, refreshKey, retry, view, fromDate, toDate, validation]);

  useEffect(() => {
    setDetail(null); setDetailError('');
    if (selected === null) return;
    const controller = new AbortController();
    request(`/trades/${selected}`, { signal: controller.signal }).then(setDetail)
      .catch(error => { if (!controller.signal.aborted) setDetailError(error.message); });
    return () => controller.abort();
  }, [selected, refreshKey, retry]);

  useEffect(() => { setChecked([]); }, [fromDate, toDate, view, status, instrument, strategyType, refreshKey, retry]);
  const allChecked = matchingIds.length > 0 && matchingIds.every(id => checked.includes(id));
  function changeRange(next, preset) {
    setRange(next, preset); setPage(1); setSelected(null); setChecked([]); setNotice('');
  }

  return <section aria-label="Paper trading report">
    <label className="ms-report-view">Report view <select disabled={bulkBusy} value={view} onChange={event => { setView(event.target.value); setPage(1); setSelected(null); setNotice(''); }}><option value="STRATEGY">STRATEGY · included trades</option><option value="RAW">RAW · all PAPER trades</option></select></label>
    <DateRangeFilter range={range} onApply={changeRange} disabled={bulkBusy} />
    <div className="ms-report-filters">
      <label>Export API key<input type="password" autoComplete="off" value={exportKey} onChange={event => setExportKey(event.target.value)} disabled={exportBusy} /></label>
      <button className="ms-button" onClick={downloadCsv} disabled={exportBusy || bulkBusy || Boolean(validation)}>{exportBusy ? 'Downloading…' : 'Download CSV'}</button>
    </div>
    {exportError && <p className="ms-error" role="alert">{exportError}</p>}
    <p className="ms-sub">Performance and trade history are calculated for the selected report view and date range, using trade entry time in Asia/Kolkata. Status and instrument filters apply to both sections.</p>
    <div className="ms-sectionhead">Performance Summary</div>
    {error && <p className="ms-error" role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
    {!report && !error && !validation && <p role="status">Loading report…</p>}
    {report && !validation && <>
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
    <StrategyPerformanceComparison fromDate={fromDate} toDate={toDate} view={view}
      status={status} instrument={instrument} refreshKey={`${refreshKey}-${retry}`} />
    <div className="ms-sectionhead">Trade history</div>
    {notice && <p role="status">{notice}</p>}
    <fieldset className="ms-trade-filters" disabled={bulkBusy || Boolean(validation)}>
    <form className="ms-report-filters" onSubmit={event => { event.preventDefault(); setChecked([]); setInstrument(draft.trim().toUpperCase()); setPage(1); setSelected(null); }}>
      <label>Exit strategy<select value={strategyType} onChange={event => { setStrategyType(event.target.value); setPage(1); setSelected(null); }}><option value="">All strategies</option><option value="LEGACY">Current / Legacy</option><option value="ATR">ATR</option></select></label>
      <label>Status<select value={status} onChange={event => { setStatus(event.target.value); setChecked([]); setPage(1); setSelected(null); }}><option value="">All statuses</option><option>OPEN</option><option>CLOSED</option></select></label>
      <label>Instrument<input list="report-instruments" value={draft} onChange={event => setDraft(event.target.value)} placeholder="All indices" /><datalist id="report-instruments">{supportedIndices.map(symbol => <option key={symbol} value={symbol} />)}</datalist></label>
      <button className="ms-button">Apply filter</button>
    </form>
    </fieldset>
    {!validation && <>
      <label className="ms-check"><input type="checkbox" checked={allChecked} disabled={bulkBusy || !matchingIds.length} onChange={event => setChecked(event.target.checked ? matchingIds : [])} />Select All · {matchingIds.length} matching trades across all pages</label>
      <BulkTradeClassification key={`${fromDate}-${toDate}-${view}`} tradeIds={checked} ready={Boolean(history)} busy={bulkBusy} onBusy={setBulkBusy} onSaved={count => { setChecked([]); setNotice(`Classification saved for ${count} trades.`); setRetry(value => value + 1); }} />
    </>}
    {!history && !error && !validation && <p role="status">Loading history…</p>}
    {history && !validation && <>
      <div className="ms-tablewrap" tabIndex={0} role="region" aria-label="Trade history table"><table className="ms-report-table">
        <thead><tr><th scope="col">Select</th><th scope="col">Trade / time (IST)</th><th scope="col">Instrument / level</th><th scope="col" className="ms-report-option">Option</th><th scope="col">Exit strategy</th>{['Qty', 'Entry', 'High', 'Exit', 'P&L'].map(label => <th scope="col" className="ms-num" key={label}>{label}</th>)}<th scope="col">Status</th><th scope="col" className="ms-report-exit">Exit reason</th></tr></thead>
        <tbody>{history.items.map(trade => <tr key={trade.trade_id} onClick={() => setSelected(trade.trade_id)} className="ms-history-row" aria-selected={selected === trade.trade_id}>
          <td onClick={event => event.stopPropagation()}><input className="ms-checkbox" type="checkbox" aria-label={`Select trade ${trade.trade_id}`} checked={checked.includes(trade.trade_id)} disabled={bulkBusy} onChange={event => setChecked(ids => event.target.checked ? [...ids, trade.trade_id] : ids.filter(id => id !== trade.trade_id))} /></td>
          <td className="ms-report-trade"><div><button className="ms-link" onClick={() => setSelected(trade.trade_id)} aria-label={`View trade ${trade.trade_id} timeline`}>#{trade.trade_id}</button><time dateTime={trade.entry_time}>{new Date(trade.entry_time).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' })}</time></div><small className="ms-time">{new Date(trade.entry_time).toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric' })}</small></td>
          <td>{trade.instrument}<small className="ms-time">Level {formatPrice(trade.trigger_level)}</small></td>
          <td className="ms-report-option">{trade.option_symbol}</td><td>{trade.strategy_type === 'ATR' ? 'ATR' : 'Current / Legacy'}</td>
          <td className="ms-num">{trade.quantity}</td>
          <td className="ms-num">{formatPrice(trade.entry_price)}</td>
          <td className="ms-num">{formatPrice(trade.highest_price)}</td>
          <td className="ms-num">{formatPrice(trade.exit_price)}</td>
          <td className={`ms-num ms-report-pnl ${trade.realised_pnl > 0 ? 'ms-up' : trade.realised_pnl < 0 ? 'ms-down' : ''}`}>{formatPrice(trade.realised_pnl)}{trade.realised_pnl_percentage == null ? '' : ` (${formatPrice(trade.realised_pnl_percentage)}%)`}</td>
          <td><span className={`ms-status ${trade.status === 'OPEN' ? 'triggered' : 'disabled'}`}>{trade.status}</span><small className="ms-time">{trade.validity_status} · {trade.exclude_from_strategy_metrics ? 'Excluded' : 'Included'}</small></td>
          <td className="ms-report-exit">{formatExitReason(trade.exit_reason)}</td>
        </tr>)}{history.items.length === 0 && <tr><td colSpan={12}>No matching trades.</td></tr>}</tbody>
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
        <ol>{detail.events.map(event => <li key={event.id}><strong>{event.event_type.replaceAll('_', ' ')}</strong><div>{new Date(event.timestamp).toLocaleString()} · Price {formatPrice(event.price)}</div>{event.current_stop != null && <div>Stop: {formatPrice(event.previous_stop)} → {formatPrice(event.current_stop)}</div>}{event.trailing_pct != null && <div>High: {formatPrice(event.highest_price)} · Trail: {event.trailing_pct}% · Step: {event.trailing_step}</div>}{event.reconstructed && <small>Reconstructed from a legacy trade record</small>}</li>)}</ol>
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
    <details><summary>Exit strategy snapshot at entry</summary><pre>{JSON.stringify({ strategy: trade.strategy_type, configuration: trade.strategy_config_snapshot, option_atr: trade.option_atr_at_entry, index_atr: trade.index_atr_at_entry, initial_risk: trade.initial_risk_amount }, null, 2)}</pre></details>
    <details><summary>Settings snapshot at entry</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(trade.settings_snapshot, null, 2)}</pre></details>
  </section>;
}
