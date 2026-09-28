import React, { useEffect, useState } from 'react';
import { request } from './api';
import ConnectionPage from './ConnectionPage';

export default function SettingsPage({ indexes, error, onRefresh, connection, connectionError, feedStatus, lastUiEvent }) {
  return <div className="ms-settings">
    <ProtectionSettings />
    <section aria-label="Index Rules">
      <h3 className="ms-sectionhead">Index Rules</h3>
      <p className="ms-sub">Initial arm distance is the minimum distance between the current index price and the configured level. It is checked on create, edit, and while pending. Changing this setting preserves active and disarmed states.</p>
      {error && <p role="alert">{error} <button onClick={onRefresh}>Retry</button></p>}
      {!indexes && !error && <p>Loading settings…</p>}
      <div className="ms-index-rules">{(indexes ?? []).map(index => <IndexRule key={`${index.instrument}-${index.updated_at}`} index={index} onRefresh={onRefresh} />)}</div>
    </section>
    <section id="connection" aria-labelledby="connection-heading" tabIndex={-1}>
      <h3 id="connection-heading" className="ms-sectionhead">Connection</h3>
      <ConnectionPage connection={connection} error={connectionError} onRefresh={onRefresh} feedStatus={feedStatus} lastUiEvent={lastUiEvent} />
    </section>
  </div>;
}

function IndexRule({ index, onRefresh }) {
  const [distance, setDistance] = useState(index.initial_arm_distance_points);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  async function save(event) {
    event.preventDefault(); setBusy(true); setMessage('');
    try {
      await request(`/settings/indexes/${index.instrument}`, { method: 'PUT', body: JSON.stringify({ initial_arm_distance_points: Number(distance) }) });
      setMessage('Saved'); await onRefresh();
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  return <form className="ms-index-rule" onSubmit={save}>
    <div className="ms-index-name">{index.instrument}</div>
    <label>Initial Arm Distance · points<input aria-label={`${index.instrument} Initial Arm Distance`} type="number" min="0" step="any" required value={distance} disabled={busy} onChange={event => setDistance(event.target.value)} /></label>
    <button className="ms-button" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button><span className="ms-index-message" role="status">{message}</span>
  </form>;
}

function ProtectionSettings() {
  const [settings, setSettings] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  async function load() {
    try { setSettings(await request('/settings/protection')); setMessage(''); }
    catch (error) { setMessage(error.message); }
  }
  useEffect(() => { load(); }, []);
  async function save(event) {
    event.preventDefault(); setBusy(true); setMessage('');
    try {
      setSettings(await request('/settings/protection', { method: 'PUT', body: JSON.stringify(settings) }));
      setMessage('Saved. Applies to new PAPER trades.');
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  return <section aria-label="Progressive trailing stop">
    <h3 className="ms-sectionhead">Progressive trailing stop</h3>
    <p className="ms-sub">Protect profit at the trigger, then tighten the trail as the highest premium rises. Open trades keep their entry settings. Backtests use the values selected for each run. There is no fixed profit target.</p>
    {!settings ? <p>{message || 'Loading settings…'} {message && <button onClick={load}>Retry</button>}</p> : <form onSubmit={save}>
      <fieldset disabled={busy} className="ms-backtest-grid">{Object.entries(settings).map(([key, value]) => <label key={key}>
        {key.replaceAll('_', ' ').replace(' pct', ' (%)')}
        <input type="number" required step="any" min={key === 'profit_lock_pct' ? '0' : '0.000001'} value={value}
          onChange={event => setSettings(previous => ({ ...previous, [key]: event.target.value === '' ? '' : Number(event.target.value) }))} />
      </label>)}</fieldset>
      <button className="ms-button" disabled={busy}>{busy ? 'Saving…' : 'Save protection settings'}</button>
      <p role="status">{message}</p>
    </form>}
  </section>;
}
