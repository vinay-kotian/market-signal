import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { authenticationStatus, initialPage } from './connectionState.js';

test('callback path opens Settings; auth errors are not connected', () => {
  assert.equal(initialPage('/connection'), 'settings');
  assert.equal(initialPage('/'), 'dashboard');
  assert.equal(authenticationStatus(null), 'NOT_CONNECTED');
  assert.equal(authenticationStatus({ auth_status: 'AUTH_REQUIRED' }), 'AUTH_REQUIRED');
  assert.equal(authenticationStatus({ auth_status: 'CONNECTED' }, 'Request failed'), 'ERROR');
});

test('Connection renders one-click login and enables sync only after authentication', async () => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { default: ConnectionPage } = await server.ssrLoadModule('/src/ConnectionPage.jsx');
    const base = { market_data_mode: 'ZERODHA', login_url: 'http://127.0.0.1:8000/zerodha/login', connection_status: 'SYNC_REQUIRED' };
    const render = auth_status => renderToStaticMarkup(React.createElement(ConnectionPage, { connection: { ...base, auth_status }, onRefresh() {} }));
    const connected = render('CONNECTED');
    assert.match(connected, /Zerodha session connected/);
    assert.match(connected, /href="http:\/\/127.0.0.1:8000\/zerodha\/login"/);
    assert.match(connected, /<button class="ms-button">Sync instruments<\/button>/);
    assert.doesNotMatch(connected, /request_token|Request token|type="password"/);
    assert.match(render('AUTH_REQUIRED'), /<button[^>]*disabled=""[^>]*>Sync instruments/);
    assert.match(render('ERROR'), /Zerodha login could not be completed/);
    const simulated = renderToStaticMarkup(React.createElement(ConnectionPage, {
      connection: { ...base, market_data_mode: 'SIMULATED', auth_status: 'NOT_CONNECTED' }, onRefresh() {},
    }));
    assert.match(simulated, /<button[^>]*disabled=""[^>]*>Connect Zerodha/);
    assert.match(simulated, /<button[^>]*disabled=""[^>]*>Sync instruments/);
    assert.match(simulated, /Zerodha controls are disabled while simulated prices are active/);
  } finally { await server.close(); }
});


test('new live level automatically selects the first synced instrument', async () => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { default: LevelForm } = await server.ssrLoadModule('/src/LevelForm.jsx');
    const html = renderToStaticMarkup(React.createElement(LevelForm, {
      instrument: '', instrumentOptions: ['NIFTY', 'BANKNIFTY', 'SENSEX'], live: true,
    }));
    assert.match(html, /<option value="NIFTY" selected="">NIFTY/);
    assert.match(html, /<option value="BANKNIFTY">BANKNIFTY/);
    assert.match(html, /<option value="SENSEX">SENSEX/);
    const simulated = renderToStaticMarkup(React.createElement(LevelForm, {
      instrument: 'NIFTY', instrumentOptions: ['NIFTY', 'BANKNIFTY'], live: false,
    }));
    assert.match(simulated, /<select/);
    assert.match(simulated, /<option value="SENSEX">SENSEX/);
    assert.doesNotMatch(simulated, /<datalist/);
  } finally { await server.close(); }
});

test('Settings renders separate per-index distance inputs', async () => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { default: SettingsPage } = await server.ssrLoadModule('/src/SettingsPage.jsx');
    const html = renderToStaticMarkup(React.createElement(SettingsPage, {
      indexes: [{ instrument: 'NIFTY', initial_arm_distance_points: 30, updated_at: 'a' },
        { instrument: 'BANKNIFTY', initial_arm_distance_points: 50, updated_at: 'b' },
        { instrument: 'SENSEX', initial_arm_distance_points: 60, updated_at: 'c' }],
      onRefresh() {},
    }));
    assert.match(html, /NIFTY Initial Arm Distance/);
    assert.match(html, /BANKNIFTY Initial Arm Distance/);
    assert.match(html, /SENSEX Initial Arm Distance/);
    assert.match(html, /value="60"/);
    assert.match(html, /value="30"/);
    assert.match(html, /value="50"/);
    assert.match(html, /id="connection"/);
    assert.match(html, /Market data connection/);
    assert.equal(initialPage('/settings'), 'settings');
  } finally { await server.close(); }
});

test('Backtest keeps index choices and adds historical date and multiple levels', async () => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    for (const file of ['BacktestPage', 'PaperReportPage']) {
      const { default: Page } = await server.ssrLoadModule(`/src/${file}.jsx`);
      const html = renderToStaticMarkup(React.createElement(Page));
      assert.match(html, /<option[^>]*>SENSEX<\/option>|<option value="SENSEX"/);
      if (file === 'BacktestPage') {
        assert.match(html, /type="date"/);
        assert.match(html, /<textarea/);
        assert.match(html, /Historical archive/);
      }
      assert.match(html, /NIFTY/);
      assert.match(html, /BANKNIFTY/);
    }
  } finally { await server.close(); }
});

