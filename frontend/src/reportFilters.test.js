import test from 'node:test';
import assert from 'node:assert/strict';
import { defaultReportRange, reportRangeError, loadReport } from './reportFilters.js';

const today = { fromDate: '2026-10-03', toDate: '2026-10-03' };

test('Report defaults to today in Kolkata even when the UTC day differs', () => {
  assert.deepEqual(defaultReportRange(new Date('2026-10-02T18:30:00Z')), today);
  assert.deepEqual(defaultReportRange(new Date('2026-10-03T18:29:59.999Z')), today);
  assert.deepEqual(defaultReportRange(new Date('2026-10-03T18:30:00Z')), {
    fromDate: '2026-10-04', toDate: '2026-10-04',
  });
});

test('Invalid or missing dates prevent every API request', async () => {
  for (const range of [{ fromDate: '2026-10-04', toDate: '2026-10-03' },
    { fromDate: '', toDate: today.toDate }, { fromDate: today.fromDate, toDate: '' }]) {
    let requests = 0;
    assert.ok(reportRangeError(range));
    await assert.rejects(loadReport({ ...range, view: 'STRATEGY', page: 1 }, {
      send: async () => { requests++; },
    }), /From Date|To Date/);
    assert.equal(requests, 0);
  }
});

test('Summary, history and bulk IDs share range/view on refresh, pagination and view change', async () => {
  for (const range of [today, { ...today, fromDate: '2026-09-30' }]) {
    for (const [view, page] of [['STRATEGY', 1], ['STRATEGY', 1], ['STRATEGY', 2], ['RAW', 1]]) {
      const urls = [];
      const response = { report: { total_trades: 24 }, history: { total: 24, items: [] }, ids: [1, 2] };
      const result = await loadReport({ ...range, view, page, status: 'CLOSED', instrument: 'BANKNIFTY' }, {
        send: async path => {
          const url = new URL(path, 'http://test'); urls.push(url);
          return url.pathname === '/reports/paper-trading' ? response.report
            : url.pathname === '/trades/history' ? response.history : response.ids;
        },
      });
      assert.equal(urls.length, 3);
      for (const url of urls) {
        assert.equal(url.searchParams.get('from_date'), range.fromDate);
        assert.equal(url.searchParams.get('to_date'), range.toDate);
        assert.equal(url.searchParams.get('view'), view);
        assert.equal(url.searchParams.get('status'), 'CLOSED');
        assert.equal(url.searchParams.get('instrument'), 'BANKNIFTY');
        assert.equal(url.searchParams.get('page'), url.pathname === '/trades/history' ? String(page) : null);
      }
      assert.deepEqual(result, { report: response.report, history: response.history, matchingIds: response.ids });
    }
  }
});

test('Trades uses RAW backend history for single-day and multi-day ranges across refresh and pages', async () => {
  const { loadTradeHistory } = await import('./reportFilters.js');
  for (const range of [today, { ...today, fromDate: '2026-09-30' }]) {
    for (const page of [1, 1, 2]) {
      const rows = { items: [], total: 25, page, page_size: 20 };
      let calls = 0;
      const result = await loadTradeHistory({ ...range, page, instrument: 'NIFTY', status: 'CLOSED' }, {
        send: async path => {
          calls++;
          const url = new URL(path, 'http://test');
          assert.equal(url.pathname, '/trades/history');
          assert.deepEqual(Object.fromEntries(url.searchParams), {
            view: 'RAW', from_date: range.fromDate, to_date: range.toDate,
            instrument: 'NIFTY', status: 'CLOSED', page: String(page), page_size: '20',
          });
          return rows;
        },
      });
      assert.equal(calls, 1);
      assert.equal(result, rows);
    }
  }
});

test('Trades sends no history request for reversed or incomplete ranges', async () => {
  const { loadTradeHistory } = await import('./reportFilters.js');
  for (const range of [{ fromDate: '2026-10-04', toDate: '2026-10-03' },
    { fromDate: '', toDate: '2026-10-03' }, { fromDate: '2026-10-03', toDate: '' }]) {
    let calls = 0;
    await assert.rejects(loadTradeHistory({ ...range, page: 1 }, {
      send: async () => { calls++; },
    }), /From Date|To Date/);
    assert.equal(calls, 0);
  }
});
