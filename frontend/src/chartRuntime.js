import { sessionData, eventMarkers, istTime } from './chartData.js';

// The runtime is lazy and injectable so interaction tests exercise both chart
// subscriptions without a canvas or a second market-data connection.
export function mountCharts(library, panels, day, onHover, onSelect) {
  const { createChart, CandlestickSeries, LineSeries, createSeriesMarkers, LineStyle } = library;
  let synchronizing = false;
  const instances = panels.map(panel => {
    const chart = createChart(panel.element, {
      autoSize: true, height: 290,
      layout: { background: { color: '#ffffff' }, textColor: '#475569', attributionLogo: true },
      grid: { vertLines: { color: '#f1f5f9' }, horzLines: { color: '#f1f5f9' } },
      rightPriceScale: { minimumWidth: 82, scaleMargins: { top: 0.12, bottom: 0.12 } },
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: time => istTime(time * 1000).slice(0, 5) },
      localization: { timeFormatter: time => `${day} ${istTime(time * 1000)} IST` },
      crosshair: { mode: 0 },
    });
    const series = chart.addSeries(CandlestickSeries, { upColor: '#16a34a', downColor: '#dc2626', borderVisible: false,
      wickUpColor: '#16a34a', wickDownColor: '#dc2626' });
    series.setData(sessionData(day, panel.candles));
    // Actual event prices can be shown in candle gaps, without inventing OHLC.
    const anchors = chart.addSeries(LineSeries, { lineVisible: false, pointMarkersVisible: false,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    const points = eventMarkers(panel.events, panel.candles, panel.enabled, day);
    anchors.setData([...new Map(points.map(marker => [marker.time, { time: marker.time, value: marker.price }])).values()]);
    const markers = createSeriesMarkers(anchors, points);
    const stops = [];
    for (const trade of panel.trades ?? []) {
      const line = series.createPriceLine({ price: trade.initial_stop_loss, color: '#dc2626',
        lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false,
        title: `#${trade.trade_id} initial SL`, lineVisible: panel.enabled.INITIAL_STOP });
      stops.push({ line, trade_id: trade.trade_id });
    }
    const guide = document.createElement('div');
    guide.className = 'ms-chart-crosshair'; guide.hidden = true; panel.element.appendChild(guide);
    return { chart, series, anchors, markers, stops, guide, panel };
  });

  for (const source of instances) {
    source.rangeChanged = range => {
      if (synchronizing || !range) return;
      synchronizing = true;
      try { for (const target of instances) if (target !== source) target.chart.timeScale().setVisibleLogicalRange(range); }
      finally { synchronizing = false; }
    };
    source.crosshairChanged = param => {
      if (synchronizing) return;
      source.guide.hidden = true;
      synchronizing = true;
      try {
        const id = param.hoveredInfo?.objectId ?? param.hoveredObjectId;
        onHover({ time: param.time, event: source.panel.events.find(event => event.id === id),
          candles: instances.map(instance => instance.panel.candles.find(row => row.time === param.time)) });
        for (const target of instances) if (target !== source) {
          const candle = target.panel.candles.find(row => row.time === param.time);
          target.guide.hidden = true;
          if (param.time == null) target.chart.clearCrosshairPosition();
          else if (candle) target.chart.setCrosshairPosition(candle.close, param.time, target.series);
          else {
            target.chart.clearCrosshairPosition();
            // Show the same time in an unobserved gap without implying a price.
            const x = target.chart.timeScale().timeToCoordinate(param.time);
            if (x != null) { target.guide.style.left = `${x}px`; target.guide.hidden = false; }
          }
        }
      } finally { synchronizing = false; }
    };
    source.clicked = param => {
      const id = param.hoveredInfo?.objectId ?? param.hoveredObjectId;
      const event = source.panel.events.find(event => event.id === id);
      if (event) onSelect(event);
    };
    source.chart.timeScale().subscribeVisibleLogicalRangeChange(source.rangeChanged);
    source.chart.subscribeCrosshairMove(source.crosshairChanged);
    source.chart.subscribeClick(source.clicked);
  }
  instances[0]?.chart.timeScale().setVisibleLogicalRange({ from: 0, to: 375 });
  return {
    update(index, panel) {
      const instance = instances[index];
      if (!instance) return;
      instance.panel = { ...instance.panel, ...panel };
      instance.series.setData(sessionData(day, instance.panel.candles));
      const points = eventMarkers(instance.panel.events, instance.panel.candles, instance.panel.enabled, day);
      instance.anchors.setData([...new Map(points.map(marker => [marker.time, { time: marker.time, value: marker.price }])).values()]);
      instance.markers.setMarkers(points);
      for (const trade of instance.panel.trades ?? []) {
        if (!instance.stops.some(stop => stop.trade_id === trade.trade_id)) {
          const line = instance.series.createPriceLine({ price: trade.initial_stop_loss, color: '#dc2626',
            lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false,
            title: `#${trade.trade_id} initial SL`, lineVisible: instance.panel.enabled.INITIAL_STOP });
          instance.stops.push({ line, trade_id: trade.trade_id });
        }
      }
      for (const stop of instance.stops) {
        stop.line.applyOptions({ lineVisible: Boolean(instance.panel.enabled.INITIAL_STOP &&
          instance.panel.trades?.some(trade => trade.trade_id === stop.trade_id)) });
      }
    },
    destroy() {
      for (const instance of instances) {
        instance.chart.timeScale().unsubscribeVisibleLogicalRangeChange(instance.rangeChanged);
        instance.chart.unsubscribeCrosshairMove(instance.crosshairChanged);
        instance.chart.unsubscribeClick(instance.clicked);
        instance.markers.detach(); instance.chart.remove(); instance.guide.remove();
      }
    },
  };
}