test('progressive trades show profit protection without legacy breakeven status', async () => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { TradesTable } = await server.ssrLoadModule('/src/TradesPage.jsx');
    const base = { trade_id: 1, status: 'OPEN', entry_time: '2026-09-14T10:00:00+05:30',
      settings_snapshot: { stop_strategy: 'PROGRESSIVE' }, profit_lock_activated: true,
      trailing_pct: 9, trailing_step: 1, breakeven_protection_enabled: true };
    const render = trade => renderToStaticMarkup(React.createElement(TradesTable, { trades: [trade] }));
    assert.match(render(base), /Profit locked · Trail 9% · Step 1/);
    assert.doesNotMatch(render(base), /Breakeven:/);
    assert.match(render({ ...base, profit_lock_activated: false }), /Awaiting profit trigger/);
    assert.match(render({ ...base, settings_snapshot: {} }), /Breakeven: Waiting/);
  } finally { await server.close(); }
});

test('Report renders today’s Kolkata date range above the performance summary', async t => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { default: Report } = await server.ssrLoadModule('/src/PaperReportPage.jsx');
    t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-10-02T19:00:00Z') });
    const html = renderToStaticMarkup(React.createElement(Report));
    assert.match(html, /From Date<input[^>]+value="2026-10-03"/);
    assert.match(html, /To Date<input[^>]+value="2026-10-03"/);
    assert.ok(html.indexOf('Report view') < html.indexOf('From Date'));
    assert.ok(html.indexOf('To Date') < html.indexOf('Performance Summary'));
    assert.match(html, /selected report view and date range/);
    assert.doesNotMatch(html, /Summary metrics cover all dates/);
  } finally { t.mock.timers.reset(); await server.close(); }
});

test('Trades defaults to today in Kolkata and places shared date controls above the list', async t => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { default: Trades } = await server.ssrLoadModule('/src/TradesPage.jsx');
    const { default: DateRangeFields } = await server.ssrLoadModule('/src/DateRangeFields.jsx');
    t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-10-02T19:00:00Z') });
    const html = renderToStaticMarkup(React.createElement(Trades));
    assert.match(html, /From Date<input[^>]+value="2026-10-03"/);
    assert.match(html, /To Date<input[^>]+value="2026-10-03"/);
    assert.ok(html.indexOf('From Date') < html.indexOf('Loading trades'));
    assert.doesNotMatch(html, /latest 100/);
    const invalid = renderToStaticMarkup(React.createElement(DateRangeFields, {
      range: { fromDate: '2026-10-04', toDate: '2026-10-03' }, onChange() {},
    }));
    assert.match(invalid, /role="alert">From Date cannot be after To Date/);
    assert.match(invalid, /aria-invalid="true"/);
  } finally { t.mock.timers.reset(); await server.close(); }
});


test('Backtest renders saved summary, actual fill times, and a selected trade timeline', async () => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { BacktestResults } = await server.ssrLoadModule('/src/BacktestPage.jsx');
    const result = { id: 'test-run', status: 'COMPLETED', instrument: 'BANKNIFTY', trading_date: '2026-09-14',
      data_source: 'TEST_ARCHIVE', total_trades: 1, wins: 1, losses: 0, win_rate: 100,
      gross_pnl: 300, profit_factor: null, max_drawdown: 0, trades: [{ trade_id: 1,
        trigger_level: 60000, direction: 'FROM_ABOVE', option_symbol: 'TEST-OPTION',
        entry_price: 200, exit_price: 210, quantity: 30, realised_pnl: 300,
        realised_pnl_percentage: 5, signal_timestamp: '2026-09-14T04:31:00Z',
        entry_time: '2026-09-14T04:31:01Z', exit_reason: 'MARKET_CLOSING_EXIT' }],
      signals: [], option_selections: [], entry_results: [], timeline: [
        { id: 1, event_type: 'MANDATORY_EXIT', timestamp: '2026-09-14T15:25:00+05:30', trade_id: 1,
          payload: { reason: 'Awaiting option quote', level: 60000 } },
        { id: 2, event_type: 'UNRELATED_EVENT', timestamp: '2026-09-14T15:26:00+05:30', trade_id: 2, payload: {} }],
    };
    const html = renderToStaticMarkup(React.createElement(BacktestResults, { result, selectedTrade: '1', setSelectedTrade() {} }));
    assert.match(html, /Max Drawdown/);
    assert.match(html, /Profit Factor/);
    assert.match(html, /10:01:00/);
    assert.match(html, /10:01:01/);
    assert.match(html, /MANDATORY_EXIT/);
    assert.doesNotMatch(html, /UNRELATED_EVENT/);
    assert.match(html, /Costs are not modelled/);
  } finally { await server.close(); }
});


const active = { instrument: 'NIFTY', option_symbol: 'NIFTY-25050-PE', strike: 25050,
  expiry: '2026-09-21', option_type: 'PE', status: 'ACTIVE', trade_id: 1, trade_mode: 'PAPER',
  watchlist_date: '2026-09-14', entry_price: 100, current_ltp: 120,
  change_from_entry_percentage: 20, unrealized_pnl_percentage: 20, realised_pnl_percentage: null };

