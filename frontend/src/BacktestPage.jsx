import React, { useEffect, useState } from 'react';
import { request } from './api';
import { formatPrice, formatExitReason } from './format';
import { parseLevels, parseHistoricalDataset, eventsForTrade } from './backtestInput';
import { supportedIndices } from './indices';

const localTime = value => value ? new Date(value).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false }) : '—';

export default function BacktestPage() {
  const [instrument, setInstrument] = useState('NIFTY');
  const [date, setDate] = useState('2026-09-14');
  const [levels, setLevels] = useState('25000');
  const [source, setSource] = useState('archive');
  const [dataset, setDataset] = useState(null);
  const [fileName, setFileName] = useState('');
  const [settings, setSettings] = useState(null);
  const [runs, setRuns] = useState([]);
  const [result, setResult] = useState(null);
  const [selectedTrade, setSelectedTrade] = useState('');
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    Promise.all([request('/backtests/settings'), request('/backtests')]).then(([snapshot, history]) => {
      if (active) { setSettings(snapshot); setRuns(history); }
    }).catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, []);

  async function run(event) {
    event.preventDefault(); setError('');
    let prices;
    try { prices = parseLevels(levels); } catch (error) { setError(error.message); return; }
    if (source === 'file' && !dataset) { setError('Choose a historical JSON dataset first.'); return; }
    setBusy(true); setResult(null); setSelectedTrade('');
    try {
      const response = await request('/backtests/run', { method: 'POST', body: JSON.stringify({
        trading_date: date, instrument, levels: prices,
        ...(source === 'demo' ? { fixture: 'nifty-demo' } : {}),
        ...(source === 'file' ? { dataset: dataset.ticks, contracts: dataset.contracts } : {}),
      }) });
      setResult(response);
      setSettings(response.settings_snapshot);
      setRuns(await request('/backtests'));
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  const currentSettings = settings ? Object.entries(settings).filter(([key]) => !['contracts', 'index_settings', 'trade_mode', 'timezone'].includes(key)) : [];

  return <section aria-label="Backtesting">
    <p className="ms-sub">Replay one historical trading day with the current strategy. Times use Asia/Kolkata. Each run stores its settings and remains separate from PAPER reports.</p>
    <form onSubmit={run}>
      <fieldset disabled={busy || reading} className="ms-backtest-fields">
        <div className="ms-report-filters">
          <label>Trading date<input required type="date" value={date} onChange={event => setDate(event.target.value)} /></label>
          <label>Instrument<select value={instrument} onChange={event => {
            setInstrument(event.target.value); if (event.target.value !== 'NIFTY' && source === 'demo') setSource('archive');
          }}>{supportedIndices.map(symbol => <option key={symbol}>{symbol}</option>)}</select></label>
          <label>Price data<select value={source} onChange={event => {
            setSource(event.target.value); if (event.target.value === 'demo') { setDate('2026-09-14'); setInstrument('NIFTY'); }
          }}><option value="archive">Historical archive</option><option value="file">Upload historical JSON</option><option value="demo">Synthetic NIFTY demo · 14 Sep 2026</option></select></label>
        </div>
        <label>Trading levels<textarea required rows="4" value={levels} placeholder={'59800\n60000\n60250'} onChange={event => setLevels(event.target.value)} /></label>
        <p className="ms-sub">Enter one level per line, or separate levels with commas.</p>
        {source === 'file' && <label>Historical dataset<input type="file" accept=".json,application/json" onChange={async event => {
          const file = event.target.files?.[0]; setDataset(null); setFileName(''); setError('');
          if (!file) return;
          setReading(true);
          try {
            if (file.size > 25 * 1024 * 1024) throw new Error('Choose a JSON file smaller than 25 MB.');
            setDataset(parseHistoricalDataset(await file.text())); setFileName(file.name);
          } catch (error) { setError(error.message); }
          finally { setReading(false); }
        }} /></label>}
        {fileName && source === 'file' && <p className="ms-sub">{fileName} · {dataset.ticks.length} ticks · {dataset.contracts.length} contracts</p>}
        <p className="ms-sub">Historical data must include recorded index prices, option prices, and that day's option contracts with expiry and lot size. Missing option quotes are reported as data gaps. The demo uses synthetic data.</p>
        <details className="ms-backtest-settings"><summary>Current settings{result ? ' / last run snapshot' : ''}</summary>
          <p>Initial arm distance: {formatPrice(settings?.index_settings?.[instrument]?.initial_arm_distance_points)} points</p>
          <dl className="ms-backtest-grid">{currentSettings.map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{String(value)}</dd></div>)}</dl>
          <p className="ms-sub">A new run captures application settings at execution time. Saved runs keep their original snapshot.</p>
        </details>
        <button className="ms-button ms-primary" type="submit">{busy ? 'Running…' : 'Run Backtest'}</button>
      </fieldset>
    </form>
    <label>Saved runs<select disabled={busy} value={result?.id ?? ''} onChange={async event => {
      if (!event.target.value) return;
      setBusy(true); setError('');
      try { const saved = await request(`/backtests/${event.target.value}`); setResult(saved); setSettings(saved.settings_snapshot); setSelectedTrade(''); }
      catch (error) { setError(error.message); }
      finally { setBusy(false); }
    }}><option value="">Select a run</option>{runs.map(run => <option key={run.id} value={run.id}>{run.trading_date ?? 'Legacy run'} · {run.instrument} · {run.status} · {run.id.slice(0, 8)}</option>)}</select></label>
    {error && <p className="ms-error" role="alert">{error}</p>}
    {busy && <p role="status">Loading backtest…</p>}
    {result && <BacktestResults result={result} selectedTrade={selectedTrade} setSelectedTrade={setSelectedTrade} />}
  </section>;
}


