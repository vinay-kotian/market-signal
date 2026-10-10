import React, { useEffect, useLayoutEffect, useId, useRef, useState } from 'react';
import { datePopoverPosition } from './datePopover';
import { tradingDate } from './format';
import { addDays, monthDays, presetRange, rangeError, rangeLabel, selectDay, shiftMonth } from './dateRange';

export default function DateRangeFilter({ range, onChange, onApply, singleDay = false, disabled = false, label = '' }) {
  const [open, setOpen] = useState(false), [draft, setDraft] = useState(range);
  const initialMonth = rangeError(range) ? tradingDate().slice(0, 7) : range.fromDate.slice(0, 7);
  const [month, setMonth] = useState(initialMonth);
  const [position, setPosition] = useState({ left: 12, top: 12 });
  const [draftPreset, setDraftPreset] = useState(null);
  const [selectingEnd, setSelectingEnd] = useState(false);
  const root = useRef(null), trigger = useRef(null), dialog = useRef(null);
  const id = useId(), today = tradingDate(), error = rangeError(draft, today);
  function close() { setOpen(false); trigger.current?.focus(); }
  useEffect(() => {
    if (!open) return;
    dialog.current?.querySelector('button')?.focus();
    const outside = event => { if (!root.current?.contains(event.target)) setOpen(false); };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);
  useLayoutEffect(() => {
    if (!open) return;
    function updatePosition() {
      setPosition(datePopoverPosition(trigger.current.getBoundingClientRect(), {
        width: dialog.current.offsetWidth, height: dialog.current.scrollHeight,
      }, { width: window.innerWidth, height: window.innerHeight }));
    }
    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [open, month, error]);
  function change(next) { setDraft(next); onChange?.(next); }
  function preset(value) { const next = presetRange(value); change(next); setMonth(next.fromDate.slice(0, 7)); setSelectingEnd(false); setDraftPreset(value); }
  function choose(day) {
    setDraftPreset('CUSTOM');
    change(selectDay(draft, day, selectingEnd, singleDay));
    setSelectingEnd(!singleDay && !selectingEnd);
  }
  function keyboard(event) {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key === 'Tab') {
      const buttons = [...dialog.current.querySelectorAll('button:not(:disabled)')].filter(node => node.getClientRects().length);
      const first = buttons[0], last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }
  return <div className="ms-date-filter" ref={root}>
    {label && <span className="ms-date-label">{label}</span>}
    <button type="button" className="ms-button" ref={trigger} aria-label={label ? `${label}: ${rangeLabel(range, today)}` : undefined} disabled={disabled} aria-haspopup="dialog" aria-expanded={open} aria-controls={id} onClick={() => {
      if (open) { close(); return; }
      setDraft(range); setMonth(initialMonth); setSelectingEnd(false); setDraftPreset(null); setOpen(true);
    }}>{rangeLabel(range, today)} ▾</button>
    {open && <div id={id} ref={dialog} className="ms-date-popover" style={position} role="dialog" aria-label={singleDay ? 'Choose trading date' : 'Choose date range'} onKeyDown={keyboard}>
      <div className="ms-date-presets">{['TODAY', 'YESTERDAY'].map(value => <button className="ms-button" type="button" key={value} aria-pressed={draft.fromDate === presetRange(value).fromDate && draft.toDate === draft.fromDate} onClick={() => preset(value)}>{value === 'TODAY' ? 'Today' : 'Yesterday'}</button>)}<button className="ms-button" type="button" onClick={() => { setSelectingEnd(false); dialog.current.querySelector('[data-day]:not(:disabled)')?.focus(); }}>Custom Range</button></div>
      <p className="ms-sub" role="status">{singleDay ? 'Select a day' : selectingEnd ? 'Select the end date' : 'Select the start date'} · Asia/Kolkata</p>
      <div className="ms-date-navigation"><button type="button" className="ms-link" aria-label="Previous month" onClick={() => setMonth(shiftMonth(month, -1))}>←</button><button type="button" className="ms-link" aria-label="Next month" disabled={month >= today.slice(0, 7)} onClick={() => setMonth(shiftMonth(month, 1))}>→</button></div>
      <div className="ms-date-months">{[month, shiftMonth(month, 1)].map((value, index) => <section key={value} className={index ? 'ms-date-second' : ''} aria-label={value}>
        <strong>{new Date(`${value}-01T00:00:00Z`).toLocaleDateString('en-IN', { timeZone: 'UTC', month: 'long', year: 'numeric' })}</strong>
        <div className="ms-date-grid">{['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].map(day => <span key={day}>{day}</span>)}
          {monthDays(value).map((day, i) => day ? <button type="button" key={day} data-day={day} disabled={day > today} aria-label={day} aria-pressed={day === draft.fromDate || day === draft.toDate} className={day === draft.fromDate || day === draft.toDate ? 'ms-date-selected' : day > draft.fromDate && day < draft.toDate ? 'ms-date-between' : ''} onClick={() => choose(day)} onKeyDown={event => {
            const offset = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[event.key];
            if (!offset) return;
            event.preventDefault(); const next = addDays(day, offset);
            if (next > today) return;
            if (!dialog.current.querySelector(`[data-day="${next}"]`)?.getClientRects().length) setMonth(next.slice(0, 7));
            requestAnimationFrame(() => dialog.current?.querySelector(`[data-day="${next}"]`)?.focus());
          }}>{Number(day.slice(-2))}</button> : <span key={`blank-${i}`} />)}
        </div>
      </section>)}</div>
      <p className="ms-sub">Selected: {draft.fromDate || '—'}{!singleDay && ` – ${draft.toDate || '—'}`}</p>
      {error && <p className="ms-error" role="alert">{error}</p>}
      <div className="ms-date-footer"><button type="button" className="ms-link" onClick={() => preset('TODAY')}>Reset</button><button type="button" className="ms-link" onClick={close}>Cancel</button><button type="button" className="ms-button ms-primary" disabled={Boolean(error) || disabled} onClick={() => { onApply?.(draft, draftPreset); close(); }}>Apply</button></div>
    </div>}
  </div>;
}
