import { tradingDate } from './format.js';

export function addDays(day, count) {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + count);
  return date.toISOString().slice(0, 10);
}
export function presetRange(preset, now = new Date()) {
  const day = addDays(tradingDate(now), preset === 'YESTERDAY' ? -1 : 0);
  return { fromDate: day, toDate: day };
}
export function rangeError({ fromDate, toDate }, today = tradingDate()) {
  if (!fromDate || !toDate) return 'Choose both From Date and To Date.';
  for (const day of [fromDate, toDate]) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || Number.isNaN(Date.parse(`${day}T00:00:00Z`)) || new Date(`${day}T00:00:00Z`).toISOString().slice(0, 10) !== day) return 'From Date and To Date must be valid dates.';
  }
  if (fromDate > toDate) return 'From Date cannot be after To Date.';
  if (toDate > today) return 'To Date cannot be in the future.';
  return '';
}
export function selectDay(range, day, selectingEnd, singleDay = false) {
  if (singleDay || !selectingEnd) return { fromDate: day, toDate: singleDay ? day : '' };
  return { fromDate: day < range.fromDate ? day : range.fromDate, toDate: day < range.fromDate ? range.fromDate : day };
}
export function rangeQuery(range) {
  const error = rangeError(range);
  if (error) throw new Error(error);
  return new URLSearchParams({ from_date: range.fromDate, to_date: range.toDate });
}
export function monthDays(month) {
  const start = `${month}-01`;
  const first = new Date(`${start}T00:00:00Z`);
  const last = new Date(first);
  last.setUTCMonth(last.getUTCMonth() + 1); last.setUTCDate(0);
  const days = last.getUTCDate();
  return [...Array(first.getUTCDay()).fill(null), ...Array.from({ length: days }, (_, i) => addDays(start, i))];
}
export function shiftMonth(month, count) {
  const date = new Date(`${month}-01T00:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + count);
  return date.toISOString().slice(0, 7);
}
export function rangeLabel(range, today = tradingDate()) {
  if (range.fromDate === range.toDate) {
    if (range.fromDate === today) return 'Today';
    if (range.fromDate === addDays(today, -1)) return 'Yesterday';
  }
  const format = day => new Date(`${day}T00:00:00Z`).toLocaleDateString('en-IN', { timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric' });
  if (!range.fromDate || !range.toDate) return 'Choose dates';
  return range.fromDate === range.toDate ? format(range.fromDate) : `${format(range.fromDate)} – ${format(range.toDate)}`;
}
