import React, { useEffect, useState } from 'react';
import { tradingDate } from './format';
import { supportedIndices } from './indices';

export default function LevelForm({ level, instrument, instrumentOptions = [], live = false, busy, onSave, onCancel }) {
  const available = live ? instrumentOptions : supportedIndices;
  const [symbol, setSymbol] = useState(level?.instrument || instrument || available[0] || '');
  const [levelDate, setLevelDate] = useState(level?.level_date ?? null);
  const [price, setPrice] = useState(level?.price ?? '');
  const [enabled, setEnabled] = useState(level?.enabled ?? true);
  useEffect(() => {
    if (!symbol && available.length) setSymbol(available[0]);
  }, [symbol, available]);
  const choices = [...new Set([...(level?.instrument ? [level.instrument] : []), ...available])];
  return <form className="ms-editor" onSubmit={event => {
    event.preventDefault();
    if (!symbol.trim() || !Number.isFinite(Number(price))) return;
    onSave({ instrument: symbol.trim(), price: Number(price), enabled, ...(levelDate ? { level_date: levelDate } : {}) });
  }}>
    <div className="ms-sectionhead">{level ? 'Edit level' : 'Add level'}</div>
    <div className="ms-fields">
      <label>Instrument<select required value={choices.includes(symbol) ? symbol : ''} disabled={busy || !choices.length} onChange={event => setSymbol(event.target.value)}>
        {!choices.includes(symbol) && <option value="">Select an instrument</option>}
        {choices.map(value => <option key={value} value={value}>{value}</option>)}
      </select></label>
      <label>Trading date (Asia/Kolkata)<input type="date" required value={levelDate ?? tradingDate()} disabled={busy || Boolean(level)} onChange={event => setLevelDate(event.target.value)} /></label>
      <label>Level price<input required type="number" step="any" value={price} onChange={event => setPrice(event.target.value)} /></label>
      <label className="ms-check"><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} />Enabled</label>
    </div>
    {live && supportedIndices.some(index => !instrumentOptions.includes(index)) && <p className="ms-sub">Missing an index? Sync instruments in Settings → Connection to load all available indices, including SENSEX.</p>}
    <footer><button type="button" className="ms-button" disabled={busy} onClick={onCancel}>Cancel</button><button className="ms-button ms-primary" disabled={busy || !symbol || !choices.includes(symbol)}>{busy ? 'Saving…' : 'Save level'}</button></footer>
  </form>;
}
