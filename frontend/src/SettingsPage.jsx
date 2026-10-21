import ContextHelp from './help/ContextHelp';
import React, { useEffect, useRef, useState } from 'react';
import { request } from './api';
import ConnectionPage from './ConnectionPage';
import TradingTimeSettings from './TradingTimeSettings';
import ExitStrategySettings from './ExitStrategySettings';
import TelegramSettings from './TelegramSettings';

const navigation = [
  { label: 'Workspace', items: [['connection', 'Connection', 'Broker and market data']] },
  { label: 'Trading rules', items: [['trading-time', 'Trading hours', 'Session and entry windows'], ['index-rules', 'Index rules', 'Level arming distances']] },
  { label: 'Exit strategies', items: [['exit-strategy', 'Strategy selection', 'Defaults and overrides'], ['exit-atr', 'ATR strategy', 'Trailing and protection'], ['exit-fixed', 'Strategy 3', 'Fixed stop and target'], ['exit-daily', "Today’s selection", 'Daily and next-trade overrides'], ['exit-legacy', 'Legacy strategy', 'Percentage and progressive']] },
  { label: 'Notifications', items: [['notifications', 'Telegram alerts', 'Delivery and destination']] },
];
const sections = navigation.flatMap(group => group.items);

export default function SettingsPage({ indexes, error, onRefresh, connection, connectionError, feedStatus, lastUiEvent }) {
  const root = useRef(null), mobileNav = useRef(null);
  const [active, setActive] = useState('connection');
  function goTo(id, updateHistory = true) {
    const target = root.current?.querySelector(`[id="${id}"]`);
    if (!target) {
      if (updateHistory) {
        window.history.pushState({}, '', `#${id}`);
        window.dispatchEvent(new Event('hashchange'));
      }
      return false;
    }
    // Open a destination panel before measuring or scrolling to its heading.
    if (target.tagName === 'DETAILS') target.open = true;
    const parent = target.closest('details');
    if (parent) parent.open = true;
    setActive(id);
    if (updateHistory && window.location.hash !== `#${id}`) window.history.pushState({}, '', `#${id}`);
    target.focus({ preventScroll: true });
    target.scrollIntoView({ block: 'start', behavior: 'instant' });
    return true;
  }
  useEffect(() => {
    let frame = null;
    let pending = window.location.hash.slice(1);
    if (!sections.some(([id]) => id === pending)) pending = '';
    const update = () => {
      frame = null;
      if (pending) {
        if (goTo(pending, false)) pending = '';
        else return; // A strategy panel may still be loading.
      }
      const mobileHeight = mobileNav.current?.getBoundingClientRect().height ?? 0;
      const marker = mobileHeight ? mobileHeight + 24 : 48;
      let current = sections[0][0];
      for (const [id] of sections) {
        const node = root.current?.querySelector(`[id="${id}"]`);
        if (node && node.getBoundingClientRect().top <= marker) current = id;
      }
      if (document.documentElement.scrollHeight > window.innerHeight && window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2) current = sections.at(-1)[0];
      setActive(current);
    };
    const schedule = () => { if (frame === null) frame = window.requestAnimationFrame(update); };
    const followHash = () => {
      const id = window.location.hash.slice(1);
      pending = sections.some(([section]) => section === id) ? id : '';
      schedule();
    };
    const observer = new MutationObserver(schedule);
    observer.observe(root.current, { childList: true, subtree: true });
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    window.addEventListener('hashchange', followHash);
    window.addEventListener('popstate', followHash);
    root.current.addEventListener('toggle', schedule, true);
    const container = root.current;
    schedule();
    return () => {
      observer.disconnect();
      if (frame !== null) window.cancelAnimationFrame(frame);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      window.removeEventListener('hashchange', followHash);
      window.removeEventListener('popstate', followHash);
      container.removeEventListener('toggle', schedule, true);
    };
  }, []);
  const activeLabel = sections.find(([id]) => id === active)?.[1];
  return <div className="ms-settings" ref={root}>
    <nav className="ms-settings-nav" aria-label="Settings sections">
      <div className="ms-settings-nav-title">Settings</div>
      <p className="ms-settings-nav-intro">Configure your workspace</p>
      {navigation.map(group => <div className="ms-settings-nav-group" key={group.label}>
        <div className="ms-label">{group.label}</div>
        {group.items.map(([id, label, description]) => <a key={id} href={`#${id}`} aria-current={active === id ? 'location' : undefined}
          onClick={event => { event.preventDefault(); goTo(id); }}>
          <span>{label}</span><small>{description}</small>
        </a>)}
      </div>)}
    </nav>
    <div className="ms-settings-mobile-nav" ref={mobileNav}>
      <label>Settings section<select value={active} onChange={event => goTo(event.target.value)}>
        {navigation.map(group => <optgroup label={group.label} key={group.label}>{group.items.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</optgroup>)}
      </select></label>
    </div>
    <div className="ms-settings-content">
      <div className="ms-settings-intro"><span className="ms-label">Workspace preferences</span><h3>Set up your trading workspace</h3><p>Manage connections, trading rules and alerts. Each section has its own save controls.</p><span className="ms-settings-location">Viewing: {activeLabel}</span></div>
      <section id="connection" aria-labelledby="connection-heading" tabIndex={-1}>
        <h3 id="connection-heading" className="ms-sectionhead">Connection</h3>
        <p className="ms-sub">Connect your broker and check the market data feed.</p>
        <ConnectionPage connection={connection} error={connectionError} onRefresh={onRefresh} feedStatus={feedStatus} lastUiEvent={lastUiEvent} />
      </section>
      <div id="trading-time" className="ms-settings-card" tabIndex={-1}><TradingTimeSettings /></div>
      <section id="index-rules" aria-label="Index Rules" tabIndex={-1}>
        <h3 className="ms-sectionhead">Index Rules</h3>
        <p className="ms-sub">Initial arm distance is the minimum distance between the current index price and the configured level. It is checked on create, edit, and while pending. Changing this setting preserves active and disarmed states.</p>
        {error && <p role="alert">{error} <button onClick={onRefresh}>Retry</button></p>}
        {!indexes && !error && <p>Loading settings…</p>}
        <div className="ms-index-rules">{(indexes ?? []).map(index => <IndexRule key={`${index.instrument}-${index.updated_at}`} index={index} onRefresh={onRefresh} />)}</div>
      </section>
      <div className="ms-settings-card"><ExitStrategySettings /></div>
      <div id="notifications" className="ms-settings-card" tabIndex={-1}><TelegramSettings /></div>
    </div>
  </div>;
}

function IndexRule({ index, onRefresh }) {
  const [distance, setDistance] = useState(index.initial_arm_distance_points);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  async function save(event) {
    event.preventDefault(); setBusy(true); setMessage('');
    try {
      await request(`/settings/indexes/${index.instrument}`, { method: 'PUT', body: JSON.stringify({ initial_arm_distance_points: Number(distance) }) });
      setMessage('Saved'); await onRefresh();
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  return <form className="ms-index-rule" onSubmit={save}>
    <div className="ms-index-name">{index.instrument}</div>
    <label>Initial Arm Distance · points<ContextHelp topicId="signals/arm-distance" /><input aria-label={`${index.instrument} Initial Arm Distance`} type="number" min="0" step="any" required value={distance} disabled={busy} onChange={event => setDistance(event.target.value)} /></label>
    <button className="ms-button" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button><span className="ms-index-message" role="status">{message}</span>
  </form>;
}
