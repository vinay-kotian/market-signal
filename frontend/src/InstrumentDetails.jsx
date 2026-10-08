import React, { useEffect, useRef, useState } from 'react';
import { request } from './api';
import { formatPrice, tradingDate } from './format';
import { markerTypes, istTime, istEventTime, eventMarkers, mergeLiveCandles } from './chartData';
import { mountCharts } from './chartRuntime';

const path = (symbol, kind, day) => `/instruments/${encodeURIComponent(symbol)}/${kind}?date=${day}`;
const percentage = value => value == null ? '—' : `${formatPrice(value)}%`;

export function EventDetails({ event, tooltip = false }) {
  if (!event) return <p className="ms-sub">Hover or click a marker, or select a recorded event below.</p>;
  const rows = [['Time (IST)', istEventTime(event.timestamp)],
    ['Price', formatPrice(event.price)], ['Configured level', event.level == null ? null : formatPrice(event.level)],
    ['Direction', event.direction], ['Signal ID', event.signal_id], ['Trade ID', event.trade_id],
    ['Event', event.event_type], ['Touch / cross', event.trigger_kind], ['Rejection reason', event.rejection_reason],
    ['Contract', event.option_symbol], ['Strike', event.strike], ['Expiry', event.expiry], ['CE / PE', event.option_type],
    ['Quantity', event.quantity], ['Signal index price', event.index_price == null ? null : formatPrice(event.index_price)],
    ['Entry time (IST)', event.entry_time ? istEventTime(event.entry_time) : null],
    ['Initial stop', event.initial_stop_loss == null ? null : formatPrice(event.initial_stop_loss)],
    ['Previous stop', event.previous_stop == null ? null : formatPrice(event.previous_stop)],
    ['Updated stop', event.current_stop == null ? null : formatPrice(event.current_stop)],
    ['Exit reason', event.exit_reason], ['Realized P&L (₹)', event.realised_pnl == null ? null : formatPrice(event.realised_pnl)],
    ['Realized P&L (%)', event.realised_pnl_percentage == null ? null : percentage(event.realised_pnl_percentage)],
    ['Duration', event.duration_seconds == null ? null : `${Math.floor(event.duration_seconds / 60)}m ${Number((event.duration_seconds % 60).toFixed(3))}s`]];
  return <div className="ms-chart-event-details" role={tooltip ? 'tooltip' : undefined}>
    <strong>{markerTypes[event.event_type]?.[0] ?? event.event_type}</strong>
    <dl>{rows.filter(([, value]) => value != null).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
  </div>;
}

function ChartPair({ panels, day, enabled, onSelect }) {
  const containers = useRef([]), runtime = useRef(null), latest = useRef(null);
  const [hover, setHover] = useState(null), [error, setError] = useState('');
  latest.current = panels.map((panel, index) => ({ ...panel, enabled, element: containers.current[index] }));
  const key = panels.map(panel => panel.symbol).join('|');
  useEffect(() => {
    let cancelled = false;
    setHover(null); setError('');
    import('lightweight-charts').then(library => {
      if (cancelled) return;
      runtime.current = mountCharts(library, latest.current.map((panel, index) => ({ ...panel, element: containers.current[index] })), day, setHover, onSelect);
    }).catch(() => { if (!cancelled) setError('Chart renderer could not load. Recorded events remain available below.'); });
    return () => { cancelled = true; runtime.current?.destroy(); runtime.current = null; };
  }, [key, day]);
  useEffect(() => { panels.forEach((panel, index) => runtime.current?.update(index, { ...panel, enabled })); }, [panels, enabled]);
  return <div className="ms-chart-pair">
    {error && <p role="alert" className="ms-error">{error}</p>}
    {panels.map((panel, index) => <section className="ms-chart-panel" key={panel.symbol} aria-label={`${panel.symbol} minute candles`}>
      <div className="ms-sectionhead"><span>{panel.symbol} · {index === 0 && panel.isIndex ? 'Index price' : 'Option premium'} · 1 minute</span>
        <span className="ms-sub">{hover?.time ? `${istTime(hover.time * 1000)} IST` : '09:15–15:30 IST'}</span></div>
      <div className="ms-chart-ohlc ms-sub">{hover?.candles?.[index] ? ['open', 'high', 'low', 'close'].map(field => `${field[0].toUpperCase()} ${formatPrice(hover.candles[index][field])}`).join(' · ') : hover?.time ? 'No observed candle at this time' : 'Zoom with the wheel · drag to pan'}</div>
      {panel.message && <p className="ms-chart-message ms-sub">{panel.message}</p>}
      {!panel.candles.length && <p className="ms-chart-message">No candles available. Recorded events are listed below.</p>}
      <div className="ms-chart-canvas" ref={element => { containers.current[index] = element; }} />
    </section>)}
    {hover?.event && <div className="ms-chart-tooltip"><EventDetails event={hover.event} tooltip /></div>}
    <p className="ms-sub">Charts by <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts</a>. Marker times are positioned within their minute; event details preserve exact timestamps and prices. Dashed red lines are saved initial-stop references for the listed trades.</p>
  </div>;
}

export default function InstrumentDetails({ symbol, today = tradingDate(), prices = {}, chartCandles = {}, revision = 0, onBack }) {
  const [day, setDay] = useState(today), [info, setInfo] = useState(null), [option, setOption] = useState('');
  const [datasets, setDatasets] = useState(null), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const cached = useRef(null);
  const [enabled, setEnabled] = useState(() => Object.fromEntries(Object.keys(markerTypes).map(type => [type, true])));
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    let cancelled = false;
    setError('');
    request(path(symbol, 'trades', day)).then(result => {
      if (cancelled) return;
      setInfo(result);
      const contracts = [...new Set(result.trades.map(trade => trade.option_symbol))];
      setOption(previous => result.instrument.instrument_type !== 'INDEX' ? result.instrument.symbol :
        contracts.includes(previous) ? previous : contracts[0] ?? '');
    }).catch(problem => { if (!cancelled) setError(problem.message); });
    return () => { cancelled = true; };
  }, [symbol, day, revision, retry]);
  const index = info?.instrument.instrument;
  useEffect(() => {
    if (!info || info.date !== day || (info.instrument.symbol !== symbol && String(info.instrument.instrument_token) !== symbol)) return;
    let cancelled = false;
    const symbols = [index, ...(option ? [option] : [])];
    // Events refresh on committed engine changes. Candle requests are cached by
    // the backend, and current minute observations arrive over the shared feed.
    Promise.all(symbols.map(async instrument => {
      const saved = cached.current?.day === day && cached.current?.retry === retry
        ? cached.current.panels.find(panel => panel.symbol === instrument) : null;
      const results = await Promise.allSettled([
        saved ? Promise.resolve({ candles: saved.candles, message: saved.candleMessage, as_of: saved.asOf }) : request(path(instrument, 'candles', day)),
        request(path(instrument, 'events', day))]);
      const [candles, events] = results;
      return { symbol: instrument, isIndex: instrument === index,
        candles: candles.status === 'fulfilled' ? candles.value.candles : [],
        asOf: candles.status === 'fulfilled' ? candles.value.as_of : null,
        candleMessage: candles.status === 'fulfilled' ? candles.value.message : candles.reason.message,
        events: events.status === 'fulfilled' ? events.value.events : [],
        eventsError: events.status === 'rejected',
        message: [candles.status === 'fulfilled' ? candles.value.message : candles.reason.message,
          events.status === 'rejected' ? events.reason.message : null].filter(Boolean).join(' '),
        trades: instrument === index ? [] : info.trades.filter(trade => trade.option_symbol === instrument) };
    })).then(result => { if (!cancelled) { cached.current = { day, symbols, panels: result, retry }; setDatasets(cached.current); } });
    return () => { cancelled = true; };
  }, [info, index, option, day, retry]);
  const activeData = datasets?.day === day && datasets.symbols.join('|') === [index, ...(option ? [option] : [])].join('|') ? datasets : null;
  const panels = activeData?.panels.map(panel => {
    const merged = mergeLiveCandles(panel.candles, chartCandles[panel.symbol], day, today, panel.asOf);
    return { ...panel, candles: merged };
  }) ?? [];
  const headerPanel = panels.find(panel => panel.symbol === symbol) ?? panels[0];
  const last = headerPanel?.candles.at(-1)?.close;
  const quote = day === today ? prices[symbol] : null;
  const change = quote?.change ?? (last != null && headerPanel?.candles.length ? last - headerPanel.candles[0].open : null);
  const changePercent = quote?.change_percentage ?? (change != null && headerPanel?.candles[0]?.open > 0 ? change / headerPanel.candles[0].open * 100 : null);
  const allEvents = panels.flatMap(panel => panel.events).sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
  const contracts = [...new Map((info?.trades ?? []).map(trade => [trade.option_symbol, trade])).values()];
  const chosen = contracts.find(trade => trade.option_symbol === option);
  const unplotted = panels.reduce((count, panel) => count + panel.events.filter(event => enabled[event.event_type]).length - eventMarkers(panel.events, panel.candles, enabled, day).length, 0);
  return <section className="ms-instrument-details" aria-label="Instrument Details">
    <button className="ms-link" onClick={onBack}>← Back to Dashboard</button>
    <div className="ms-heading"><h2>{symbol} · Instrument Details</h2><label>Trading date (IST)<input type="date" value={day} max={today} onChange={event => { setDay(event.target.value || today); setDatasets(null); setSelected(null); }} /></label></div>
    <div className="ms-pricebar"><div><strong>{formatPrice(quote?.price ?? last)}</strong><small className="ms-time">{day === today ? 'Current / last received price' : 'Last recorded close'}</small></div>
      <span className={change == null ? '' : change >= 0 ? 'ms-up' : 'ms-down'}>{formatPrice(change)} · {percentage(changePercent)}<small className="ms-time">{quote?.change != null ? 'Feed reference' : 'From first observed open'}</small></span><span className="ms-sub">PAPER · Asia/Kolkata</span></div>
    {error && <p role="alert" className="ms-error">{error}</p>}
    <button className="ms-link" onClick={() => setRetry(value => value + 1)}>Reload chart data</button>
    {contracts.length > 0 && info?.instrument.instrument_type === 'INDEX' && <label className="ms-chart-contract">Option contract<select value={option} onChange={event => { setOption(event.target.value); setSelected(null); }}>{contracts.map(trade => <option key={trade.option_symbol} value={trade.option_symbol}>{trade.option_symbol}</option>)}</select></label>}
    {info && (chosen || info.instrument.instrument_type !== 'INDEX') && <p className="ms-sub">Strike {formatPrice(chosen?.strike ?? info?.instrument.strike)} · Expiry {chosen?.expiry ?? info?.instrument.expiry} · {chosen?.option_type ?? info?.instrument.instrument_type}</p>}
    <fieldset className="ms-marker-filters"><legend>Event markers</legend>{Object.entries(markerTypes).map(([type, [label, color]]) => <label key={type} style={{ '--marker-color': color }}><input type="checkbox" checked={enabled[type]} onChange={event => setEnabled(previous => ({ ...previous, [type]: event.target.checked }))} />{label}</label>)}</fieldset>
    {!activeData ? <p role="status">{error ? 'Chart data could not be loaded. Use Reload chart data to retry.' : 'Loading chart data…'}</p> : <ChartPair panels={panels} day={day} enabled={enabled} onSelect={setSelected} />}
    {unplotted > 0 && <p className="ms-sub">{unplotted} enabled events outside the chart session are available in the event list.</p>}
    {!option && info && <p className="ms-sub">No associated PAPER option trades for this date.</p>}
    <div className="ms-sectionhead">Recorded events · {allEvents.length}</div>
    <p className="ms-sub">Initial arm and touch/cross details are recorded from this version onward. Older signals and executions remain available.</p>
    <div className="ms-chart-events"><div className="ms-chart-event-list">{allEvents.filter(event => enabled[event.event_type]).map(event => <button className="ms-chart-event" key={event.id} aria-pressed={selected?.id === event.id} onClick={() => setSelected(event)}><time>{istTime(event.timestamp)}</time> {markerTypes[event.event_type]?.[0] ?? event.event_type} {event.trade_id ? `· Trade #${event.trade_id}` : ''}</button>)}{activeData && !allEvents.length && <p>{panels.some(panel => panel.eventsError) ? 'Trading events unavailable. Reload chart data to retry.' : 'No recorded events for this date.'}</p>}</div><EventDetails event={selected} /></div>
  </section>;
}
