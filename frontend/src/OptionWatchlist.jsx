import React from 'react';
import { formatPrice } from './format';

export function visibleOptionWatchlist(items, today, search = '') {
  const query = search.trim().toLowerCase();
  return (items ?? []).filter(item => (item.status === 'ACTIVE' || item.watchlist_date === today)
    && [item.instrument, item.option_symbol, item.strike, item.expiry, item.option_type]
      .join(' ').toLowerCase().includes(query));
}

const percent = value => value == null ? '—' : `${value > 0 ? '+' : ''}${formatPrice(value)}%`;
const tone = value => value == null ? '' : value >= 0 ? 'ms-up' : 'ms-down';

export default function OptionWatchlist({ items, today, search = '', busy = false, error, onRemove, onOpen }) {
  const options = visibleOptionWatchlist(items, today, search);
  return <section className="ms-option-watchlist-section" aria-label="Traded option watchlist">
    <div className="ms-sidehead"><span className="ms-label">Traded options</span><span className="ms-sub">{options.length}</span></div>
    {error && <p className="ms-sidefoot ms-error" role="alert">{error}</p>}
    {items == null && !error && <p className="ms-sidefoot">Loading options…</p>}
    <div className="ms-option-watchlist">{options.map(item => <article
      key={item.option_symbol} className={`ms-option-watch ${item.status === 'ACTIVE' ? 'ms-option-active' : ''}`}
      aria-label={`${item.instrument} ${item.strike} ${item.option_type} ${item.status}`}>
      <div className="ms-option-head"><strong>{item.instrument} {item.option_type}</strong>
        <span className={`ms-status ${item.status === 'ACTIVE' ? 'triggered' : 'disabled'}`}>{item.status}</span>
        {item.status === 'CLOSED' && <button className="ms-link ms-option-remove" disabled={busy}
          aria-label={`Remove closed option ${item.option_symbol}`} onClick={() => onRemove(item.option_symbol)}>×</button>}
      </div>
      {onOpen ? <button className="ms-link ms-option-symbol" disabled={busy} title={item.option_symbol} aria-label={`Open ${item.option_symbol} Instrument Details`} onClick={() => onOpen(item.option_symbol)}>{item.option_symbol}</button> : <div className="ms-option-symbol" title={item.option_symbol}>{item.option_symbol}</div>}
      <div className="ms-sub">Strike {formatPrice(item.strike)} · Expiry {item.expiry}</div>
      <dl className="ms-option-quotes">
        <div><dt>Entry</dt><dd>{formatPrice(item.entry_price)}</dd></div>
        <div title={item.quote_timestamp ? `Last quote: ${new Date(item.quote_timestamp).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })} IST` : 'No quote received'}><dt>LTP</dt><dd>{formatPrice(item.current_ltp)}</dd></div>
        <div><dt>Change from entry</dt><dd className={tone(item.change_from_entry_percentage)}>{percent(item.change_from_entry_percentage)}</dd></div>
        <div><dt>{item.status === 'ACTIVE' ? 'Unrealized P&L' : 'Realized P&L'}</dt><dd className={tone(item.status === 'ACTIVE' ? item.unrealized_pnl_percentage : item.realised_pnl_percentage)}>{percent(item.status === 'ACTIVE' ? item.unrealized_pnl_percentage : item.realised_pnl_percentage)}</dd></div>
      </dl>
    </article>)}</div>
    {items && !options.length && !error && <p className="ms-sidefoot">{search ? 'No matching options.' : 'Entered options appear here automatically.'}</p>}
  </section>;
}
