export function parseLevels(value) {
  const parts = value.trim().split(/[\s,]+/);
  const levels = [...new Set(parts.map(Number))];
  if (!value.trim() || levels.length > 100 || levels.some(price => !Number.isFinite(price) || price <= 0)) {
    throw new Error('Enter 1–100 positive levels, separated by newlines, commas, or spaces.');
  }
  return levels;
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
    || (event.trade_id == null && event.payload.level === trade.trigger_level)
    || ['MARKET_OPEN', 'MARKET_CLOSE'].includes(event.event_type));
}
