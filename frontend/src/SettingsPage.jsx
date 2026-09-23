import React, { useState } from 'react';
import { request } from './api';

export default function SettingsPage({ indexes, error, onRefresh }) {
  return <section aria-label="Index Rules">
    <div className="ms-sectionhead">Index Rules</div>
    <p className="ms-sub">Initial arm distance applies to pending levels for each index. Active and disarmed levels keep their state.</p>
    {error && <p role="alert">{error} <button onClick={onRefresh}>Retry</button></p>}
    {!indexes && !error && <p>Loading settings…</p>}
    {(indexes ?? []).map(index => <IndexRule key={`${index.instrument}-${index.updated_at}`} index={index} onRefresh={onRefresh} />)}
  </section>;
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
  return <form className="ms-report-filters" onSubmit={save}>
    <label>{index.instrument} Initial Arm Distance<input type="number" min="0" step="any" required value={distance} disabled={busy} onChange={event => setDistance(event.target.value)} /></label>
    <button className="ms-button" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button><span role="status">{message}</span>
  </form>;
}
