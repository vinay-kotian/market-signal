/** Single documentation source for field help, decision help, search and articles.
 * Defaults below are documented system defaults, never historical decision inputs.
 */
const topic = (id, title, category, summary, rules, extra = {}) => ({ id, title, category, summary, rules,
  keywords: [], related: [], configurable: 'Review Settings for controls available in the UI; backend-only parameters require server configuration.', ...extra });
export const topics = [
  topic('getting-started/paper', 'PAPER execution and getting started', 'Getting started', 'Market data and execution are separate. Broker integration is read-only; trades execute in PAPER.', [
    'Add levels for the intended Asia/Kolkata trading date, provide market data, and review signals, selections and entry results separately.',
    'A valid signal does not guarantee a trade. Time, contract, price, position and exit-risk checks can still reject entry.',
    'Backtests use isolated BACKTEST state and do not place orders or send trade alerts.'
  ], { related: ['signals/arm-distance', 'entries/eligibility'] }),
  topic('dashboard/quotes', 'Watchlist prices and data freshness', 'Dashboard & watchlist', 'LTP is the latest received observation, not a guarantee of a currently executable quote.', [
    'Index changes use the available previous close; absent reference data stays unknown.',
    'Option watchlist entries originate from trades. A closed option can still receive new market prices; its realised result stays fixed.',
    'Browser feed status, broker authentication and the Zerodha market-data socket are different connection states.'
  ], { related: ['zerodha/connection', 'trades/pnl'] }),
  topic('signals/arm-distance', 'Initial arm distance and pending levels', 'Levels & signals', 'A level arms only when a valid underlying price is at least the configured distance from the level.', [
    'The condition is absolute(index price − level price) ≥ the index’s Initial Arm Distance.',
    'No valid quote or insufficient distance leaves the level PENDING_ARM. Enabled levels for the current date are checked on subsequent observations.',
    'The activation reference is audit metadata; distance is measured from the configured level. Changing the setting preserves ACTIVE and DISARMED states.',
    'A displayed live distance explains current eligibility only; it does not reconstruct the quote or threshold used when an old level first armed.'
  ], { formula: '|index price − level price| ≥ initial arm distance', configurable: 'Settings → Index rules. The per-index distance is distinct from the signal approach filter.', related: ['signals/approach', 'levels/lifecycle'] }),
  topic('levels/lifecycle', 'Level dates, states and rearming', 'Levels & signals', 'Enabled status, trading date and arm state jointly determine whether a level is eligible.', [
    'Levels apply to their Asia/Kolkata date. Future levels do not trade early; past levels expire.',
    'PENDING_ARM waits for sufficient distance. ACTIVE is armed. DISARMED requires rearming after the normal signal/entry flow. EXPIRED is historical.',
    'A later underlying observation at sufficient distance can rearm a disarmed level. Option ticks and trade closure do not rearm it.'
  ], { related: ['signals/arm-distance', 'signals/touch-cross'] }),
  topic('levels/timeframe', 'Level timeframe metadata', 'Levels & signals', 'A level’s timeframe is descriptive metadata and part of its identity.', [
    'Configured options include 5m, 15m, 1h and 1d, with optional backend-configured durations.',
    'The timeframe does not choose strategy rules or the ATR candle duration. Missing historical timeframe remains “Not recorded”.',
    'The same price can have separate records for different dates or timeframes.'
  ], { related: ['atr/strategies'] }),
  topic('signals/touch-cross', 'Touches, crosses and signal generation', 'Levels & signals', 'A touch or crossing can be analysed only for an eligible armed level.', [
    'Crosses satisfy previous < level ≤ current, or previous > level ≥ current. Current == level also counts as a touch.',
    'Unchanged repeated prices are ignored. The first price establishes a baseline.',
    'FROM_ABOVE and FROM_BELOW describe the prior contiguous same-side approach, not the eventual option’s profit or loss.'
  ], { related: ['signals/approach', 'entries/option-selection'] }),
  topic('signals/approach', 'Signal approach distance and rejection', 'Levels & signals', 'The signal engine examines prior same-side prices within its lookback window.', [
    'It walks backward until a level touch or side change. FROM_ABOVE uses maximum approach price − level; FROM_BELOW uses level − minimum approach price.',
    'No usable approach yields INSUFFICIENT_PRICE_HISTORY. If the distance filter is enabled and distance is below its threshold, rejection is MINIMUM_DISTANCE_NOT_MET.',
    'The default lookback is 15 minutes. The approach filter defaults to disabled with a 0-point threshold. These defaults are not evidence of a historical threshold.'
  ], { configurable: 'Signal parameters are backend configuration and backtest input fields. New signals record their applied settings.', related: ['signals/arm-distance', 'signals/touch-cross'] }),
  topic('entries/eligibility', 'Why an entry was skipped', 'Option selection & entry', 'A signal, a selected option and a successful trade entry are separate outcomes.', [
    'PAPER/BACKTEST entry checks the level state/date, execution mode, signal and fill times, existing position, contract, lot size, quote and exit-risk configuration.',
    'Only one open trade per underlying is allowed. Historical replay can also reserve one pending entry per underlying.',
    'Unknown or unavailable data is not permission to invent a price or contract. Read the stored reason code; a failed entry is not a losing trade.'
  ], { related: ['entries/time-window', 'entries/option-selection', 'atr/risk-guard'] }),
  topic('entries/option-selection', 'Option contract, ATM, ITM and quantity', 'Option selection & entry', 'Selection uses the signal’s trigger price, nearest unexpired expiry and configured ITM depth.', [
    'FROM_ABOVE selects CE; FROM_BELOW selects PE. ATM rounds trigger price to the instrument strike step using half-up rounding.',
    'CE strike = ATM − depth × step; PE strike = ATM + depth × step. Default depth is 1.',
    'The exact expiry, strike and type must exist in the catalogue. There is no substitute contract when it is missing.',
    'Quantity = contract lot size × number of lots. Default number of lots is 1. The catalogue supplies lot size.'
  ], { formula: 'quantity = lot size × number of lots', related: ['entries/eligibility', 'risk/sizing'] }),
  topic('entries/time-window', 'Entry start and cutoff restrictions', 'Option selection & entry', 'Both the signal timestamp and execution timestamp must lie inside the entry window.', [
    'Entry starts at market open + the opening block, inclusive. The cutoff is market close − the closing block, exclusive.',
    'Defaults: 09:15–15:30 session, 10-minute opening block and 10-minute closing block. This produces a 09:25 ≤ time < 15:20 IST entry window.',
    'Trading-time settings can change during PAPER trading. Entry rejection records capture the applied window; historical entry snapshots do not prove a later mandatory-exit deadline.'
  ], { configurable: 'Settings → Trading hours. New backtests capture their own settings.', related: ['trades/market-close'] }),
  topic('atr/strategies', 'ATR strategies are different', 'Exit strategies', 'ATR uses five-minute Wilder ATR; Strategy 3 (ATR_FIXED) uses one-minute SMA true ranges.', [
    'ATR requires its configured period of completed available candles and skips entry when its option ATR is unavailable. It has no percentage fallback.',
    'Strategy 3 permits reduced history when its minimum is met and applies a configured fallback stop if ATR/history/stop is invalid.',
    'ATR can trail and activate breakeven according to its frozen configuration. Strategy 3 keeps its stop and target fixed.'
  ], { related: ['atr/minimum-candles', 'atr/wilder', 'atr/fixed-stop'] }),
  topic('atr/minimum-candles', 'Minimum pre-entry candles', 'Exit strategies', 'Strategy 3 requires completed one-minute option candles ending at or before actual entry.', [
    'The default minimum is 2 candles. The first candle has no prior close, so two contiguous candles provide one valid True Range.',
    'Up to the latest atr_period valid TRs are averaged. With default atr_period = 14, fifteen contiguous candles supply the full fourteen TRs.',
    'With less history than the configured period but at least the minimum, available valid TRs are used. Missing adjacent minutes cannot supply an invented previous close.',
    'Insufficient history uses Strategy 3’s fallback; this is not the rule of the separate Wilder ATR strategy.',
    'Partially completed and future candles are excluded from entry ATR. Old trades may not record the number of pre-entry candles.'
  ], { configurable: 'Settings → Strategy 3 → min pre entry candles. Default 2; frozen at entry.', related: ['atr/fallback', 'atr/wilder'], example: 'Illustrative only: 10 contiguous candles give 9 TRs. If their sum is ₹36, SMA ATR is ₹4. This does not assert that a real trade used those values.' }),
  topic('atr/fallback', 'ATR fallback activation', 'Exit strategies', 'Strategy 3 uses its percentage fallback when history, ATR or the ATR-derived stop is invalid.', [
    'Fallback stop = actual entry premium × (1 − fallback_sl_pct / 100). The default fallback is 20%.',
    'The stored stop_source and fallback_reason say whether and why fallback was used. Do not infer fallback merely because ATR is missing in an older record.',
    'An invalid fallback rejects the trade. A maximum-risk breach rejects entry rather than substituting a tighter stop.'
  ], { formula: 'stop = entry × (1 − fallback percent / 100)', configurable: 'Settings → Strategy 3. Uses the frozen entry-time fallback percentage.', related: ['atr/minimum-candles', 'atr/risk-guard'] }),
  topic('atr/fixed-stop', 'Strategy 3 fixed stop and target', 'Exit strategies', 'The stop and target are calculated once from actual entry price and frozen settings.', [
    'ATR stop = entry − ATR × multiplier. Risk per unit = entry − initial stop. Target = entry + risk × risk/reward ratio.',
    'Defaults: SMA ATR period 14, multiplier 0.75, risk/reward 2. No trailing, breakeven, dynamic target or partial exit is added.',
    'PAPER stops and targets fill at observed quotes. Historical baseline fills use the exact fixed threshold.',
    'Both thresholds touched in one minute: SL wins. At EOD the cutoff candle close is used; missing coverage is DATA_INCOMPLETE.'
  ], { formula: 'initial stop = entry − (ATR × multiplier); target = entry + risk × risk/reward', related: ['atr/fallback', 'backtesting/candle-limitations'], example: 'Illustrative only: entry ₹100, ATR ₹4, multiplier 0.75 → stop ₹97. Risk ₹3 and ratio 2 → target ₹106.' }),
  topic('atr/wilder', 'Five-minute Wilder ATR', 'Exit strategies', 'The ATR strategy uses only completed, available option candles and Wilder smoothing.', [
    'Default period 14, timeframe 5minute, initial multiplier 1.5. The first TR is high − low. The first period seeds an arithmetic mean; later values use (previous ATR × (period − 1) + TR) / period.',
    'A missing/nonpositive option ATR skips entry. Risk at/above the entry price is invalid. The default maximum SL risk is 15%, optionally removable.',
    'The option ATR is frozen at entry, including for later ATR trailing. Index ATR is recorded separately and does not set the option stop.'
  ], { formula: 'initial stop = entry − option ATR × initial multiplier', related: ['atr/risk-guard', 'trades/trailing-stop', 'trades/breakeven'] }),
  topic('atr/risk-guard', 'Initial risk and rejected risk limits', 'Risk management', 'Risk guards block entries that exceed the configured maximum; they do not tighten the calculated stop.', [
    'Initial risk per unit = entry − initial stop. Initial risk percent = risk / entry × 100. Amount at risk = risk per unit × quantity.',
    'ATR uses atr_max_sl_percent; Strategy 3 uses max_initial_risk_pct. These are different settings. Strategy 3’s guard defaults to null.',
    'Snapshots can show the entry-time guard. If an old rejected entry has no context, its exact attempted risk cannot be reconstructed.'
  ], { related: ['risk/sizing', 'atr/fixed-stop', 'atr/wilder'] }),
  topic('trades/initial-stop', 'Initial stop-loss calculation', 'Exit strategies', 'Use the trade’s recorded strategy and frozen settings to interpret its initial stop.', [
    'LEGACY percentage stop = entry × (1 − stop_loss_percentage / 100). Progressive uses initial_stop_loss_pct instead.',
    'ATR uses frozen option ATR and multiplier. Strategy 3 uses its recorded ATR or fallback source.',
    'Initial stop and current effective stop are different values. Later protection may raise the stop in strategies that support it.'
  ], { related: ['atr/fixed-stop', 'atr/wilder', 'trades/trailing-stop'] }),
  topic('trades/trailing-stop', 'Trailing updates and stop exits', 'Exit strategies', 'A trailing stop can only raise the effective stop in strategies that support trailing.', [
    'LEGACY percentage trailing = highest observed premium × (1 − trailing percent / 100).',
    'ATR trailing mode OFF keeps the initial candidate; PERCENTAGE uses highest × (1 − percent / 100); ATR uses highest − frozen entry ATR × trailing multiplier.',
    'Effective protection is the maximum of initial stop, previous stop, trailing candidate and any activated protection.',
    'A raised effective stop produces TRAILING_STOP_LOSS when hit. A profitable result alone does not establish the exit reason.',
    'Event-time previous/current stops are preferable to a trade’s final high/stop when explaining a historical update. Strategy 3 never trails.'
  ], { related: ['trades/breakeven', 'trades/progressive', 'backtesting/candle-limitations'] }),
  topic('trades/breakeven', 'Breakeven activation', 'Exit strategies', 'Activation and the protected price depend on the frozen strategy configuration.', [
    'LEGACY activates at entry × (1 + activation percent / 100); its lock price is entry × (1 + lock percent / 100).',
    'ATR can activate using percentage, ATR multiples or initial-risk R. OFF disables activation. The protected price uses its frozen breakeven lock percent.',
    'An activation event confirms the condition was reached. An old trade’s final high is not evidence of the exact activation observation. Strategy 3 has no breakeven adjustment.'
  ], { related: ['trades/trailing-stop', 'trades/progressive'] }),
  topic('trades/progressive', 'Progressive profit lock and tightening', 'Exit strategies', 'Progressive LEGACY protection locks profit and tightens a percentage trail in configured steps.', [
    'Defaults: initial stop 10%, lock trigger 10%, lock 5%, initial trail 10%, reduction step 10 premium points, reduction 1 percentage point, minimum trail 5%.',
    'After activation, step = floor((highest − trigger premium) / step points), bounded below by zero. Trail percent is bounded by the configured minimum.',
    'Effective stop is the maximum of initial, previous, locked and trailing stops. A recorded PROFIT_LOCK_ACTIVATED is distinct from legacy breakeven.'
  ], { related: ['trades/trailing-stop', 'trades/breakeven'] }),
  topic('settings/strategy-selection', 'Strategy selection and overrides', 'Settings reference', 'Selection chooses the exit strategy for a future entry; open trades retain their strategy and exit configuration.', [
    'Priority: explicit execution override → next-trade override → daily instrument override → persistent instrument override → daily default → persistent default.',
    'Next-trade overrides apply to that date and underlying and are consumed only after successful entry. Failed entries do not consume them.',
    'Disabling ATR prevents new ATR entries; it does not stop monitoring existing ATR positions. ATR_FIXED is a separate selection.',
    'If the old trade records only the selected strategy, the winning override source is unknown. Never infer it from current Settings.'
  ], { configurable: 'Settings → Exit strategies: persistent, daily and next-trade selections.', related: ['settings/snapshots', 'atr/strategies'] }),
  topic('settings/snapshots', 'Frozen settings and effective times', 'Settings reference', 'Historical explanations use stored snapshots, not the current Settings page.', [
    'Each trade freezes its entry signal/option/trade configuration and exit strategy configuration. Strategy 3 also stores its complete entry plan.',
    'Exit defaults affect future entries. Trading-time configuration affects running PAPER time checks immediately; backtests keep their run configuration. Strategy 3’s own EOD cutoff is frozen.',
    'Level arming uses applicable index settings during evaluation; a current quote and threshold are a live observation, not historical proof.',
    'Missing historical thresholds or counts remain unavailable. A derived value must be identified as derived.'
  ], { related: ['entries/time-window', 'trades/market-close'] }),
  topic('trades/market-close', 'Mandatory market-close and EOD exits', 'Trades & reports', 'A market-close exit is a time rule, not a conclusion inferred from P&L.', [
    'Default generic mandatory exit is 3 minutes before 15:30 (15:27 IST). PAPER checks use the currently applicable trading-time rules, including for open trades.',
    'The PAPER market-close service can use its last known quote, provider quote or entry-price fallback. A recorded exit price is not proof of a fresh executable quote.',
    'Backtests require valid exit data and do not silently fill a missing mandatory exit. Strategy 3 instead freezes its own EOD time, default 15:25.',
    'Strategy 3 PAPER waits for an observed quote at/after cutoff. Historical Strategy 3 requires a completed eligible cutoff candle.'
  ], { related: ['entries/time-window', 'backtesting/data-quality'] }),
  topic('trades/exit-reasons', 'Recorded exit reasons', 'Trades & reports', 'The persisted exit reason is the evidence of why a position closed.', [
    'STOP_LOSS and TRAILING_STOP_LOSS are shared protection exits. Strategy 3 uses SL, TARGET and EOD. Market-close reasons identify time exits; MANUAL_SQUARE_OFF is explicit user action.',
    'Do not classify an exit from P&L sign. Stop exits can be profitable after protection rises.',
    'A historical event without a reason cannot be assigned one from final trade performance.'
  ], { related: ['trades/trailing-stop', 'trades/market-close'] }),
  topic('trades/pnl', 'Premium, quantity and P&L', 'Trades & reports', 'Long-option gross P&L is exit minus entry premium, multiplied by quantity.', [
    'Gross P&L = (exit − entry) × quantity. Return percent = (exit − entry) / entry × 100. Open positions have no realised outcome.',
    'PAPER reports do not subtract brokerage, taxes or slippage. Backtests support a separate flat transaction cost per order.',
    'Net P&L is gross minus separately modelled costs. Never assume brokerage, taxes or executable fills that are not supplied.'
  ], { formula: 'gross P&L = (exit − entry) × quantity', related: ['reports/metrics', 'backtesting/costs'] }),
  topic('reports/metrics', 'Win rate, profit factor and drawdown', 'Trades & reports', 'Reports calculate realised performance from persisted closed trades in the selected scope.', [
    'Win rate = winners / (winners + losers) × 100; breakeven trades are excluded from this denominator. Backtest summary win_rate uses closed trades as its denominator.',
    'Profit factor = gross profits / absolute gross losses; no losses makes it unavailable. Loss metrics are displayed as positive amounts.',
    'Maximum drawdown uses closed realised P&L in exit-time order. Open mark-to-market drawdown is not calculated by this metric.',
    'STRATEGY view excludes flagged records; RAW includes them. Date filters select Asia/Kolkata entry dates.'
  ], { related: ['reports/r-multiple', 'reports/classification'] }),
  topic('reports/r-multiple', 'R-multiple and average R', 'Trades & reports', 'One R is the recorded initial amount at risk.', [
    'Gross realised R = (exit − entry) / initial risk per unit. Average R in existing reports/backtest summaries uses included realised P&L divided by known initial risk amount; backtest costs can reduce it.',
    'Trades without known positive initial risk do not contribute a fabricated R. The sample size can differ from closed-trade count.',
    'Comparisons show observed strategy groups, whose entry samples can differ. They are not promises of future performance.'
  ], { related: ['atr/risk-guard', 'backtesting/costs'] }),
  topic('reports/classification', 'Classification and report filters', 'Trades & reports', 'Classification changes report inclusion and validity annotations, not trading history.', [
    'Excluded trades remain visible in RAW history. Bulk classification validates the selected IDs as a whole.',
    'Timeframe, instrument, strategy, entry-date and status filters control the report scope. An absent timeframe stays unknown.',
    'CSV exports persistently recorded PAPER values; it does not reconstruct missing historical settings.'
  ], { related: ['reports/metrics'] }),
  topic('backtesting/candle-limitations', 'Candle simulation and intrabar limits', 'Backtesting', 'One-minute OHLC does not reveal the actual sequence of intraminute prices.', [
    'Zerodha historical replay generates signals from completed index closes and fills entries at the next eligible option open.',
    'The existing Legacy/ATR candle replay evaluates adverse low before crediting high, then retests low against raised protection. It is a conservative approximation, not an observed tick path.',
    'Strategy 3 resolves a same-candle stop/target collision to SL first. Its partial entry minute is skipped by default; FULL_CANDLE_APPROXIMATION explicitly uses it.',
    'OHLC threshold fills are theoretical and cannot promise exact executable intrabar prices or order timing.'
  ], { related: ['backtesting/data-quality', 'atr/fixed-stop'] }),
  topic('backtesting/data-quality', 'Missing historical data and incomplete runs', 'Backtesting', 'Historical data must identify the exact dated contract and provide sufficient price coverage.', [
    'Missing or duplicate minute candles are not silently filled. Future data cannot establish entry ATR.',
    'Strategy 3 returns DATA_INCOMPLETE for missing post-entry/cutoff coverage. An unclosed incomplete trade retains null exit/P&L rather than a fabricated EOD outcome.',
    'Historical entry/mandatory-exit data errors can fail other replays. A failed contract selection does not permit a substitute.',
    'Warnings are not all fatal. An option ATR warmup warning can mean ATR entries lack required history; Strategy 3 evaluates its independent minute data and fallback rules.'
  ], { related: ['atr/minimum-candles', 'backtesting/candle-limitations'] }),
  topic('backtesting/costs', 'Backtest fees and execution assumptions', 'Backtesting', 'Flat transaction_cost_per_order is separate from fill pricing.', [
    'A closed trade has two orders (entry and exit). An open trade incurs its entry cost only in aggregate accounting.',
    'No automatic brokerage/tax schedule or slippage estimate is implied. Strategy 3 baseline slippage_model is none.',
    'Run settings, dataset hash, data resolution and execution model are stored for reproducibility.'
  ], { related: ['trades/pnl', 'reports/r-multiple'] }),
  topic('zerodha/connection', 'Zerodha connection and authentication', 'Zerodha integration', 'Authentication, instrument sync, market-data socket and browser feed have separate states.', [
    'Connect Zerodha through the broker login flow, then sync instruments. Passwords/OTPs stay with Zerodha. Execution remains PAPER.',
    'Connection errors with a structured auth_error.code link to this guide. Unknown messages are shown as recorded messages, not guessed diagnoses.',
    'Login and market-data mode must be configured on the backend. Simulated mode disables broker controls. Reconnect attempts do not prove current data freshness.'
  ], { configurable: 'Settings → Connection. Backend credentials and market-data mode are server configuration.', related: ['zerodha/instruments', 'dashboard/quotes'] }),
  topic('zerodha/instruments', 'Instrument sync and market-data subscriptions', 'Zerodha integration', 'Contracts and index tokens must exist in the synced catalogue before they can be subscribed or selected.', [
    'Enabled index levels, open-paper option positions and retained option-watchlist rows determine the normal subscriptions.',
    'Dated historical catalogues are required for trustworthy historical nearest-expiry selection. Today’s instruments do not prove an older expiry existed.',
    'Missing instrument data and missing price data are separate failures. Check the reported code and actual last-sync/last-tick timestamps.'
  ], { related: ['entries/option-selection', 'backtesting/data-quality'] }),
  topic('risk/sizing', 'Quantity and initial amount at risk', 'Risk management', 'Quantity is lot size times configured lots; stop risk is measured in option-premium points.', [
    'Initial amount at risk = (entry − initial stop) × quantity. It is not a guarantee of a maximum executable loss.',
    'Gaps, delayed quotes, missing historical observations and costs can affect realised loss. Index level distance is not the option stop distance.'
  ], { related: ['atr/risk-guard', 'entries/option-selection'] }),
  topic('settings/notifications', 'Telegram notifications', 'Settings reference', 'Telegram messages can be sent for PAPER option entries when enabled.', [
    'The channel destination URL is configured separately from the enable switch. Backtests do not send trade notifications.',
    'A notification is not evidence of a live broker order; the platform uses PAPER execution.'
  ], { related: ['getting-started/paper'] }),
  topic('dashboard/charts', 'Chart candles and recorded markers', 'Dashboard & watchlist', 'Charts show available minute prices and recorded event markers.', [
    'A marker identifies its recorded event time and price. Missing candles are not proof that no price movement occurred.',
    'A final trade snapshot cannot establish the exact high/stop at every earlier chart marker. Read the event-time metadata when present.'
  ], { related: ['backtesting/candle-limitations', 'trades/exit-reasons'] }),
  topic('troubleshooting/unknown', 'Unavailable decision details', 'Troubleshooting & FAQs', 'Some older records and external errors do not contain structured decision evidence.', [
    'The application shows only recorded fields and clearly labelled arithmetic derived from them.',
    'An unknown reason code is displayed without assigning a guessed rule. No missing threshold, candle count, exit reason or override source is inferred from today’s settings or P&L.',
    'New records can carry additive decision_context metadata while old API fields remain unchanged.'
  ], { related: ['settings/snapshots', 'trades/exit-reasons'] }),
  topic('glossary/trading', 'Trading glossary', 'Trading glossary', 'Common terms describe different parts of the decision pipeline.', [
    'LTP: last traded/received premium. OHLC: open, high, low, close for an interval. ATR: average true range. SMA: arithmetic mean.',
    'CE/PE: call/put. ATM/ITM: at/in the money relative to the trigger price and configured selection depth.',
    'Armed: eligible level state. Signal: level approach analysis. Selection: chosen contract. Entry: accepted simulated execution. R: initial risk unit.'
  ], { related: ['getting-started/paper', 'entries/option-selection'] })
];
export const helpRegistry = Object.assign(Object.create(null), Object.fromEntries(topics.map(t => [t.id, { ...t, url: `/help/${t.id}` }])));
export const categories = [...new Set(topics.map(t => t.category))];
export function searchTopics(query = '', category = '') {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return topics.filter(t => (!category || t.category === category) && words.every(word =>
    [t.title, t.summary, t.category, ...t.rules, ...t.keywords, t.formula, t.configurable].filter(Boolean).join(' ').toLowerCase().includes(word)));
}
export function helpPath(id) { return helpRegistry[id]?.url ?? '/help/troubleshooting/unknown'; }

