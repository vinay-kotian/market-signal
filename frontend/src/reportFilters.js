import { tradingDate } from './format.js';
import { request } from './api.js';

export function defaultReportRange(now = new Date()) {
  const today = tradingDate(now);
  return { fromDate: today, toDate: today };
}

export function reportRangeError({ fromDate, toDate }) {
  if (!fromDate || !toDate) return 'Choose both From Date and To Date.';
  if (fromDate > toDate) return 'From Date cannot be after To Date.';
  return '';
}

export async function loadReport(filters, { signal, send = request } = {}) {
  const error = reportRangeError(filters);
  if (error) throw new Error(error);
  const query = new URLSearchParams({
    view: filters.view, from_date: filters.fromDate, to_date: filters.toDate,
  });
  if (filters.status) query.set('status', filters.status);
  if (filters.instrument) query.set('instrument', filters.instrument);
  const historyQuery = new URLSearchParams(query);
  historyQuery.set('page', filters.page);
  historyQuery.set('page_size', 20);
  const [report, history, matchingIds] = await Promise.all([
    send(`/reports/paper-trading?${query}`, { signal }),
    send(`/trades/history?${historyQuery}`, { signal }),
    send(`/trades/history/ids?${query}`, { signal }),
  ]);
  return { report, history, matchingIds };
}
