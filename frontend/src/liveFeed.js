// One transport per application mount, shared by every page and instrument.
export function marketSocketUrl(location) {
  return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/market`;
}

export function createLiveFeed({ url, loadSnapshot, onSnapshot, onEvent, onStatus,
  WebSocketClass = globalThis.WebSocket, schedule = setTimeout, cancel = clearTimeout }) {
  let socket, retry, watchdog, stopped = false, attempt = 0, generation = 0;
  let buffering = false, buffer = [];

  async function refresh() {
    const current = ++generation;
    buffering = true; buffer = [];
    try {
      const snapshot = await loadSnapshot();
      if (stopped || current !== generation) return;
      onSnapshot(snapshot);
      for (const event of buffer) onEvent(event);
    } finally {
      if (current === generation) { buffering = false; buffer = []; }
    }
  }

  function connect() {
    if (stopped) return;
    onStatus(attempt ? 'RECONNECTING' : 'DISCONNECTED');
    const active = socket = new WebSocketClass(url);
    function armWatchdog() {
      cancel(watchdog);
      watchdog = schedule(() => active.close(), 45000);
    }
    active.onopen = () => {
      if (stopped || socket !== active) return;
      onStatus('CONNECTED'); armWatchdog();
      // Subscribe first, buffer events during REST recovery, then apply deltas.
      refresh().catch(() => active.close());
    };
    active.onmessage = message => {
      if (stopped || socket !== active) return;
      armWatchdog(); attempt = 0;
      let event;
      try { event = JSON.parse(message.data); } catch { return; }
      if (!event || typeof event.type !== 'string' || !event.timestamp || !event.data) return;
      if (event.type === 'HEARTBEAT') return;
      if (buffering) {
        buffer.push(event);
        if (buffer.length > 10000) active.close();
      } else onEvent(event);
    };
    active.onerror = () => active.close();
    active.onclose = () => {
      if (stopped || socket !== active) return;
      cancel(watchdog); ++generation; buffering = false; buffer = [];
      onStatus('RECONNECTING');
      retry = schedule(connect, Math.min(1000 * 2 ** attempt++, 30000));
    };
  }
  return {
    start() { connect(); },
    refresh,
    stop() {
      stopped = true; ++generation; cancel(retry); cancel(watchdog);
      socket?.close(); onStatus('DISCONNECTED');
    },
  };
}

function upsert(rows, row, key = 'id', limit = 100) {
  return [row, ...(rows ?? []).filter(item => item[key] !== row[key])]
    .sort((a, b) => b[key] - a[key]).slice(0, limit);
}

export function applyLiveEvent(state, event) {
  const data = event.data;
  switch (event.type) {
    case 'MARKET_PRICE_UPDATED':
      return { ...state, connection: state.connection ? { ...state.connection,
        last_tick_at: data.last_tick_at, ticks_received: data.ticks_received,
        prices: { ...state.connection.prices, [data.instrument]: data.price } } : null,
        prices: { ...state.prices, [data.instrument]: { price: data.price, change: data.change } } };
    case 'ZERODHA_CONNECTION_STATUS':
      return { ...state, connection: { ...state.connection, ...data } };
    case 'LEVEL_TRIGGERED': return { ...state, events: upsert(state.events, data) };
    case 'LEVEL_DISARMED':
    case 'LEVEL_REARMED':
    case 'LEVEL_UPDATED':
      return { ...state, levels: upsert(state.levels, data.level, 'id', Infinity).sort((a, b) => a.id - b.id) };
    case 'LEVEL_DELETED': return { ...state, levels: (state.levels ?? []).filter(level => level.id !== data.id) };
    case 'SIGNAL_CREATED': return { ...state, signals: upsert(state.signals, data) };
    case 'OPTION_SELECTION_CREATED': return { ...state, selections: upsert(state.selections, data) };
    case 'TRADE_ENTRY_RESULT': return { ...state, entryResults: upsert(state.entryResults, data, 'option_selection_id') };
    case 'TRADE_OPENED':
    case 'TRADE_CLOSED':
    case 'STOP_UPDATED':
    case 'TRADE_UPDATED': return { ...state, trades: upsert(state.trades, data, 'trade_id') };
    default: return state;
  }
}
