import React, { useEffect, useRef, useState } from 'react';
import { request } from './api';
import { tradingDate } from './format';
import { supportedIndices } from './indices';

export function StrategySelect({ value, onChange, atrEnabled = true, optional = false, disabled = false, label, className }) {
  return <label className={className}><span>{label}</span><select value={value ?? ''} disabled={disabled} onChange={event => onChange(event.target.value || null)}>
    {optional && <option value="">Use default</option>}<option value="LEGACY">Current / Legacy</option><option value="ATR" disabled={!atrEnabled}>ATR</option>
  </select></label>;
}

export const atrChoices = {
  atr_timeframe: ['5minute'], atr_trailing_mode: ['OFF', 'PERCENTAGE', 'ATR'],
  atr_breakeven_activation_mode: ['OFF', 'PERCENTAGE', 'ATR', 'R'],
};
export function ConfigurationFields({ settings, onChange, choices = atrChoices }) {
  return <div className="ms-backtest-grid">{Object.entries(settings).map(([key, value]) => <label key={key}>
    {key.replaceAll('_', ' ')}
    {choices[key] ? <select value={value} onChange={event => onChange(key, event.target.value)}>{choices[key].map(choice => <option key={choice}>{choice}</option>)}</select>
      : typeof value === 'boolean' ? <input type="checkbox" checked={value} onChange={event => onChange(key, event.target.checked)} />
        : <input type="number" step={key === 'atr_period' ? '1' : 'any'} value={value ?? ''} required={key !== 'atr_max_sl_percent'} onChange={event => onChange(key, event.target.value === '' ? (key === 'atr_max_sl_percent' ? null : '') : Number(event.target.value))} />}
  </label>)}</div>;
}

