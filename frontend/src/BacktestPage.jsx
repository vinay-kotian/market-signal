import React, { useState } from 'react';
import { request } from './api';
import { formatPrice } from './format';

const defaults = {
  lookback_minutes: 15, minimum_approach_distance_enabled: false,
  minimum_approach_distance_points: 0, itm_depth: 1, number_of_lots: 1,
  level_rearm_distance_points: 50,
  stop_loss_percentage: 10, trailing_stop_percentage: 10,
  breakeven_protection_enabled: true, breakeven_activation_percent: 10,
  breakeven_lock_percent: 0, trading_start_time: '09:15',
  new_trade_cutoff_time: '15:15', mandatory_exit_time: '15:25',
};

export default function BacktestPage() {
  const [instrument, setInstrument] = useState('NIFTY');
  const [levels, setLevels] = useState('25000');
  const [source, setSource] = useState('demo');
  const [dataset, setDataset] = useState(null);
  const [fileName, setFileName] = useState('');
  const [settings, setSettings] = useState(defaults);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState('');

  async function run(event) {
    event.preventDefault(); setError(''); setResult(null);
    const prices = levels.split(',').map(value => Number(value.trim()));
    if (prices.some(price => !Number.isFinite(price) || price <= 0)) {
      setError('Enter positive level prices separated by commas.'); return;
    }
    if (source === 'file' && !dataset) { setError('Choose a JSON dataset first.'); return; }
    setBusy(true);
    try {
      setResult(await request('/backtests/run', { method: 'POST', body: JSON.stringify({
        instrument, levels: prices, ...settings,
        ...(source === 'demo' ? { fixture: 'nifty-demo' } : { dataset }),
        ...(start ? { start_time: start } : {}), ...(end ? { end_time: end } : {}),
      }) }));
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  return <section aria-label="Backtesting">
    <p className="ms-sub">Replay recorded prices through the same strategy and risk rules. Each run is isolated from PAPER trading.</p>
    <form onSubmit={run}>
      <fieldset disabled={busy || reading} className="ms-backtest-fields">
        <div className="ms-report-filters">
          <label>Instrument<select value={instrument} onChange={event => setInstrument(event.target.value)}><option>NIFTY</option><option>BANKNIFTY</option></select></label>
          <label>Levels, separated by commas<input required value={levels} onChange={event => setLevels(event.target.value)} /></label>
          <label>Price data<select value={source} onChange={event => setSource(event.target.value)}><option value="demo">NIFTY demo · 14 Sep 2026</option><option value="file">Local JSON file</option></select></label>
        </div>
        {source === 'file' && <label>JSON dataset<input type="file" accept=".json,application/json" onChange={async event => {
          const file = event.target.files?.[0]; setDataset(null); setFileName(''); setError('');
          if (!file) return;
          setReading(true);
          try {
            if (file.size > 5 * 1024 * 1024) throw new Error('Choose a JSON file smaller than 5 MB.');
            const rows = JSON.parse(await file.text());
            if (!Array.isArray(rows) || rows.length === 0 || rows.length > 10000) throw new Error('JSON must contain 1–10,000 tick records.');
            setDataset(rows); setFileName(file.name);
          } catch (error) { setError(error.message); }
          finally { setReading(false); }
        }} /></label>}
        {fileName && source === 'file' && <p className="ms-sub">{fileName} · {dataset.length} records</p>}
        <p className="ms-sub">Records need timestamp (with timezone), instrument, and price. Include synthetic option-symbol prices before entry; no option quotes are invented. Equal-time records replay in file order.</p>
        <details className="ms-backtest-settings"><summary>Strategy settings and data range</summary>
          <div className="ms-backtest-grid">{Object.entries(settings).map(([key, value]) => <label key={key}>
            {key.replaceAll('_', ' ')}
            {typeof value === 'boolean' ? <input className="ms-checkbox" type="checkbox" checked={value} onChange={event => setSettings(previous => ({ ...previous, [key]: event.target.checked }))} />
              : <input required type={typeof value === 'number' ? 'number' : 'time'} step={typeof value === 'number' ? (['itm_depth', 'number_of_lots'].includes(key) ? '1' : 'any') : '1'} value={value} onChange={event => setSettings(previous => ({ ...previous, [key]: typeof value === 'number' ? Number(event.target.value) : event.target.value }))} />}
          </label>)}</div>
          <p className="ms-sub">Trading times use Asia/Kolkata. Optional range timestamps must include an offset. The replay clock stops at the last tick, or advances to the specified end time; positions can remain OPEN when the range ends before exit.</p>
          <div className="ms-report-filters"><label>Range start<input value={start} placeholder="2026-09-14T09:15:00+05:30" onChange={event => setStart(event.target.value)} /></label><label>Range end<input value={end} placeholder="2026-09-14T15:30:00+05:30" onChange={event => setEnd(event.target.value)} /></label></div>
        </details>
        <button className="ms-button ms-primary" type="submit">{busy ? 'Running…' : 'Run backtest'}</button>
      </fieldset>
    </form>
    {error && <p className="ms-error" role="alert">{error}</p>}
    {busy && <p role="status">Replaying historical ticks…</p>}
    {result && <section className="ms-report-timeline" aria-label="Backtest results">
      <div className="ms-sectionhead">{result.status} · Backtest</div><p className="ms-sub">Run ID: {result.id}</p>
      {result.status === 'FAILED' ? <p className="ms-error" role="alert">{result.error}</p> : <>
        <dl className="ms-report-summary">{[['Total trades', result.total_trades], ['Win rate', `${formatPrice(result.win_rate)}%`], ['Net P&L', formatPrice(result.net_pnl)], ['Profit factor', result.profit_factor === null ? 'N/A' : formatPrice(result.profit_factor)]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
        <p>Wins {result.wins} · Losses {result.losses} · Breakeven {result.breakeven} · Open {result.open_trades}</p>
        <p className="ms-sub">Gross profit {formatPrice(result.gross_profit)} · Gross loss {formatPrice(result.gross_loss)} · {result.ticks_processed} ticks processed. Performance counts closed trades only.</p>
        <div className="ms-tablewrap"><table><thead><tr>{['Instrument / level', 'Option', 'Quantity', 'Entry', 'Exit', 'P&L', 'Status', 'Exit reason'].map(label => <th key={label}>{label}</th>)}</tr></thead>
          <tbody>{result.trades.map(trade => <tr key={trade.trade_id}><td>{trade.instrument}<small className="ms-time">{formatPrice(trade.trigger_level)}</small></td><td>{trade.option_symbol}</td><td>{trade.quantity}</td><td>{formatPrice(trade.entry_price)}<small className="ms-time">{trade.entry_time}</small></td><td>{formatPrice(trade.exit_price)}<small className="ms-time">{trade.exit_time}</small></td><td>{formatPrice(trade.realised_pnl)}</td><td>{trade.status}<small className="ms-time">BACKTEST</small></td><td>{trade.exit_reason?.replaceAll('_', ' ') ?? '—'}</td></tr>)}{result.trades.length === 0 && <tr><td colSpan="8">No trades created. Check signal and entry results below.</td></tr>}</tbody>
        </table></div>
        <details className="ms-backtest-settings"><summary>Signal and entry results</summary>
          <ul>{result.signals.map(signal => <li key={signal.id}>Signal #{signal.id} · Level {signal.level} · {signal.valid ? 'VALID' : `REJECTED: ${signal.rejection_reason}`}</li>)}</ul>
          <ul>{result.option_selections.filter(selection => selection.status === 'FAILED').map(selection => <li key={selection.id}>Selection #{selection.id} · {selection.failure_reason}</li>)}</ul>
          <ul>{result.entry_results.map(entry => <li key={entry.option_selection_id}>Selection #{entry.option_selection_id} · {entry.failure_reason ?? 'Trade created'}</li>)}</ul>
        </details>
      </>}
    </section>}
  </section>;
}
