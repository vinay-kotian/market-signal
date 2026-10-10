import React, { useEffect, useState } from 'react';
import { request } from './api';
import { tradingTimePreview } from './tradingTime';

const fields = [
  ['market_open_time', 'Market Open Time', 'time'],
  ['market_close_time', 'Market Close Time', 'time'],
  ['entry_block_after_open_minutes', 'Entry Block After Open — minutes', 'number'],
  ['entry_block_before_close_minutes', 'Entry Block Before Close — minutes', 'number'],
  ['mandatory_exit_before_close_minutes', 'Mandatory Exit Before Close — minutes', 'number'],
];

export default function TradingTimeSettings() {
  const [configuration, setConfiguration] = useState(null), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    request('/settings/trading-time', { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setConfiguration(data.configuration); })
      .catch(problem => { if (!controller.signal.aborted) setError(problem.message); });
    return () => controller.abort();
  }, [retry]);
  const preview = configuration ? tradingTimePreview(configuration) : null;
  async function save(event) {
    event.preventDefault();
    if (preview?.error || !configuration || busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const data = await request('/settings/trading-time', { method: 'PUT', body: JSON.stringify(configuration) });
      setConfiguration(data.configuration);
      setNotice('Saved. PAPER entry and mandatory exit times now use this configuration. New backtests capture it when they start.');
    } catch (problem) { setError(problem.message); }
    finally { setBusy(false); }
  }
  return <section aria-label="Trading Time Configuration">
    <h3 className="ms-sectionhead">Trading Time Configuration</h3>
    <p className="ms-sub">All times use Asia/Kolkata (IST). Saved changes apply immediately to PAPER entries and mandatory exits, including open positions. Running backtests keep their original settings.</p>
    {error && <p className="ms-error" role="alert">{error}{!configuration && <button type="button" className="ms-link" onClick={() => setRetry(value => value + 1)}>Retry</button>}</p>}
    {!configuration && !error && <p role="status">Loading trading time settings…</p>}
    {configuration && <form onSubmit={save}>
      <fieldset disabled={busy} className="ms-trading-time-fields">
        {fields.map(([key, label, type]) => <label key={key}>{label}<input type={type} required
          step={type === 'time' ? '1' : 'any'} min={type === 'number' ? '0' : undefined}
          value={configuration[key]} onChange={event => {
            const value = event.target.value;
            setConfiguration(previous => ({ ...previous, [key]: type === 'number' && value !== '' ? Number(value) : value }));
            setNotice(''); setError('');
          }} /></label>)}
      </fieldset>
      <div className="ms-trading-windows" aria-live="polite">
        <h4>Calculated Trading Windows · IST</h4>
        {preview.error ? <p className="ms-error" role="alert">{preview.error}</p> : <dl>
          <div><dt>Entry Window</dt><dd>{preview.entryFrom} – {preview.entryUntil}</dd><small>Start inclusive · end exclusive</small></div>
          <div><dt>Mandatory Exit Starts</dt><dd>{preview.exitStarts}</dd></div>
        </dl>}
      </div>
      <button type="submit" className="ms-button" disabled={busy || Boolean(preview.error)}>{busy ? 'Saving…' : 'Save trading time configuration'}</button>
      {notice && <p role="status">{notice}</p>}
    </form>}
  </section>;
}
