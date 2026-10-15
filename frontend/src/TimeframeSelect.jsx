import React, { useEffect, useState } from 'react';
import { request } from './api';

export default function TimeframeSelect({ value, onChange, disabled, filter = false }) {
  const [options, setOptions] = useState(['5m', '15m', '1h', '1d']);
  useEffect(() => {
    const controller = new AbortController();
    request('/levels/timeframes', { signal: controller.signal })
      .then(values => { if (Array.isArray(values) && !controller.signal.aborted) setOptions(values); })
      .catch(() => {});
    return () => controller.abort();
  }, []);
  const choices = [...new Set([...options, ...(value && value !== 'UNKNOWN' ? [value] : [])])];
  return <label>Timeframe<select value={value ?? ''} disabled={disabled} onChange={event => onChange(event.target.value)}>
    <option value="">{filter ? 'All timeframes' : 'Not recorded'}</option>
    {filter && <option value="UNKNOWN">Not recorded</option>}
    {choices.map(option => <option key={option} value={option}>{option}</option>)}
  </select></label>;
}
