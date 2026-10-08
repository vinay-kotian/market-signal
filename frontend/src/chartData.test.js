import test from 'node:test';
import assert from 'node:assert/strict';
import { sessionData, eventMarkers, markerTypes, minuteOf, mergeLiveCandles, istEventTime } from './chartData.js';
import { mountCharts } from './chartRuntime.js';
import { applyLiveEvent } from './liveFeed.js';

const day = '2026-09-14';
const time = minuteOf('2026-09-14T09:15:37.123+05:30');
const candle = { time, open: 25000, high: 25020, low: 24990, close: 25010 };
const event = { id: 'entry-1', event_type: 'TRADE_ENTRY', timestamp: '2026-09-14T09:15:37.123+05:30', price: 101.25, trade_id: 1 };
const enabled = Object.fromEntries(Object.keys(markerTypes).map(type => [type, true]));

test('same session grid aligns index and option without filling missing candles', () => {
  const index = sessionData(day, [candle]);
  const option = sessionData(day, [{ ...candle, time: time + 60 }]);
  assert.equal(index.length, 376);
  assert.deepEqual(index.map(row => row.time), option.map(row => row.time));
  assert.deepEqual(index[1], { time: time + 60 });
  assert.deepEqual(option[0], { time });
  assert.equal(index.at(-1).time, Date.parse(`${day}T15:30:00+05:30`) / 1000);
});

test('markers retain exact execution price and independent repeated trades, including candle gaps', () => {
  const later = { ...event, id: 'entry-2', price: 102.75, trade_id: 2 };
  const markers = eventMarkers([event, later], [], enabled, day);
  assert.deepEqual(markers.map(marker => marker.id), ['entry-1', 'entry-2']);
  assert.deepEqual(markers.map(marker => marker.price), [101.25, 102.75]);
  assert.equal(markers[0].time, time);
  assert.equal(markers[0].shape, 'arrowUp');
  assert.equal(event.timestamp, '2026-09-14T09:15:37.123+05:30');
  assert.deepEqual(eventMarkers([event], [], { ...enabled, TRADE_ENTRY: false }, day), []);
  assert.deepEqual(eventMarkers([{ ...event, timestamp: '2026-09-14T08:00:00+05:30' }], [], enabled, day), []);
});

test('minute updates persist every observed minute and isolate historical dates and rollover', () => {
  let state = { prices: {} };
  const update = row => ({ type: 'MARKET_PRICE_UPDATED', timestamp: event.timestamp,
    data: { instrument: 'NIFTY', price: row.close, candle: row } });
  state = applyLiveEvent(state, update(candle));
  state = applyLiveEvent(state, update({ ...candle, close: 25030 }));
  state = applyLiveEvent(state, update({ ...candle, time: time + 60 }));
  assert.equal(state.chartCandles.NIFTY[time].close, 25030);
  assert.equal(Object.values(state.chartCandles.NIFTY).filter(row => row?.time).length, 2);
  assert.deepEqual(mergeLiveCandles([candle], { day: '2026-09-15', [time]: candle }, day, day), [candle]);
  state = applyLiveEvent(state, update({ ...candle, time: time + 86400 }));
  assert.equal(state.chartCandles.NIFTY.day, '2026-09-15');
  assert.equal(state.chartCandles.NIFTY[time], undefined);
  assert.equal(state.chartRevision, 0);
  state = applyLiveEvent(state, { type: 'STOP_UPDATED', data: { trade_id: 1 } });
  assert.equal(state.chartRevision, 1);
});

