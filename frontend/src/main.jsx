import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { request } from './api';
import { formatPrice, levelStatus } from './format';
import SignalsTable from './SignalsTable';
import OptionSelectionsTable from './OptionSelectionsTable';
import LevelForm from './LevelForm';
import TradesPage from './TradesPage';
import PaperReportPage from './PaperReportPage';
import BacktestPage from './BacktestPage';
import ConnectionPage from './ConnectionPage';
import { initialPage } from './connectionState';
import './styles.css';

function App() {
  const [page, setPage] = useState(() => initialPage(window.location.pathname));
  const [connection, setConnection] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [levels, setLevels] = useState(null);
  const [events, setEvents] = useState(null);
  const [signals, setSignals] = useState(null);
  const [selections, setSelections] = useState(null);
  const [trades, setTrades] = useState(null);
  const [entryResults, setEntryResults] = useState(null);
  const [errors, setErrors] = useState({});
  const [selected, setSelected] = useState('');
  const [search, setSearch] = useState('');
  const [prices, setPrices] = useState({});
  const [tickPrice, setTickPrice] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [editor, setEditor] = useState(null);
  const [deleting, setDeleting] = useState(null);

  async function refresh() {
    setRefreshKey(value => value + 1);
    await Promise.all([
      ['/connection', setConnection, 'connection'], ['/levels', setLevels, 'levels'], ['/simulation/events', setEvents, 'events'], ['/signals', setSignals, 'signals'],
      ['/option-selections', setSelections, 'selections'],
      ['/trades', setTrades, 'trades'], ['/trade-entry-results', setEntryResults, 'entryResults'],
    ].map(async ([path, setter, key]) => {
      try {
        setter(await request(path));
        setErrors(previous => ({ ...previous, [key]: null }));
      } catch (error) {
        setter(null);
        setErrors(previous => ({ ...previous, [key]: error.message }));
      }
    }));
  }
  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    if (connection?.market_data_mode !== 'ZERODHA') return;
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [connection?.market_data_mode]);
  const instruments = [...new Set((levels ?? []).map(level => level.instrument))];
  useEffect(() => {
    if (!instruments.includes(selected)) setSelected(instruments[0] ?? '');
  }, [levels]);

  async function mutate(action) {
    setBusy(true); setErrors(previous => ({ ...previous, action: null })); setMessage('');
    try { await action(); await refresh(); }
    catch (error) { setErrors(previous => ({ ...previous, action: error.message })); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    const onPopState = () => setPage(initialPage(window.location.pathname));
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);
  function navigate(next) { window.history.pushState({}, '', '/' + next); setPage(next); setEditor(null); setDeleting(null); }
  const rows = (levels ?? []).filter(level => level.instrument === selected);
  const live = connection?.market_data_mode === 'ZERODHA';
  const shownPrices = live ? Object.fromEntries(Object.entries(connection.prices ?? {}).map(([symbol, price]) => [symbol, { price }])) : prices;
  const current = shownPrices[selected]?.price;

  return <div id="ms-design">
    <header><span className="ms-logo" aria-hidden="true">π</span><span className="ms-brand">Market Signal</span><span className="ms-env">PAPER · {connection?.market_data_mode ?? 'LOADING'} DATA</span></header>
    <div className="ms-shell">
      <aside aria-label="Instrument watchlist">
        <div className="ms-sidehead"><span className="ms-label">Watchlist</span><span className="ms-sub">{instruments.length} instruments</span></div>
        <div className="ms-search"><input type="search" aria-label="Search instruments" placeholder="Search instruments" value={search} onChange={event => setSearch(event.target.value)} /></div>
        <div className="ms-watchlist">{instruments.filter(symbol => symbol.toLowerCase().includes(search.toLowerCase())).map(symbol => <button className="ms-watch" aria-pressed={symbol === selected} key={symbol} disabled={busy} onClick={() => { setSelected(symbol); setEditor(null); }}>
          <span>{symbol}<small>{levels.filter(level => level.instrument === symbol).length} levels</small></span>
          <span className="ms-quote">{formatPrice(shownPrices[symbol]?.price)}<small className={shownPrices[symbol]?.change >= 0 ? 'ms-up' : 'ms-down'}>{shownPrices[symbol]?.change == null ? 'No previous tick' : `${shownPrices[symbol].change >= 0 ? '↗ +' : '↘ '}${formatPrice(shownPrices[symbol].change)}`}</small></span>
        </button>)}</div>
        <div className="ms-sidefoot">{live ? 'Live Zerodha prices' : 'Prices sent from this browser session'}<br />{live ? 'Updated every 5 seconds' : 'Movement since previous submitted tick'}</div>
      </aside>
      <main>
        <nav aria-label="Pages">{['dashboard', 'levels', 'trades', 'report', 'backtest', 'connection'].map(name => <button className="ms-tab" key={name} aria-pressed={page === name} disabled={busy} onClick={() => navigate(name)}>{name[0].toUpperCase() + name.slice(1)}</button>)}</nav>
        <div className="ms-heading"><h2>{page[0].toUpperCase() + page.slice(1)}</h2><div className="ms-actions"><button className="ms-link" disabled={busy} onClick={() => mutate(async () => {})}>Refresh</button>{(page === 'dashboard' || page === 'levels') && <button className="ms-button" disabled={busy} onClick={() => page === 'dashboard' ? navigate('levels') : setEditor({})}>{page === 'dashboard' ? 'Manage levels ↗' : '+ Add level'}</button>}</div></div>
        {page === 'connection' && <ConnectionPage connection={connection} error={errors.connection} onRefresh={refresh} />}
        {page === 'backtest' && <BacktestPage />}
        {page === 'report' && <PaperReportPage refreshKey={refreshKey} />}
        {page === 'trades' && <TradesPage trades={trades} results={entryResults} error={errors.trades} resultsError={errors.entryResults} onRetry={() => mutate(async () => {})} />}
        {(page === 'dashboard' || page === 'levels') && <>
        {(errors.levels || errors.events || errors.action) && <div className="ms-error" role="alert">{errors.action || errors.levels || `Trigger status unavailable: ${errors.events}`} <button className="ms-link" disabled={busy} onClick={() => mutate(async () => {})}>Retry refresh</button></div>}
        {page === 'dashboard' && <div className="ms-pricebar"><div className="ms-instrument">{selected || 'No instrument selected'}</div><div><div className="ms-current">{formatPrice(current)}</div><div className="ms-sub">{live ? 'Latest received Zerodha price' : 'Last price submitted from this session'}</div></div></div>}
        {editor && <LevelForm key={editor.id ?? 'new'} level={editor.id ? editor : null} instrument={selected} instrumentOptions={connection?.available_instruments ?? []} live={live} busy={busy} onCancel={() => setEditor(null)} onSave={data => mutate(async () => {
          await request(editor.id ? `/levels/${editor.id}` : '/levels', { method: editor.id ? 'PUT' : 'POST', body: JSON.stringify(data) });
          setSelected(data.instrument); setEditor(null);
        })} />}
        <div className="ms-sectionhead"><span>Configured levels{page === 'levels' && selected ? ` · ${selected}` : ''}</span><span className="ms-sub">{rows.length} levels</span></div>
        {levels === null && !errors.levels ? <p>Loading levels…</p> : <div className="ms-tablewrap"><table>
          <thead><tr><th>Level price</th><th>Level state</th>{page === 'dashboard' ? <><th className="ms-num">Distance · pts</th><th>Status · recent</th></> : <><th>Enabled</th><th>Actions</th></>}</tr></thead>
          <tbody>{rows.map(level => <tr key={level.id}><td>{formatPrice(level.price)}</td><td><span className="ms-status">{level.status}</span></td>{page === 'dashboard' ? <>
            <td className="ms-num">{current == null ? '—' : `${level.price > current ? '+' : ''}${formatPrice(level.price - current)}`}</td>
            <td><span className={`ms-status ${levelStatus(level, events).toLowerCase()}`}>{levelStatus(level, events)}</span></td>
          </> : <><td><input className="ms-checkbox" type="checkbox" aria-label={`Enable level ${level.price}`} checked={level.enabled} disabled={busy} onChange={() => mutate(() => request(`/levels/${level.id}`, { method: 'PUT', body: JSON.stringify({ instrument: level.instrument, price: level.price, enabled: !level.enabled }) }))} /></td>
            <td><button className="ms-link" disabled={busy} onClick={() => setEditor(level)}>Edit</button><button className="ms-link ms-delete" disabled={busy} onClick={() => {
              if (deleting !== level.id) setDeleting(level.id);
              else mutate(async () => { await request(`/levels/${level.id}`, { method: 'DELETE' }); setDeleting(null); });
            }}>{deleting === level.id ? 'Confirm delete' : 'Delete'}</button>{deleting === level.id && <button className="ms-link" onClick={() => setDeleting(null)}>Cancel</button>}</td></>}</tr>)}
            {levels && rows.length === 0 && <tr><td colSpan="4" className="ms-empty">No levels configured. Add a level to begin.</td></tr>}
          </tbody>
        </table></div>}
        {page === 'dashboard' && <>
          {!live && connection?.market_data_mode === 'SIMULATED' && <form className="ms-simulation" onSubmit={event => {
            event.preventDefault(); const symbol = selected, price = Number(tickPrice);
            if (!symbol || !Number.isFinite(price)) return;
            mutate(async () => {
              await request('/simulation/tick', { method: 'POST', body: JSON.stringify({ instrument: symbol, price }) });
              setPrices(previous => ({ ...previous, [symbol]: { price, change: previous[symbol] ? price - previous[symbol].price : null } }));
              setMessage('Tick processed.');
            });
          }}>
            <div className="ms-sectionhead">Send a simulated price</div>
            <div className="ms-fields"><label>Instrument<select value={selected} disabled={busy || !instruments.length} onChange={event => setSelected(event.target.value)}>{!instruments.length && <option value="">Add a level first</option>}{instruments.map(symbol => <option key={symbol}>{symbol}</option>)}</select></label><label>Simulated price<input required type="number" step="any" value={tickPrice} onChange={event => setTickPrice(event.target.value)} /></label><button className="ms-button ms-primary" disabled={busy || !selected}>{busy ? 'Processing…' : 'Send Tick →'}</button></div>
            <div className="ms-message" role="status">{message}</div>
          </form>}
          <SignalsTable signals={signals} error={errors.signals} onRetry={() => mutate(async () => {})} />
          <OptionSelectionsTable selections={selections} error={errors.selections} onRetry={() => mutate(async () => {})} />
        </>}
        </>}
      </main>
    </div>
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);