export default function ExitStrategySettings() {
  const browserDay = useRef(tradingDate());
  const [snapshot, setSnapshot] = useState(null), [configuration, setConfiguration] = useState(null);
  const [daily, setDaily] = useState(null), [legacy, setLegacy] = useState(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  function apply(saved) { setSnapshot(saved); setConfiguration(saved.configuration); setDaily(saved.daily); }
  async function load() {
    setError('');
    try { const [saved, current] = await Promise.all([request('/settings/exit-strategy'), request('/settings/exit-strategy/legacy')]); apply(saved); setLegacy(current); }
    catch (error) { setError(error.message); }
  }
  useEffect(() => { load(); }, []);
  useEffect(() => {
    const checkDay = () => {
      const day = tradingDate();
      if (!busy && browserDay.current !== day) {
        browserDay.current = day;
        load();
      }
    };
    const timer = setInterval(checkDay, 1000);
    window.addEventListener('focus', checkDay);
    return () => { clearInterval(timer); window.removeEventListener('focus', checkDay); };
  }, [busy]);
  async function save(path, data, label) {
    setBusy(true); setError(''); setNotice('');
    try {
      const saved = await request(`/settings/exit-strategy${path}`, { method: 'PUT', body: JSON.stringify(data) });
      if (path === '/legacy') setLegacy(saved); else apply(saved);
      setNotice(`${label} saved. Applies to future entries.`);
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }
  if (!snapshot) return <section aria-label="Exit Strategy"><h3 className="ms-sectionhead">Exit Strategy</h3>{error ? <p role="alert">{error} <button onClick={load}>Retry</button></p> : <p>Loading exit settings…</p>}</section>;
  const atr = Object.fromEntries(Object.entries(configuration).filter(([key]) => key.startsWith('atr_') && key !== 'atr_enabled'));
  const change = (key, value) => setConfiguration(previous => ({ ...previous, [key]: value }));
  const override = (previous, instrument, strategy) => {
    const overrides = { ...previous.instrument_overrides };
    if (strategy) overrides[instrument] = strategy; else delete overrides[instrument];
    return { ...previous, instrument_overrides: overrides };
  };
  return <section aria-label="Exit Strategy">
    <h3 className="ms-sectionhead">Exit Strategy <span className="ms-sub">PAPER</span></h3>
    <p className="ms-sub">Selections affect future entries. Open trades retain their strategy and configuration. Disabling ATR keeps existing ATR positions monitored; new ATR entries are skipped.</p>
    <form onSubmit={event => { event.preventDefault(); save('', configuration, 'Exit settings'); }}>
      <fieldset disabled={busy} className="ms-backtest-fields">
        <label className="ms-toggle"><input type="checkbox" role="switch" checked={configuration.atr_enabled} onChange={event => change('atr_enabled', event.target.checked)} /><span className="ms-toggle-track" aria-hidden="true" /><span>Enable ATR strategy for selection</span></label>
        <StrategySelect label="Persistent default" value={configuration.default_exit_strategy} atrEnabled={configuration.atr_enabled} onChange={value => change('default_exit_strategy', value)} />
        <h4>ATR configuration</h4>
        <ConfigurationFields settings={atr} onChange={change} />
        <p className="ms-sub">Option ATR uses completed 5-minute candles with Wilder smoothing. Entry ATR is frozen, including for ATR trailing. Leave maximum SL percent empty to remove the risk guard. A stop above the guard skips entry. Breakeven thresholds use the selected unit (percent, ATR multiples or initial risk R).</p>
        <details><summary>Persistent instrument overrides</summary><div className="ms-exit-overrides">{supportedIndices.map(instrument => <StrategySelect key={instrument} className="ms-exit-instrument-row" label={instrument} optional atrEnabled={configuration.atr_enabled} value={configuration.instrument_overrides[instrument]} onChange={value => setConfiguration(previous => override(previous, instrument, value))} />)}</div></details>
        <div className="ms-exit-actions"><button className="ms-button">Save exit settings</button></div>
      </fieldset>
    </form>
    <form onSubmit={event => { event.preventDefault(); save('/daily', daily, 'Daily selection'); }}>
      <fieldset disabled={busy} className="ms-backtest-fields">
        <h4>Today's selection · {snapshot.daily.trading_date} · Asia/Kolkata</h4>
        <StrategySelect label="Today's default" optional atrEnabled={snapshot.configuration.atr_enabled} value={daily.default_exit_strategy} onChange={value => setDaily(previous => ({ ...previous, default_exit_strategy: value }))} />
        <p className="ms-sub">A new trading day uses the persistent default unless that date has its own selection. Instrument overrides take priority over the daily default.</p>
        <div className="ms-exit-overrides">{supportedIndices.map(instrument => <StrategySelect key={instrument} className="ms-exit-instrument-row" label={`${instrument} today`} optional atrEnabled={snapshot.configuration.atr_enabled} value={daily.instrument_overrides[instrument]} onChange={value => setDaily(previous => override(previous, instrument, value))} />)}</div>
        <div className="ms-exit-actions"><button className="ms-button">Save today's selection</button></div>
      </fieldset>
    </form>
    <details><summary>Next trade overrides</summary><p className="ms-sub">Applies to one successful entry today, taking priority over instrument and daily selections.</p><div className="ms-exit-overrides">{supportedIndices.map(instrument => <StrategySelect key={instrument} className="ms-exit-instrument-row" label={`${instrument} next trade`} disabled={busy} optional atrEnabled={snapshot.configuration.atr_enabled} value={snapshot.next_trade_overrides[instrument]} onChange={value => save(`/next-trade/${instrument}`, { strategy: value }, 'Next trade override')} />)}</div></details>
    <p>Effective strategy for new entries: {Object.entries(snapshot.effective).map(([instrument, strategy]) => `${instrument}: ${strategy === 'LEGACY' ? 'Current' : strategy}`).join(' · ')}</p>
    {legacy && <form onSubmit={event => { event.preventDefault(); save('/legacy', legacy, 'Current configuration'); }}><fieldset disabled={busy} className="ms-backtest-fields"><h4>Current / Legacy configuration</h4><ConfigurationFields settings={legacy} choices={{ stop_strategy: ['PROGRESSIVE', 'LEGACY'] }} onChange={(key, value) => setLegacy(previous => ({ ...previous, [key]: value }))} /><p className="ms-sub">PROGRESSIVE retains profit lock and step-based tightening. LEGACY retains percentage trailing and breakeven.</p><button className="ms-button">Save current configuration</button></fieldset></form>}
    {notice && <p role="status">{notice}</p>}{error && <p className="ms-error" role="alert">{error}</p>}
  </section>;
}
