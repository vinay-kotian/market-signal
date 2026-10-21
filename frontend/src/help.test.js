import test from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { createServer } from 'vite';
import { JSDOM } from 'jsdom';
import { helpRegistry, topics, searchTopics, helpPath, fieldTopic } from './help/registry.js';
import { reasonToHelp, explainDecision, eventReason } from './help/reasons.js';
import { initialPage } from './connectionState.js';

const fact = (model, label) => model.facts.find(item => item.label === label)?.value;
const trade = { strategy_type: 'ATR_FIXED', entry_price: 100, initial_stop_loss: 97, quantity: 10,
  option_atr_at_entry: 4, strategy_config_snapshot: { atr_multiplier: .75, min_pre_entry_candles: 2, risk_reward_ratio: 2 },
  strategy3_entry: { pre_entry_candle_count: 15, atr_sample_count: 14, stop_source: 'ATR', initial_stop: 97, target: 106,
    frozen_strategy_settings: { atr_multiplier: .75, min_pre_entry_candles: 2, risk_reward_ratio: 2 } },
  decision_context: { strategy_selection: { source: 'NEXT_TRADE_OVERRIDE', strategy: 'ATR_FIXED' } } };

test('all registry IDs, related articles and machine-code mappings resolve to deep links', () => {
  assert.equal(new Set(topics.map(t => t.id)).size, topics.length);
  for (const topic of topics) {
    assert.equal(helpPath(topic.id), `/help/${topic.id}`);
    assert.ok(topic.rules.length && topic.summary && topic.category);
    for (const related of topic.related) assert.ok(helpRegistry[related], related);
  }
  for (const [code, entry] of Object.entries(reasonToHelp)) assert.ok(helpRegistry[entry.topicId], code);
  for (const path of ['/help', '/help/atr/minimum-candles', '/help/trades/trailing-stop']) assert.equal(initialPage(path), 'help');
  assert.equal(initialPage('/helpful'), 'dashboard');
  assert.ok(searchTopics('minimum candles').some(t => t.id === 'atr/minimum-candles'));
  assert.ok(searchTopics('trailing', 'Exit strategies').every(t => t.category === 'Exit strategies'));
  assert.equal(searchTopics('zzzz-no-results').length, 0);
  assert.equal(helpPath('__proto__'), '/help/troubleshooting/unknown');
  assert.equal(helpRegistry.constructor, undefined);
  assert.equal(fieldTopic('min_pre_entry_candles'), 'atr/minimum-candles');
  assert.equal(fieldTopic('atr_period', 'ATR_FIXED'), 'atr/fixed-stop');
  assert.equal(fieldTopic('atr_period', 'ATR'), 'atr/wilder');
});

test('recorded strategy values drive deterministic calculations and never read global settings', () => {
  const before = structuredClone(trade);
  const model = explainDecision({ code: 'FIXED_PLAN', trade, currentSettings: { atr_multiplier: 20 } });
  assert.equal(fact(model, 'Completed pre-entry candles'), 15);
  assert.equal(fact(model, 'Minimum required candles'), 2);
  assert.equal(fact(model, 'Frozen initial ATR multiplier'), .75);
  assert.match(model.calculations.join(' '), /100 − \(4 × 0.75\) = 97/);
  assert.match(model.calculations.join(' '), /target = 100 \+ \(100 − 97\) × 2 = 106/);
  assert.deepEqual(trade, before);
  assert.deepEqual(model, explainDecision({ code: 'FIXED_PLAN', trade }));
  assert.equal(fact(explainDecision({ code: 'STRATEGY_SELECTED', trade }), 'Winning override source'), 'NEXT_TRADE_OVERRIDE');
});

