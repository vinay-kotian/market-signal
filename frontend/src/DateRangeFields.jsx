import React, { useId } from 'react';
import { reportRangeError } from './reportFilters';

export default function DateRangeFields({ range, onChange, disabled = false }) {
  const errorId = useId();
  const validation = reportRangeError(range);
  return <fieldset className="ms-trade-filters ms-report-date-range" disabled={disabled}>
    <legend>Date range · Asia/Kolkata</legend>
    <div className="ms-report-filters">
      <label>From Date<input type="date" required value={range.fromDate} aria-invalid={Boolean(validation)} aria-describedby={validation ? errorId : undefined} onChange={event => onChange('fromDate', event.target.value)} /></label>
      <label>To Date<input type="date" required value={range.toDate} aria-invalid={Boolean(validation)} aria-describedby={validation ? errorId : undefined} onChange={event => onChange('toDate', event.target.value)} /></label>
    </div>
    {validation && <p id={errorId} className="ms-error" role="alert">{validation}</p>}
  </fieldset>;
}