export function BacktestResults({ result, selectedTrade = '', setSelectedTrade }) {
  const trade = result?.trades?.find(row => String(row.trade_id) === selectedTrade);
  const timeline = eventsForTrade(result?.timeline ?? [], trade);
  return <section className="ms-report-timeline" aria-label="Backtest results">
      <div className="ms-sectionhead">{result.status} · {result.instrument} · {result.trading_date}</div><p className="ms-sub">Run ID: {result.id} · Source: {result.data_source}</p>
      {result.status === 'FAILED' && <p className="ms-error" role="alert">{result.error_message ?? result.error}</p>}
      <dl className="ms-report-summary">{[['Total Trades', result.total_trades], ['Wins', result.wins], ['Losses', result.losses], ['Win Rate', `${formatPrice(result.win_rate)}%`], ['P&L', formatPrice(result.gross_pnl)], ['Profit Factor', result.profit_factor == null ? 'N/A' : formatPrice(result.profit_factor)], ['Max Drawdown', formatPrice(result.max_drawdown)]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <p className="ms-sub">Breakeven {result.breakeven} · Open {result.open_trades} · Average P&L {formatPrice(result.average_pnl)} · Average return {formatPrice(result.average_return_percent)}% · Total return {formatPrice(result.total_return_percent)}% · Best trade {formatPrice(result.best_trade)} · Worst trade {formatPrice(result.worst_trade)}</p>
      <p className="ms-sub">Costs are not modelled. Drawdown uses realised P&L in exit order; total return uses the sum of closed trade entry premiums. {result.ticks_processed} ticks processed.</p>
      <div className="ms-tablewrap"><table><thead><tr>{['Signal time', 'Level', 'Direction', 'Option', 'Entry', 'Exit', 'Exit reason', 'Quantity', 'P&L', 'Return %'].map(label => <th key={label}>{label}</th>)}</tr></thead>
        <tbody>{result.trades.map(row => <tr key={row.trade_id} onClick={() => setSelectedTrade(String(row.trade_id))}>
          <td>{localTime(row.signal_timestamp)}</td><td>{formatPrice(row.trigger_level)}</td><td>{row.direction}</td><td>{row.option_symbol}<small className="ms-time">{row.expiry} · Strike {row.strike}</small></td>
          <td>{formatPrice(row.entry_price)}<small className="ms-time">{localTime(row.entry_time)}</small></td><td>{formatPrice(row.exit_price)}<small className="ms-time">{localTime(row.exit_time)}</small></td>
          <td>{row.exit_reason ? formatExitReason(row.exit_reason) : row.status}</td><td>{row.quantity}</td><td>{formatPrice(row.realised_pnl)}</td><td>{formatPrice(row.realised_pnl_percentage)}</td>
        </tr>)}{result.trades.length === 0 && <tr><td colSpan="10">No trades created. Inspect the timeline and entry results.</td></tr>}</tbody>
      </table></div>
      <details className="ms-backtest-settings"><summary>Signal and entry results</summary>
        <ul>{result.signals.map(signal => <li key={signal.id}>{localTime(signal.timestamp)} · Level {signal.level} · {signal.direction} · {signal.valid ? 'VALID' : `REJECTED: ${signal.rejection_reason}`}</li>)}</ul>
        <ul>{result.option_selections.filter(selection => selection.status === 'FAILED').map(selection => <li key={selection.id}>Selection #{selection.id} · {selection.failure_reason}</li>)}</ul>
        <ul>{result.entry_results.map(entry => <li key={entry.option_selection_id}>Selection #{entry.option_selection_id} · {entry.failure_reason ?? 'Trade created'}</li>)}</ul>
      </details>
      <div className="ms-sectionhead">Event Timeline</div>
      <label>Trade<select value={selectedTrade} onChange={event => setSelectedTrade(event.target.value)}><option value="">Whole session</option>{result.trades.map(row => <option key={row.trade_id} value={row.trade_id}>Trade #{row.trade_id} · Level {row.trigger_level} · {row.option_symbol}</option>)}</select></label>
      <div className="ms-tablewrap"><table><thead><tr>{['Time', 'Event', 'Level / Index', 'Option price', 'Highest / Stop', 'Return %', 'Details'].map(label => <th key={label}>{label}</th>)}</tr></thead>
        <tbody>{timeline.map(event => <tr key={event.id}><td>{localTime(event.timestamp)}</td><td>{event.event_type}</td><td>{formatPrice(event.payload.level)} / {formatPrice(event.payload.index_price)}</td><td>{formatPrice(event.payload.option_price)}</td><td>{formatPrice(event.payload.highest_price)} / {formatPrice(event.payload.stop_price)}</td><td>{formatPrice(event.payload.return_percent)}</td><td>{event.payload.reason ?? event.payload.failure_reason ?? event.payload.rejection_reason ?? event.payload.status ?? event.payload.armed_from}<details><summary>Event details</summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details></td></tr>)}</tbody>
      </table></div>
    </section>;
}
