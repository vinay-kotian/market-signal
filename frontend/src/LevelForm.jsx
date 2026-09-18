import React, { useEffect, useState } from 'react';
import { tradingDate } from './format';

export default function LevelForm({ level, instrument, instrumentOptions = [], live = false, busy, onSave, onCancel }) {
  const [symbol, setSymbol] = useState(level?.instrument || instrument || instrumentOptions[0] || '');
  const [levelDate, setLevelDate] = useState(level?.level_date ?? null);
  const [price, setPrice] = useState(level?.price ?? '');
  const [enabled, setEnabled] = useState(level?.enabled ?? true);
  useEffect(() => {
    if (!symbol && instrumentOptions.length) setSymbol(instrumentOptions[0]);
  }, [symbol, instrumentOptions]);
  const choices = [...new Set([...(level?.instrument ? [level.instrument] : []), ...instrumentOptions])];
  return <form className="ms-editor" onSubmit={event => {
    event.preventDefault();
    if (!symbol.trim() || !Number.isFinite(Number(price))) return;
    onSave({ instrument: symbol.trim(), price: Number(price), enabled, ...(levelDate ? { level_date: levelDate } : {}) });
  }}>
    <div className="ms-sectionhead">{level ? 'Edit level' : 'Add level'}</div>
    <div className="ms-fields">
      <label>Instrument{live ? <select required value={symbol} disabled={busy || !choices.length} onChange={event => setSymbol(event.target.value)}>
        {!choices.includes(symbol) && <option value="">Select an instrument</option>}
        {choices.map(value => <option key={value} value={value}>{value}</option>)}
      </select> : <><input required list="level-instruments" value={symbol} onChange={event => setSymbol(event.target.value)} /><datalist id="level-instruments">{choices.map(value => <option key={value} value={value} />)}</datalist></>}</label>
      <label>Trading date (Asia/Kolkata)<input type="date" required value={levelDate ?? tradingDate()} disabled={busy || Boolean(level)} onChange={event => setLevelDate(event.target.value)} /></label>
      <label>Level price<input required type="number" step="any" value={price} onChange={event => setPrice(event.target.value)} /></label>
      <label className="ms-check"><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} />Enabled</label>
    </div>
    {live && !instrumentOptions.length && <p className="ms-sub">Sync instruments on the Connection page to load available indices.</p>}
    <footer><button type="button" className="ms-button" disabled={busy} onClick={onCancel}>Cancel</button><button className="ms-button ms-primary" disabled={busy || !symbol || (live && !choices.includes(symbol))}>{busy ? 'Saving…' : 'Save level'}</button></footer>
  </form>;
}