test('unrecorded counts, thresholds, override sources and event-time values remain unavailable', () => {
  const old = { ...trade, decision_context: {}, strategy3_entry: { atr_sample_count: 9, stop_source: 'FALLBACK' } };
  const model = explainDecision({ code: 'INSUFFICIENT_PRE_ENTRY_CANDLES', trade: old });
  assert.match(fact(model, 'Completed pre-entry candles'), /Unavailable/);
  assert.notEqual(fact(model, 'Completed pre-entry candles'), 10);
  assert.equal(model.missing, true);
  assert.match(fact(explainDecision({ code: 'STRATEGY_SELECTED', trade: old }), 'Winning override source'), /Unavailable/);
  const trail = explainDecision({ code: 'TRAILING_STOP_UPDATED', trade: { highest_price: 999, current_stop_loss: 900 } });
  assert.match(fact(trail, 'Event effective stop (₹)'), /Unavailable/);
  assert.ok(!trail.facts.some(item => item.value === 900 || item.value === 999));
  const unknown = explainDecision({ code: 'UNDOCUMENTED_BACKEND_CODE', message: 'ATR insufficient candles stop target' });
  assert.equal(unknown.topicId, 'troubleshooting/unknown');
  assert.match(unknown.why, /no documented decision mapping/);
});

test('ATR missing history means skip; Strategy 3 fallback is recorded explicitly', () => {
  const skipped = explainDecision({ code: 'OPTION_ATR_UNAVAILABLE', entry: { status: 'FAILED', decision_context: {
    strategy_type: 'ATR', completed_candle_count: 1, required_candle_count: 14, atr_candle_timeframe: '5minute' } } });
  assert.equal(fact(skipped, 'Completed pre-entry candles'), 1);
  assert.equal(fact(skipped, 'Minimum required candles'), 14);
  assert.match(skipped.why, /does not use Strategy 3/);
  const fallback = explainDecision({ code: 'INSUFFICIENT_PRE_ENTRY_CANDLES', trade: {
    strategy_type: 'ATR_FIXED', entry_price: 100, initial_stop_loss: 80,
    strategy3_entry: { pre_entry_candle_count: 1, stop_source: 'FALLBACK', fallback_reason: 'INSUFFICIENT_PRE_ENTRY_CANDLES',
      frozen_strategy_settings: { min_pre_entry_candles: 2, fallback_sl_pct: 20 } } } });
  assert.equal(fact(fallback, 'Completed pre-entry candles'), 1);
  assert.match(fallback.calculations[0], /fallback stop = 100 × \(1 − 20 \/ 100\) = 80/);
});

test('entry cutoff and signal thresholds come from their decision snapshots', () => {
  const signal = explainDecision({ code: 'MINIMUM_DISTANCE_NOT_MET', signal: { approach_distance: 40,
    decision_context: { settings_snapshot: { minimum_approach_distance_points: 50, minimum_approach_distance_enabled: true } } } });
  assert.equal(fact(signal, 'Minimum approach threshold (points)'), 50);
  const cutoff = explainDecision({ code: 'NEW_TRADE_CUTOFF_REACHED', entry: { status: 'FAILED',
    decision_context: { new_trade_cutoff_time: '15:20:00', execution_timestamp: '2026-10-21T15:21:00+05:30' } } });
  assert.equal(fact(cutoff, 'Applied entry cutoff (IST, exclusive)'), '15:20:00');
  assert.match(fact(cutoff, 'Applied entry start (IST, inclusive)'), /Unavailable/);
});

test('exit reasons and event-time stop values are not inferred from P&L or later outcomes', () => {
  assert.equal(eventReason({ event_type: 'POSITION_CLOSED' }, { realised_pnl: -100 }), 'POSITION_CLOSED');
  assert.equal(eventReason({ event_type: 'TRAILING_STOP_UPDATED' }, { exit_reason: 'MARKET_CLOSE' }), 'TRAILING_STOP_UPDATED');
  assert.equal(eventReason({ event_type: 'TRADE_EXIT', exit_reason: 'SL' }), 'SL');
  const model = explainDecision({ code: 'TRAILING_STOP_UPDATED', trade: { ...trade, current_stop_loss: 900 },
    event: { price: 110, previous_stop: 97, current_stop: 102, highest_price: 112 } });
  assert.equal(fact(model, 'Event effective stop (₹)'), 102);
  const early = explainDecision({ code: 'BREAKEVEN_PROTECTION_ACTIVATED', trade: { ...trade, exit_reason: 'EOD', exit_price: 105 }, event: { event_type: 'BREAKEVEN_PROTECTION_ACTIVATED', price: 110 } });
  assert.equal(fact(early, 'Recorded exit reason'), undefined);
  const close = explainDecision({ code: 'MARKET_CLOSE', trade: { settings_snapshot: { mandatory_exit_before_close_minutes: 3 } } });
  assert.match(close.calculations.join(), /does not establish the exit-time deadline/);
  assert.ok(!close.facts.some(f => f.label.includes('deadline') && f.value === '15:27'));
});

