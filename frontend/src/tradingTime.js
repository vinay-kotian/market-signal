const minuteFields = ['entry_block_after_open_minutes', 'entry_block_before_close_minutes', 'mandatory_exit_before_close_minutes'];

function seconds(value) {
  if (!/^\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(value ?? '')) return NaN;
  const [hours, minutes, rest = 0] = value.split(':').map(Number);
  return hours < 24 && minutes < 60 && rest < 60 ? hours * 3600 + minutes * 60 + rest : NaN;
}
function formatTime(value) {
  const total = Math.round(value);
  const hour = String(Math.floor(total / 3600)).padStart(2, '0');
  const minute = String(Math.floor(total % 3600 / 60)).padStart(2, '0');
  const second = total % 60;
  return `${hour}:${minute}${second ? `:${String(second).padStart(2, '0')}` : ''}`;
}

// This is a display preview only. The shared backend rules enforce trading times.
export function tradingTimePreview(configuration) {
  const open = seconds(configuration.market_open_time), close = seconds(configuration.market_close_time);
  if (!Number.isFinite(open) || !Number.isFinite(close)) return { error: 'Choose valid market opening and closing times.' };
  if (open >= close) return { error: 'Market opening time must be earlier than closing time.' };
  for (const field of minuteFields) {
    const value = configuration[field];
    if (value === '' || value == null || !Number.isFinite(Number(value)) || Number(value) < 0) return { error: 'Entry buffers must be non-negative numbers, and mandatory exit minutes must be positive.' };
  }
  const after = Number(configuration.entry_block_after_open_minutes) * 60;
  const before = Number(configuration.entry_block_before_close_minutes) * 60;
  const exit = Number(configuration.mandatory_exit_before_close_minutes) * 60;
  if (after + before >= close - open) return { error: 'Entry buffers must leave a positive entry window.' };
  if (exit <= 0 || exit >= close - open) return { error: 'Mandatory exit must occur after market open and before market close.' };
  if (exit > before) return { error: 'Mandatory exit must not start before the entry cutoff.' };
  return { error: '', entryFrom: formatTime(open + after), entryUntil: formatTime(close - before), exitStarts: formatTime(close - exit) };
}
