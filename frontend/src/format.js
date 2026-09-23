export const formatPrice = value => value == null ? '—' : value.toLocaleString('en-IN', {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
});

export const formatExitReason = reason => ({
  STOP_LOSS: 'Stop Loss',
  TRAILING_STOP_LOSS: 'Trailing Stop Loss',
  MARKET_CLOSING_EXIT: 'Market Closing Exit',
  MANUAL_SQUARE_OFF: 'Manual Square Off',
})[reason] ?? reason?.replaceAll('_', ' ') ?? '—';

export function levelStatus(level, events) {
  if (level.status === 'EXPIRED') return 'EXPIRED';
  if (level.status === 'PENDING_ARM') return 'PENDING_ARM';
  if (!level.enabled) return 'DISABLED';
  if (events === null) return 'UNAVAILABLE';
  return events.some(event => event.level_id === level.id
    && event.instrument === level.instrument && event.level_price === level.price
    && Date.parse(event.triggered_at) >= Date.parse(level.updated_at))
    ? 'TRIGGERED' : 'WAITING';
}

export function tradingDate(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now);
  const value = type => parts.find(part => part.type === type).value;
  return `${value('year')}-${value('month')}-${value('day')}`;
}

export function levelsForDate(levels, today, view = 'TODAY') {
  return levels.filter(level => view === 'ALL' || level.level_date === today);
}