// Settings labels use the same articles as decisions and the searchable center.
export function fieldTopic(key, strategy = '') {
  if (key.includes('approach') || key === 'lookback_minutes') return 'signals/approach';
  if (key === 'number_of_lots') return 'risk/sizing';
  if (['itm_depth', 'expiry_strategy'].includes(key)) return 'entries/option-selection';
  if (key === 'trade_mode') return 'getting-started/paper';
  if (key === 'min_pre_entry_candles') return 'atr/minimum-candles';
  if (key === 'fallback_sl_pct') return 'atr/fallback';
  if (['atr_max_sl_percent', 'max_initial_risk_pct'].includes(key)) return 'atr/risk-guard';
  if (key === 'entry_candle_policy') return 'backtesting/candle-limitations';
  if (key === 'eod_exit_time' || key === 'mandatory_exit_before_close_minutes') return 'trades/market-close';
  if (key.includes('breakeven')) return 'trades/breakeven';
  if (key.includes('profit_lock') || key.includes('trailing_reduction') || key === 'minimum_trailing_pct') return 'trades/progressive';
  if (key.includes('trailing')) return 'trades/trailing-stop';
  if (key.startsWith('atr_')) return strategy === 'ATR_FIXED' ? 'atr/fixed-stop' : 'atr/wilder';
  if (['risk_reward_ratio'].includes(key)) return 'atr/fixed-stop';
  if (key.includes('slippage') || key.includes('transaction_cost')) return 'backtesting/costs';
  if (key.includes('stop_loss') || key === 'stop_strategy') return 'trades/initial-stop';
  if (key.includes('market_') || key.includes('entry_block_')) return 'entries/time-window';
  if (key.includes('arm_distance')) return 'signals/arm-distance';
  return 'settings/snapshots';
}