test('live arming observations are distinguished from original historical decisions', () => {
  const model = explainDecision({ code: 'LEVEL_PENDING_ARM', level: { price: 25000, status: 'PENDING_ARM' }, currentPrice: 25020, armDistance: 30 });
  assert.equal(fact(model, 'Current absolute distance (points)'), 20);
  assert.equal(model.facts.find(f => f.label === 'Current arm threshold (points)').kind, 'Current configuration');
  assert.match(model.calculations[0], /not a reconstruction/);
});

async function setup(t, pathname = '/help/atr/minimum-candles') {
  const dom = new JSDOM('<div id="root"></div>', { url: `http://localhost${pathname}` });
  const restore = [];
  for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement, PopStateEvent: dom.window.PopStateEvent, IS_REACT_ACT_ENVIRONMENT: true })) {
    const old = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    restore.push(() => old ? Object.defineProperty(globalThis, name, old) : delete globalThis[name]);
  }
  dom.window.scrollTo = () => {};
  const { createRoot } = await import('react-dom/client');
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  const help = await server.ssrLoadModule('/src/help/ContextHelp.jsx');
  const { default: HelpCenter } = await server.ssrLoadModule('/src/help/HelpCenter.jsx');
  const { TradesTable } = await server.ssrLoadModule('/src/TradesPage.jsx');
  const root = createRoot(document.getElementById('root'));
  t.after(async () => { await act(() => root.unmount()); await server.close(); dom.window.close(); restore.forEach(fn => fn()); });
  const render = async view => { await act(() => root.render(view)); };
  return { ...help, HelpCenter, TradesTable, dom, render };
}

test('context help opens actual values, traps focus, closes on Escape and outside click', async t => {
  const ui = await setup(t); let submitted = 0, parentClicked = 0;
  await ui.render(React.createElement('form', { onSubmit: e => { e.preventDefault(); submitted++; }, onClick: () => parentClicked++ },
    React.createElement('label', null, 'Option enabled', React.createElement('input', { type: 'checkbox' }),
      React.createElement(ui.default, { decision: { code: 'FIXED_PLAN', trade } }))));
  const button = document.querySelector('button');
  button.focus();
  await act(() => button.click());
  const dialog = document.querySelector('[role="dialog"]');
  assert.ok(dialog && dialog.getAttribute('aria-labelledby'));
  assert.match(dialog.textContent, /Recorded/);
  assert.match(dialog.textContent, /100 − \(4 × 0.75\) = 97/);
  assert.equal(document.querySelector('input').checked, false);
  assert.equal(submitted, 0); assert.equal(parentClicked, 0);
  const close = dialog.querySelector('button'), link = dialog.querySelector('a');
  close.focus();
  await act(() => close.dispatchEvent(new ui.dom.window.KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true })));
  assert.equal(document.activeElement, link);
  await act(() => link.dispatchEvent(new ui.dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  assert.equal(document.querySelector('[role="dialog"]'), null);
  assert.equal(document.activeElement, button);
  await act(() => button.click());
  await act(() => document.querySelector('.ms-help-backdrop').click());
  assert.equal(document.querySelector('[role="dialog"]'), null);
  assert.equal(submitted, 0);
});

