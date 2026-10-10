import React, { useEffect, useState } from 'react';
import { request } from './api';

export default function TelegramSettings() {
  const [settings, setSettings] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function load() {
    setError('');
    try { setSettings(await request('/settings/telegram')); }
    catch (error) { setError(error.message); }
  }
  useEffect(() => { load(); }, []);
  async function toggle(enabled) {
    setBusy(true); setError(''); setNotice('');
    try {
      setSettings(await request('/settings/telegram', {
        method: 'PUT', body: JSON.stringify({ enabled }),
      }));
      setNotice(enabled ? 'Telegram entry alerts enabled.' : 'Telegram entry alerts disabled.');
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }
  return <section aria-label="Telegram notifications">
    <h3 className="ms-sectionhead">Telegram notifications</h3>
    <p className="ms-sub">Send a message to your Telegram channel when a PAPER option trade opens, including the touched index level, option contract, entry premium, quantity and initial stop. Backtests send no messages.</p>
    {settings ? <label className="ms-check">
      <input type="checkbox" role="switch" checked={settings.enabled} disabled={busy}
        onChange={event => toggle(event.target.checked)} />Telegram option entry alerts
    </label> : !error && <p role="status">Loading Telegram settings…</p>}
    {busy && <p role="status">Saving…</p>}
    {notice && <p role="status">{notice}</p>}
    {error && <p className="ms-error" role="alert">{error} {!settings && <button onClick={load}>Retry</button>}</p>}
  </section>;
}