async function withModule(run) {
  const server = await createServer({ configFile: false, optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try { await run(await server.ssrLoadModule('/src/OptionWatchlist.jsx')); }
  finally { await server.close(); }
}

test('active option renders metadata, entry/LTP, percentages and highlight without removal', async () => {
  await withModule(({ default: Options }) => {
    const html = renderToStaticMarkup(React.createElement(Options, { items: [active], today: '2026-09-14' }));
    for (const text of ['NIFTY PE', 'NIFTY-25050-PE', '25,050.00', '2026-09-21', 'Entry', 'LTP', 'Change from entry', 'Unrealized P&amp;L', '+20.00%', 'ACTIVE']) assert.ok(html.includes(text), text);
    assert.match(html, /ms-option-active/);
    assert.doesNotMatch(html, /Remove closed option/);
  });
});

test('closed option renders final realised return separately from changing LTP and allows removal', async () => {
  await withModule(({ default: Options }) => {
    const closed = { ...active, status: 'CLOSED', current_ltp: 130, change_from_entry_percentage: 30,
      unrealized_pnl_percentage: null, realised_pnl_percentage: 8 };
    const html = renderToStaticMarkup(React.createElement(Options, { items: [closed], today: '2026-09-14', onRemove() {} }));
    assert.match(html, /Realized P&amp;L/);
    assert.match(html, /\+8.00%/);
    assert.match(html, /\+30.00%/);
    assert.match(html, /Remove closed option NIFTY-25050-PE/);
    assert.doesNotMatch(html, /ms-option-active/);
  });
});

test('day rollover hides previous closed rows, retains active rows, and search uses contract metadata', async () => {
  await withModule(({ visibleOptionWatchlist }) => {
    const closed = { ...active, option_symbol: 'BANKNIFTY-59900-CE', instrument: 'BANKNIFTY',
      strike: 59900, option_type: 'CE', status: 'CLOSED' };
    assert.equal(visibleOptionWatchlist([active, closed], '2026-09-14').length, 2);
    assert.deepEqual(visibleOptionWatchlist([active, closed], '2026-09-15'), [active]);
    assert.deepEqual(visibleOptionWatchlist([active, closed], '2026-09-14', '59900'), [closed]);
    assert.deepEqual(visibleOptionWatchlist([active, closed], '2026-09-14', 'banknifty'), [closed]);
    assert.deepEqual(visibleOptionWatchlist(null, '2026-09-14'), []);
  });
});

test('missing LTP remains unknown and loading/errors are visible', async () => {
  await withModule(({ default: Options }) => {
    const render = props => renderToStaticMarkup(React.createElement(Options, { today: '2026-09-14', ...props }));
    const html = render({ items: [{ ...active, current_ltp: null, change_from_entry_percentage: null, unrealized_pnl_percentage: null }] });
    assert.match(html, /—/);
    assert.doesNotMatch(html, /\+20.00%/);
    assert.match(render({ items: null }), /Loading options/);
    assert.match(render({ items: null, error: 'Watchlist unavailable' }), /role="alert"/);
  });
});

test('Instrument Details stays under Dashboard with Kolkata date, filters and exact execution tooltip', async t => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { default: Details, EventDetails } = await server.ssrLoadModule('/src/InstrumentDetails.jsx');
    t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-10-02T19:00:00Z') });
    const html = renderToStaticMarkup(React.createElement(Details, { symbol: 'SENSEX', onBack() {} }));
    assert.match(html, /Back to Dashboard/);
    assert.match(html, /SENSEX · Instrument Details/);
    assert.match(html, /value="2026-10-03"/);
    assert.match(html, /Loading chart data/);
    assert.match(html, /Level touch \/ cross/);
    assert.match(html, /Trailing stop updated/);
    assert.match(html, /checked=""/);
    const execution = renderToStaticMarkup(React.createElement(EventDetails, { tooltip: true, event: {
      id: 'exit-2', event_type: 'TRADE_EXIT', timestamp: '2026-09-14T04:31:37.123Z',
      entry_time: '2026-09-14T04:30:03Z', price: 108, trade_id: 2, signal_id: 3,
      direction: 'FROM_BELOW', level: 25000, index_price: 25001,
      option_symbol: 'NIFTY-25050-PE', option_type: 'PE', strike: 25050, expiry: '2026-09-21',
      quantity: 10, realised_pnl: 80, realised_pnl_percentage: 8,
      duration_seconds: 94.123, exit_reason: 'TRAILING_STOP_LOSS', previous_stop: 100, current_stop: 108,
    } }));
    for (const text of ['role="tooltip"', '10:01:37', 'NIFTY-25050-PE', 'TRAILING_STOP_LOSS', 'Realized P&amp;L (₹)', 'Previous stop', 'Updated stop', 'Signal ID']) assert.ok(execution.includes(text), text);
    const { default: Options } = await server.ssrLoadModule('/src/OptionWatchlist.jsx');
    assert.match(renderToStaticMarkup(React.createElement(Options, { items: [active], today: '2026-09-14', onOpen() {} })), /Open NIFTY-25050-PE Instrument Details/);
  } finally { t.mock.timers.reset(); await server.close(); }
});