test('help links navigate directly to the shared article and missing IDs fail safely', async t => {
  const ui = await setup(t, '/trades');
  await ui.render(React.createElement(ui.default, { topicId: 'atr/minimum-candles' }));
  await act(() => document.querySelector('button').click());
  const link = document.querySelector('[role="dialog"] a');
  assert.equal(link.getAttribute('href'), '/help/atr/minimum-candles');
  await act(() => link.click());
  assert.equal(window.location.pathname, '/help/atr/minimum-candles');
  await ui.render(React.createElement(ui.default, { topicId: 'unregistered-topic' }));
  await act(() => document.querySelector('button').click());
  assert.equal(document.querySelector('[role="dialog"] a').getAttribute('href'), '/help/troubleshooting/unknown');
});

test('Help Center supports deep links, searchable articles, category filters and history', async t => {
  const ui = await setup(t);
  await ui.render(React.createElement(ui.HelpCenter));
  assert.match(document.querySelector('article').textContent, /Minimum pre-entry candles/);
  assert.ok(document.querySelector('[aria-label="Article contents"] a[href="#help-rules"]'));
  const input = document.querySelector('input[type="search"]');
  await act(() => {
    Object.getOwnPropertyDescriptor(ui.dom.window.HTMLInputElement.prototype, 'value').set.call(input, 'trailing');
    input.dispatchEvent(new ui.dom.window.Event('input', { bubbles: true }));
  });
  assert.ok(document.querySelector('a[href="/help/trades/trailing-stop"]'));
  await act(() => document.querySelector('a[href="/help/trades/trailing-stop"]').click());
  assert.equal(window.location.pathname, '/help/trades/trailing-stop');
  assert.match(document.querySelector('article h2').textContent, /Trailing/);
  await act(() => { window.history.replaceState({}, '', '/help/not-found'); window.dispatchEvent(new ui.dom.window.PopStateEvent('popstate')); });
  assert.match(document.body.textContent, /topic was not found/);
});

test('trade-table contextual help links use the stored reason and actual trade snapshot', async t => {
  const ui = await setup(t, '/trades');
  await ui.render(React.createElement(ui.TradesTable, { trades: [{ ...trade, trade_id: 1, signal_id: 1, status: 'CLOSED',
    entry_time: '2026-10-21T10:00:00+05:30', exit_reason: 'TARGET', exit_price: 106 }] }));
  const help = document.querySelector('button[aria-label="Why? Strategy 3 target reached"]');
  assert.ok(help);
  await act(() => help.click());
  const dialog = document.querySelector('[role="dialog"]');
  assert.match(dialog.textContent, /TARGET/);
  assert.match(dialog.textContent, /Fixed target/);
  assert.equal(dialog.querySelector('a').getAttribute('href'), '/help/atr/fixed-stop');
});

test('breakeven thresholds use frozen units and trailing candidates remain labelled derived', () => {
  const atrTrade = { strategy_type: 'ATR', entry_price: 100, initial_stop_loss: 94, option_atr_at_entry: 4,
    strategy_config_snapshot: { atr_breakeven_activation_mode: 'R', atr_breakeven_activation_threshold: 2,
      atr_trailing_mode: 'ATR', atr_trailing_multiplier: 2 } };
  const activation = explainDecision({ code: 'BREAKEVEN_PROTECTION_ACTIVATED', trade: atrTrade, event: { price: 112, current_stop: 100 } });
  assert.equal(fact(activation, 'Derived activation premium (₹)'), 112);
  const trail = explainDecision({ code: 'TRAILING_STOP_UPDATED', trade: atrTrade, event: { price: 120, highest_price: 120, current_stop: 112 } });
  assert.equal(fact(trail, 'Derived ATR trailing candidate (₹)'), 112);
  assert.equal(trail.facts.find(f => f.label === 'Derived ATR trailing candidate (₹)').kind, 'Derived');
  const old = explainDecision({ code: 'BREAKEVEN_PROTECTION_ACTIVATED', trade: { strategy_type: 'ATR', entry_price: 100 } });
  assert.equal(fact(old, 'Derived activation premium (₹)'), undefined);
});
