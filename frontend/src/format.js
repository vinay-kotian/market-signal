export const formatPrice = value => value == null ? '—' : value.toLocaleString('en-IN', {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
});

export function levelStatus(level, events) {
  if (!level.enabled) return 'DISABLED';
  if (events === null) return 'UNAVAILABLE';
  return events.some(event => event.level_id === level.id
    && event.instrument === level.instrument && event.level_price === level.price
    && Date.parse(event.triggered_at) >= Date.parse(level.updated_at))
    ? 'TRIGGERED' : 'WAITING';
}
