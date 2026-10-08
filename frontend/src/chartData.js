export const markerTypes = {
  LEVEL_ARMED: ['Level armed', '#2563eb', 'circle'],
  LEVEL_TRIGGERED: ['Level touch / cross', '#eab308', 'circle'],
  SIGNAL_GENERATED: ['Signal generated', '#16a34a', 'circle'],
  SIGNAL_REJECTED: ['Signal rejected', '#6b7280', 'circle'],
  TRADE_TRIGGERED: ['Trade triggered', '#9333ea', 'circle'],
  TRADE_ENTRY: ['Trade entry', '#16a34a', 'arrowUp'],
  TRADE_EXIT: ['Trade exit', '#dc2626', 'arrowDown'],
  INITIAL_STOP: ['Initial stop-loss', '#dc2626', 'circle'],
  BREAKEVEN_PROTECTION_ACTIVATED: ['Breakeven activated', '#2563eb', 'circle'],
  TRAILING_STOP_UPDATED: ['Trailing stop updated', '#ea580c', 'circle'],
  STOP_LOSS_HIT: ['Stop-loss triggered', '#dc2626', 'circle'],
  PROFIT_LOCK_ACTIVATED: ['Profit lock activated', '#2563eb', 'circle'],
  TRAILING_STEP_CHANGED: ['Trailing step changed', '#ea580c', 'circle'],
  MARKET_CLOSING_EXIT_TRIGGERED: ['Market closing exit', '#dc2626', 'circle'],
};

export const minuteOf = timestamp => Math.floor(new Date(timestamp).getTime() / 60000) * 60;
export const istTime = timestamp => new Date(timestamp).toLocaleTimeString('en-IN', {
  timeZone: 'Asia/Kolkata', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
});
export function istEventTime(timestamp) {
  const fraction = String(timestamp).match(/\.\d+/)?.[0] ?? '';
  const date = new Date(timestamp).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
  return `${date} ${istTime(timestamp)}${fraction} IST`;
}

// Identical whitespace grids keep logical zoom/pan ranges aligned without inventing
// candles in gaps. The session end is an axis point, not a fabricated closing bar.
export function sessionData(day, candles) {
  const start = Date.parse(`${day}T09:15:00+05:30`) / 1000;
  const map = new Map(candles.map(row => [row.time, row]));
  return Array.from({ length: 376 }, (_, index) => {
    const time = start + index * 60;
    const row = map.get(time);
    return row ? { time, open: row.open, high: row.high, low: row.low, close: row.close } : { time };
  });
}

export function eventMarkers(events, candles, enabled, day) {
  const times = new Set((day ? sessionData(day, []) : candles).map(row => row.time));
  return events.filter(event => enabled[event.event_type] && markerTypes[event.event_type]
    && Number.isFinite(event.price) && times.has(minuteOf(event.timestamp)))
    .map(event => ({ id: event.id, time: minuteOf(event.timestamp), price: event.price,
      position: 'atPriceMiddle', color: markerTypes[event.event_type][1],
      shape: markerTypes[event.event_type][2], text: event.trade_id ? `#${event.trade_id}` : '', size: 1 }))
    .sort((a, b) => a.time - b.time);
}

export function mergeLiveCandles(candles, live, day, today, asOf) {
  if (day !== today || live?.day !== day) return candles;
  const fetchedMinute = Math.floor(Date.parse(asOf) / 60000) * 60;
  const completedHistory = new Set(candles.filter(row => row.origin === 'ZERODHA_HISTORY' && row.time < fetchedMinute).map(row => row.time));
  const received = Object.values(live).filter(row => row?.time && !completedHistory.has(row.time));
  return [...new Map([...candles, ...received].map(row => [row.time, row])).values()].sort((a, b) => a.time - b.time);
}
