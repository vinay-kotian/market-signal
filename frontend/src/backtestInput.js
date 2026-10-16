export function latestCompletedSession(now = new Date(), closeTime = '15:30') {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(now).map(part => [part.type, part.value]));
  const day = new Date(`${parts.year}-${parts.month}-${parts.day}T00:00:00Z`);
  if (`${parts.hour}:${parts.minute}` < closeTime.slice(0, 5)) day.setUTCDate(day.getUTCDate() - 1);
  while ([0, 6].includes(day.getUTCDay())) day.setUTCDate(day.getUTCDate() - 1);
  return day.toISOString().slice(0, 10);
}

export function parseLevels(value) {
  const parts = value.trim().split(/[\s,]+/);
  const levels = [...new Set(parts)].map(part => {
    const [price, timeframe, extra] = part.split('@');
    if (extra !== undefined || (timeframe !== undefined && !/^[1-9][0-9]*[mhdw]$/.test(timeframe))) {
      throw new Error('Use price@timeframe, for example 25000@15m.');
    }
    return timeframe ? { price: Number(price), timeframe } : Number(price);
  });
  if (!value.trim() || levels.length > 100 || levels.some(item => { const price = typeof item === 'number' ? item : item.price; return !Number.isFinite(price) || price <= 0; })) {
    throw new Error('Enter 1–100 positive levels, separated by newlines, commas, or spaces.');
  }
  return [...new Map(levels.map(item => [typeof item === 'number' ? `${item}@` : `${item.price}@${item.timeframe}`, item])).values()];
}

export function savedLevelsText(records, instrument, date) {
  return [...new Set(records.filter(level => level.instrument === instrument && level.level_date === date)
    .sort((a, b) => Number(a.price) - Number(b.price) || a.id - b.id)
    .map(level => `${level.price}${level.timeframe ? `@${level.timeframe}` : ''}`))].join('\n');
}

export function parseHistoricalDataset(text) {
  const data = JSON.parse(text);
  if (!data || !Array.isArray(data.ticks) || !data.ticks.length || data.ticks.length > 100000
      || !Array.isArray(data.contracts) || !data.contracts.length || data.contracts.length > 10000) {
    throw new Error('JSON needs ticks (1–100,000) and a historical contracts catalogue (1–10,000).');
  }
  return data;
}

export function eventsForTrade(timeline, trade) {
  if (!trade) return timeline;
  return timeline.filter(event => event.trade_id === trade.trade_id
    || (event.trade_id == null && event.payload.level_id === trade.level_id)
    || (event.trade_id == null && trade.level_id == null && event.payload.level === trade.trigger_level
      && (event.payload.timeframe ?? null) === (trade.timeframe ?? null))
    || ['MARKET_OPEN', 'MARKET_CLOSE'].includes(event.event_type));
}
