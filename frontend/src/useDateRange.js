import { useEffect, useState } from 'react';
import { presetRange, rangeError } from './dateRange';

// Presets follow IST midnight; explicitly selected historical dates stay fixed.
export function useDateRange() {
  const [selection, setSelection] = useState(() => ({ range: presetRange('TODAY'), preset: 'TODAY' }));
  useEffect(() => {
    const timer = setInterval(() => setSelection(previous => {
      if (!previous.preset) return previous;
      const range = presetRange(previous.preset);
      return range.fromDate === previous.range.fromDate ? previous : { ...previous, range };
    }), 1000);
    return () => clearInterval(timer);
  }, []);
  function apply(range, preset) {
    if (rangeError(range)) return;
    setSelection(previous => ({ range, preset: preset === 'CUSTOM' ? null : preset ??
      (range.fromDate === previous.range.fromDate && range.toDate === previous.range.toDate ? previous.preset : null) }));
  }
  return [selection.range, apply];
}
