import React, { useState } from 'react';
import { request } from './api';
import ConnectionPage from './ConnectionPage';

export default function SettingsPage({ indexes, error, onRefresh, connection, connectionError, feedStatus, lastUiEvent }) {
  return <div className="ms-settings">
    <section aria-label="Index Rules">
      <h3 className="ms-sectionhead">Index Rules</h3>
      <p className="ms-sub">Initial arm distance applies to pending levels for each index. Active and disarmed levels keep their state.</p>
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
