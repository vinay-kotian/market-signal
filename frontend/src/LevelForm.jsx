import React, { useState } from 'react';

export default function LevelForm({ level, instrument, busy, onSave, onCancel }) {
  const [symbol, setSymbol] = useState(level?.instrument ?? instrument);
  const [price, setPrice] = useState(level?.price ?? '');
  const [enabled, setEnabled] = useState(level?.enabled ?? true);
  return <form className="ms-editor" onSubmit={event => {
    event.preventDefault();
    if (!symbol.trim() || !Number.isFinite(Number(price))) return;
    onSave({ instrument: symbol.trim(), price: Number(price), enabled });
  }}>
    <div className="ms-sectionhead">{level ? 'Edit level' : 'Add level'}</div>
    <div className="ms-fields">
      <label>Instrument<input required value={symbol} onChange={event => setSymbol(event.target.value)} /></label>
      <label>Level price<input required type="number" step="any" value={price} onChange={event => setPrice(event.target.value)} /></label>
      <label className="ms-check"><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} />Enabled</label>
    </div>
    <footer><button type="button" className="ms-button" disabled={busy} onClick={onCancel}>Cancel</button><button className="ms-button ms-primary" disabled={busy}>{busy ? 'Saving…' : 'Save level'}</button></footer>
  </form>;
}
