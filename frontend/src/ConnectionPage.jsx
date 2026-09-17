import React, { useState } from 'react';
import { request } from './api';
import { authenticationStatus } from './connectionState';

export default function ConnectionPage({ connection, error, onRefresh, feedStatus = 'DISCONNECTED', lastUiEvent }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [actionError, setActionError] = useState('');
  const status = authenticationStatus(connection, error);

  async function sync() {
    setBusy(true); setActionError(''); setMessage('');
    try {
      await request('/zerodha/instruments/sync', { method: 'POST' });
      setMessage('Instrument sync completed.');
      await onRefresh();
    } catch (error) { setActionError(error.message); }
    finally { setBusy(false); }
  }

  return <section aria-label="Market data connection">
    <p className="ms-sub">Execution remains PAPER. Market data mode is configured in the backend environment and takes effect after restart.</p>
    {(error || actionError) && <p className="ms-error" role="alert">{actionError || error}</p>}
    {!connection && !error && <p>Loading connection…</p>}
    <dl className="ms-report-metrics">
      <div><dt>Browser live feed</dt><dd>{feedStatus}</dd></div>
      <div><dt>Last UI event</dt><dd>{lastUiEvent ? new Date(lastUiEvent).toLocaleString() : '—'}</dd></div>
    </dl>
    {connection && <>
      <dl className="ms-report-metrics">
        <div><dt>Market data</dt><dd>{connection.market_data_mode}</dd></div>
        <div><dt>Connection</dt><dd>{status}</dd></div>
        <div><dt>Zerodha WebSocket</dt><dd>{connection.market_data_mode === 'ZERODHA' ? (connection.connection_status === 'CONNECTED' ? 'CONNECTED' : 'DISCONNECTED') : 'NOT_APPLICABLE'}<small className="ms-time">{connection.connection_status}</small></dd></div>
        <div><dt>Last Zerodha tick (received)</dt><dd>{connection.last_tick_at ? new Date(connection.last_tick_at).toLocaleString() : '—'}</dd></div>
        <div><dt>Subscribed instruments</dt><dd>{connection.subscribed_instrument_count ?? 0}</dd></div>
        <div><dt>Ticks received / reconnects</dt><dd>{connection.ticks_received ?? 0} / {connection.reconnect_count ?? 0}</dd></div>
        <div><dt>Instrument sync</dt><dd>{connection.instrument_sync_status}</dd></div>
        <div><dt>Last successful sync</dt><dd>{connection.last_successful_sync ? new Date(connection.last_successful_sync).toLocaleString() : '—'}</dd></div>
      </dl>
      {connection.market_data_mode === 'ZERODHA' ? <>
        {connection.auth_error && <p className="ms-error" role="alert">{connection.auth_error.message}<small className="ms-time">{connection.auth_error.code}</small></p>}
        {status === 'CONNECTED' ? <p>Zerodha session connected. You can sync instruments.</p>
          : status === 'ERROR' ? <p role="alert">Zerodha login could not be completed. Connect again to retry.</p>
          : <p>Connect your Zerodha session to receive market data.</p>}
        <div className="ms-actions">
          <a className="ms-button" href={connection.login_url || '/api/zerodha/login'}>Connect Zerodha</a>
          <button className="ms-button" disabled={busy || status !== 'CONNECTED'} onClick={sync}>Sync instruments</button>
        </div>
        <p className="ms-sub">Complete login on Zerodha. You will return here automatically. Passwords and OTPs stay on Zerodha.</p>
      </> : <p className="ms-sub">Simulated prices are active. To use Zerodha, configure MARKET_DATA_MODE=ZERODHA and the broker credentials on the backend.</p>}
    </>}
    <p role="status">{busy ? 'Working…' : message}</p>
  </section>;
}
