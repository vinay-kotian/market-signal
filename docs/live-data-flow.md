# Live data audit and browser feed

## Zerodha ingress (verified in code)

`KiteConnector.websocket_url()` builds `wss://ws.kite.trade` with backend-only
credentials. `ZerodhaMarketDataProvider.run()` uses the existing asynchronous
`websockets` library directly, not the threaded KiteTicker SDK. It sends
`subscribe` and `mode: ltp` messages with normalized instrument-master tokens.
Binary frames are decoded, validated, mapped to application instrument names,
and passed as `PriceTick` into the existing `SimulationFlow`:

Zerodha socket → PriceTick → LevelMonitor → SignalEngine → OptionSelector →
PaperExecutor. Option-symbol ticks go to PositionMonitor. Neither path submits
broker orders. The browser is an observer, never a strategy clock or executor.

Required tokens are enabled configured indices (including DISARMED levels that
need re-arming observations) plus contracts for OPEN PAPER trades. Subscription
reconciliation runs after frames and during one-second receive timeouts. It
reads local state and sends socket subscription changes; it does not fetch
prices by HTTP. Closed positions are unsubscribed when no longer needed.
Reconnect clears the sent-token set and subscribes the complete required set.
The existing reconnect delay is 1–30 seconds, reset on a successful connection.

### REST audit

Searches of backend/app and frontend/src found:

- Token exchange: POST /session/token, only during authentication.
- Instrument master: GET /instruments, at authenticated startup or explicit sync.
- Entry quote: GET /quote/ltp in ZerodhaOptionPrices.prepare, once per valid
  selected entry attempt. This deliberately remains: strategy-rules.md requires
  a fresh quote before the entry transaction; the selected option might not yet
  be subscribed. It is not periodic polling, not the continuous position/index
  feed, and no retries/timers were added. Missing quotes still fail entry.
- No repeated REST ltp/quote/ohlc price loop exists. The mandatory-exit timer
  uses locally stored prices; it makes no market-price HTTP requests.
- React previously refreshed connection/levels/trades/signals/etc. every five
  seconds in ZERODHA mode. That interval has been removed.

The socket protocol follows [Kite's documentation](https://kite.trade/docs/connect/v3/websocket/).
The backend transport follows [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/).

## Application-to-browser feed

`/ws/market` uses one socket per mounted React application, shared by every page.
Production uses `wss://stockpi.vkotian.com/ws/market`; Vite proxies `/ws` locally.
The publisher wraps the existing live/simulated flow. After transactions commit,
it reads new persisted signal, selection, level and trade events using indexed
ID cursors, and emits normalized payloads. Position high-price changes also emit
trade updates, even when no stop event was necessary. The existing mandatory-exit
service notifies it after a successful close, including exits without new ticks.
Backtests never construct this publisher and remain isolated.

Every event has `type`, server emission `timestamp`, and `data`:

- MARKET_PRICE_UPDATED: instrument, price, change from previous backend tick,
  received-tick timestamp and count.
- LEVEL_TRIGGERED: normalized trigger.
- LEVEL_DISARMED / LEVEL_REARMED: persisted event plus current level.
- SIGNAL_CREATED / OPTION_SELECTION_CREATED / TRADE_ENTRY_RESULT: persisted result.
- TRADE_OPENED / STOP_UPDATED / TRADE_CLOSED / TRADE_UPDATED: current full trade.
- ZERODHA_CONNECTION_STATUS: sanitized connection/auth/sync state and metrics.
- LEVEL_UPDATED / LEVEL_DELETED: CRUD notifications for other browser tabs.
- HEARTBEAT: transport liveness only, not a market tick or UI business event.

No tokens, secrets or raw broker messages are sent. Same-origin browser checks
apply to this read-only endpoint. This is not new user authentication; the site's
existing access restrictions must also cover /ws/. Keep one Uvicorn worker.

## Recovery and slow clients

REST loads the initial snapshot and remains available for manual refresh, CRUD,
reports, history and backtests. Opening/reopening a socket refreshes the live REST
snapshot once, buffering incoming events until snapshot completion. Incremental
updates merge by record ID. Earlier outstanding snapshots cannot overwrite a
newer recovery. There is no recurring REST fallback while disconnected.

Browser reconnect delays grow from 1 to 30 seconds. A healthy message resets the
backoff. Heartbeats every 20 seconds keep idle Nginx connections alive; 45 seconds
without any message causes browser reconnect. Cleanup cancels timers and sockets.

The hub has one bounded 256-message in-process buffer and sender task per browser,
not per instrument. A full buffer disconnects that client for REST recovery;
slow socket sends time out after five seconds. Strategy processing never waits
for browser network I/O. This is a live notification feed, not a durable replay
log or external message queue. Persisted SQLite results remain authoritative.

## Operations

The Connection page distinguishes authenticated session status, Zerodha socket
status, and browser feed status. Metrics are process-local: subscribed count,
accepted socket ticks, last accepted tick receive time (not exchange timestamp),
and failed connection/reconnect cycles. They reset on backend restart.

Logs use the Uvicorn logger so systemd captures connected/disconnected transitions,
subscription counts, reconnect counts, first tick and every 1,000th accepted tick.
Do not log broker connection URLs, which contain credentials.

1. Install the /ws/ Nginx block as described in deploy/README.md.
2. Open Chrome DevTools → Network → WS. Expect one /ws/market connection with 101
   Switching Protocols; switching app tabs must not create more sockets.
3. Inspect Messages for MARKET_PRICE_UPDATED and state/trade events. Fetch/XHR
   should show snapshots on load/reconnect, not requests every five seconds.
4. Verify the watchlist and Trades page update without clicking Refresh. Price
   change is between received ticks, not change from yesterday's close.
5. In a second browser tab, edit a level and verify the first tab updates.
6. Toggle Chrome Network Offline, then Online. Expect RECONNECTING, a new socket,
   one recovery snapshot batch, and resumed updates. An idle open socket should
   still receive HEARTBEAT; that does not imply the market is producing prices.
7. On Lightsail inspect `sudo journalctl -u stockpi-backend -f`. Compare socket
   connection/subscription logs with the Connection page metrics. Outside market
   hours, CONNECTED with an unchanged last-tick time can be normal.

Automated tests use mocked broker sockets/HTTP only. Actual broker/network and
production Nginx validation must be performed after deployment.
