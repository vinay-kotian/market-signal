import React, { useEffect, useState } from 'react';
import { request } from './api';

export default function TelegramSettings() {
  const [settings, setSettings] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [url, setUrl] = useState('');
  async function load() {
    setError('');
    try {
      const saved = await request('/settings/telegram');
      setSettings(saved); setUrl(saved.url);
    }
    catch (error) { setError(error.message); }
  }
  useEffect(() => { load(); }, []);
  async function toggle(enabled) {
    setBusy(true); setError(''); setNotice('');
    try {
      setSettings(await request('/settings/telegram', {
        method: 'PUT', body: JSON.stringify({ enabled }),
      }));
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }
  async function saveUrl(event) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const saved = await request('/settings/telegram', {
        method: 'PUT', body: JSON.stringify({ enabled: settings.enabled, url: url.trim() }),
      });
      setSettings(saved); setUrl(saved.url); setNotice('Telegram URL saved.');
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }
  return <section aria-label="Telegram notifications">
    <h3 className="ms-sectionhead">Telegram notifications</h3>
    <p className="ms-sub">Send a message to your Telegram channel when a PAPER option trade opens, including the touched index level, option contract, entry premium, quantity and initial stop. Backtests send no messages.</p>
    {settings ? <><label className="ms-toggle">
      <input type="checkbox" role="switch" checked={settings.enabled} disabled={busy}
        onChange={event => toggle(event.target.checked)} />
      <span className="ms-toggle-track" aria-hidden="true" />
      <span>Telegram option entry alerts <strong className="ms-toggle-state" aria-hidden="true">{settings.enabled ? 'On' : 'Off'}</strong></span>
    </label>
      <form className="ms-report-filters ms-telegram-url" onSubmit={saveUrl}>
        <label>Telegram URL<input type="url" required value={url ?? ''} disabled={busy}
          onChange={event => setUrl(event.target.value)} placeholder="https://example.com/api/telegram" /></label>
        <button className="ms-button" type="submit" disabled={busy || !url?.trim() || url.trim() === settings.url}>Save URL</button>
      </form>
    </> : !error && <p role="status">Loading Telegram settings…</p>}
    {busy && <p role="status">Saving…</p>}
    {notice && <p role="status">{notice}</p>}
    {error && <p className="ms-error" role="alert">{error} {!settings && <button onClick={load}>Retry</button>}</p>}
  </section>;
}
