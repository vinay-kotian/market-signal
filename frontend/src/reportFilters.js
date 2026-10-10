import { rangeError as reportRangeError } from './dateRange.js';
import { tradingDate } from './format.js';
import { request } from './api.js';

export function defaultReportRange(now = new Date()) {
  const today = tradingDate(now);
  return { fromDate: today, toDate: today };
}

export { rangeError as reportRangeError } from './dateRange.js';

function reportQuery(filters) {
  const error = reportRangeError(filters);
  if (error) throw new Error(error);
  const query = new URLSearchParams({
    view: filters.view, from_date: filters.fromDate, to_date: filters.toDate,
  });
  if (filters.status) query.set('status', filters.status);
  if (filters.strategyType) query.set('strategy_type', filters.strategyType);
  if (filters.instrument) query.set('instrument', filters.instrument);
  return query;
}

function paginatedQuery(query, page) {
  const historyQuery = new URLSearchParams(query);
  historyQuery.set('page', page);
  historyQuery.set('page_size', 20);
  return historyQuery;
}

export async function loadTradeHistory(filters, { signal, send = request } = {}) {
  // Trades includes all PAPER positions, including excluded strategy trades.
  const query = reportQuery({ ...filters, view: 'RAW' });
  return send(`/trades/history?${paginatedQuery(query, filters.page)}`, { signal });
}

export async function loadReport(filters, { signal, send = request } = {}) {
  const query = reportQuery(filters);
  const historyQuery = paginatedQuery(query, filters.page);
  const [report, history, matchingIds] = await Promise.all([
    send(`/reports/paper-trading?${query}`, { signal }),
    send(`/trades/history?${historyQuery}`, { signal }),
    send(`/trades/history/ids?${query}`, { signal }),
  ]);
  return { report, history, matchingIds };
}

export async function loadStrategyComparison(filters, { signal, send = request } = {}) {
  const query = reportQuery({ ...filters, strategyType: null });
  return send(`/reports/strategy-comparison?${query}`, { signal });
}

export async function exportReport(filters, { apiKey, send = request } = {}) {
  const query = reportQuery(filters);
  const mode = filters.mode ?? 'PAPER';
  query.set('mode', mode);
  if (!apiKey) throw new Error('Enter the API key to download CSV.');
  const blob = await send(`/reports/export?${query}`, {
    headers: { 'X-API-Key': apiKey }, responseType: 'blob',
  });
  return { blob, filename: `trading-report-${mode}-${filters.fromDate}-${filters.toDate}.csv` };
}

export function saveCsv({ blob, filename }) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Allow the browser to start the download before releasing the blob URL.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