function fakeLibrary() {
  const charts = [];
  return { charts, CandlestickSeries: 'candle', LineSeries: 'line', LineStyle: { Dashed: 2 },
    createChart(element, options) {
      const scale = { setVisibleLogicalRange(range) { this.range = range; this.callback?.(range); },
        subscribeVisibleLogicalRangeChange(callback) { this.callback = callback; },
        unsubscribeVisibleLogicalRangeChange() { this.callback = null; }, timeToCoordinate() { return 42; } };
      const chart = { options, series: [], timeScale: () => scale,
        addSeries(type, options) { const series = { type, options, priceLines: [], createPriceLine(options) {
            const line = { options, applyOptions(update) { this.options = { ...this.options, ...update }; } };
            this.priceLines.push(line); return line;
          }, setData(data) { this.data = data; },
          applyOptions(update) { this.options = { ...this.options, ...update }; } }; this.series.push(series); return series; },
        subscribeCrosshairMove(callback) { this.crosshair = callback; }, unsubscribeCrosshairMove() { this.crosshair = null; },
        subscribeClick(callback) { this.click = callback; }, unsubscribeClick() { this.click = null; },
        setCrosshairPosition(price, time, series) { this.position = { price, time, series }; this.crosshair?.({ time }); },
        clearCrosshairPosition() { this.position = null; this.crosshair?.({}); },
        remove() { this.removed = true; } };
      charts.push(chart); return chart;
    },
    createSeriesMarkers(series, initial) {
      return series.markers = { data: initial, setMarkers(data) { this.data = data; }, detach() { this.detached = true; } };
    } };
}

test('zoom, crosshair, gaps, marker clicks, filters and disposal use paired charts without recursion', t => {
  const previous = globalThis.document;
  globalThis.document = { createElement: () => ({ style: {}, remove() { this.removed = true; } }) };
  t.after(() => { globalThis.document = previous; });
  const library = fakeLibrary(), elements = [{ appendChild(guide) { this.guide = guide; } }, { appendChild(guide) { this.guide = guide; } }];
  const panels = [ { element: elements[0], symbol: 'NIFTY', candles: [candle], events: [], enabled, trades: [] },
    { element: elements[1], symbol: 'OPTION', candles: [{ ...candle, close: 102 }], events: [event], enabled, trades: [
      { trade_id: 1, entry_time: event.timestamp, exit_time: null, initial_stop_loss: 90 }] } ];
  let hovered, clicked;
  const runtime = mountCharts(library, panels, day, value => { hovered = value; }, value => { clicked = value; });
  const [index, option] = library.charts;
  index.timeScale().setVisibleLogicalRange({ from: 10, to: 30 });
  assert.deepEqual(option.timeScale().range, { from: 10, to: 30 });
  index.crosshair({ time });
  assert.equal(option.position.time, time);
  assert.equal(option.position.price, 102); // Option premium, not the index Y coordinate.
  assert.equal(hovered.candles[0].close, 25010);
  option.crosshair({ time, hoveredInfo: { objectId: event.id } });
  assert.equal(hovered.event, event);
  option.click({ hoveredObjectId: event.id });
  assert.equal(clicked.id, 'entry-1');
  index.crosshair({ time: time + 60 });
  assert.equal(option.position, null);
  assert.equal(elements[1].guide.hidden, false);
  assert.equal(elements[1].guide.style.left, '42px');
  runtime.update(1, { ...panels[1], enabled: { ...enabled, TRADE_ENTRY: false, INITIAL_STOP: false } });
  assert.equal(option.series[1].markers.data.length, 0);
  assert.equal(option.series[0].priceLines[0].options.lineVisible, false);
  runtime.update(1, { ...panels[1], trades: [...panels[1].trades,
    { trade_id: 2, entry_time: event.timestamp, exit_time: event.timestamp, initial_stop_loss: 95 }] });
  assert.equal(option.series[0].priceLines.at(-1).options.price, 95);
  assert.deepEqual(option.timeScale().range, { from: 10, to: 30 });
  runtime.destroy();
  assert.ok(library.charts.every(chart => chart.removed && !chart.crosshair && !chart.click && !chart.timeScale().callback));
});


test('completed broker history beats stale partial ticks while current broker candles keep updating', () => {
  const saved = [{ ...candle, origin: 'ZERODHA_HISTORY' }, { ...candle, time: time + 60, origin: 'ZERODHA_HISTORY' }];
  const live = { day, [time]: { ...candle, close: 999 }, [time + 60]: { ...candle, time: time + 60, close: 25030 } };
  const result = mergeLiveCandles(saved, live, day, day, '2026-09-14T09:16:10+05:30');
  assert.equal(result[0].close, 25010);
  assert.equal(result[1].close, 25030);
  assert.deepEqual(mergeLiveCandles(saved, live, day, '2026-09-15'), saved);
  assert.equal(istEventTime('2026-09-13T18:31:03.123456Z'), '2026-09-14 00:01:03.123456 IST');
});
