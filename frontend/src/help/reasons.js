import { helpRegistry } from './registry.js';

// Exact machine codes only. Never classify an arbitrary message by its wording.
const groups = [
  ['signals/approach', {
    SIGNAL_ACCEPTED: ['Signal accepted', 'The stored signal passed approach analysis. This alone does not establish entry eligibility.'],
    INSUFFICIENT_PRICE_HISTORY: ['Signal rejected — no usable approach history', 'No prior contiguous same-side approach was available inside the signal lookback.'],
    MINIMUM_DISTANCE_NOT_MET: ['Signal rejected — minimum approach distance not met', 'The enabled approach filter rejected a distance below its recorded threshold.'],
  }],
  ['signals/arm-distance', {
    LEVEL_PENDING_ARM: ['Level pending initial arm', 'The level has not yet met the initial arming condition with a valid underlying quote.'],
    LEVEL_ARMED: ['Level armed', 'The recorded level became eligible after meeting the arming condition.'],
    LEVEL_REARMED: ['Level rearmed', 'A later underlying observation rearmed the level.'],
  }],
  ['levels/lifecycle', {
    LEVEL_DISARMED: ['Level disarmed', 'The level is not currently armed; a later eligible underlying observation is needed to rearm it.'],
    LEVEL_EXPIRED: ['Entry skipped — level expired', 'The level is expired or belongs to an earlier trading date.'],
    LEVEL_NOT_CURRENT: ['Entry skipped — level date not current', 'The level date does not equal the execution trading date.'],
  }],
  ['entries/time-window', {
    BEFORE_TRADING_START: ['Entry skipped — before trading start', 'The signal or execution timestamp is before the applied entry window.'],
    NEW_TRADE_CUTOFF_REACHED: ['Entry skipped — entry cutoff reached', 'The signal or execution timestamp is at or after the exclusive entry cutoff.'],
    STRATEGY3_EOD_CUTOFF_REACHED: ['Entry skipped — Strategy 3 EOD cutoff reached', 'Actual entry was at or beyond the configured Strategy 3 EOD cutoff.'],
  }],
  ['entries/eligibility', {
    ACTIVE_TRADE_EXISTS: ['Entry skipped — position or reservation exists', 'The underlying already has an open trade or, in historical replay, a pending reservation.'],
    OPTION_PRICE_UNAVAILABLE: ['Entry skipped — option price unavailable', 'A finite positive entry quote was not available for the exact selected option.'],
    LIVE_MODE_NOT_SUPPORTED: ['Entry skipped — live execution unsupported', 'Only PAPER and isolated BACKTEST execution are supported.'],
    TRADE_MODE_MISMATCH: ['Entry skipped — execution mode mismatch', 'The executor mode differs from its repository mode.'],
    POSITION_OPENED: ['Trade entered', 'The entry passed the executor checks and was persisted.'],
    TRADE_ENTERED: ['Trade entered', 'The entry passed the executor checks and was persisted.'],
  }],
  ['entries/option-selection', {
    OPTION_SELECTED: ['Option selected', 'The selector found the required expiry, strike and option type. Selection is not confirmation of entry.'],
    UNSUPPORTED_INSTRUMENT: ['Selection failed — unsupported instrument', 'No supported strike step is available for this underlying.'],
    NO_UNEXPIRED_CONTRACT: ['Selection failed — no unexpired contract', 'The catalogue has no eligible unexpired contract for the selected date.'],
    MISSING_OPTION_CONTRACT: ['Selection failed — exact contract missing', 'The required nearest-expiry, strike and option type are absent from the catalogue.'],
    OPTION_CONTRACT_UNAVAILABLE: ['Entry skipped — contract unavailable', 'The exact selected contract could not be found in the execution catalogue.'],
    INVALID_LOT_SIZE: ['Entry skipped — invalid lot size', 'The contract lot size is not a positive integer.'],
  }],
  ['atr/wilder', {
    OPTION_ATR_UNAVAILABLE: ['ATR entry skipped — option ATR unavailable', 'The five-minute Wilder ATR strategy requires an available positive option ATR. It does not use Strategy 3’s fallback.'],
    ATR_STRATEGY_DISABLED: ['ATR entry skipped — strategy disabled', 'ATR was selected but disabled for new entries. Existing positions remain monitored.'],
  }],
  ['atr/minimum-candles', { INSUFFICIENT_PRE_ENTRY_CANDLES: ['ATR fallback — insufficient completed candles', 'Strategy 3 had fewer completed pre-entry candles than its frozen minimum, so its percentage fallback was used.'] }],
  ['atr/fallback', {
    ATR_FALLBACK: ['Strategy 3 percentage fallback used', 'The stored entry plan records FALLBACK as its stop source. Read its recorded fallback reason if available.'],
    ATR_UNAVAILABLE_OR_INVALID: ['ATR fallback — no valid positive ATR', 'Strategy 3 could not calculate a valid positive ATR from eligible history and used the percentage fallback.'],
    FALLBACK_STOP_INVALID: ['Entry rejected — fallback stop invalid', 'The fallback did not produce a finite positive stop strictly below entry.'],
  }],
  ['atr/risk-guard', {
    ATR_STOP_INVALID: ['ATR-derived stop invalid', 'The ATR-derived stop was invalid. ATR rejects entry; Strategy 3 uses fallback only when its entry plan records that outcome.'],
    ATR_MAX_SL_EXCEEDED: ['Entry skipped — ATR risk limit exceeded', 'The calculated initial risk exceeded the frozen maximum SL percentage. The stop was not silently tightened.'],
    MAX_INITIAL_RISK_EXCEEDED: ['Entry skipped — initial risk limit exceeded', 'Strategy 3’s calculated initial risk exceeded its configured maximum. The entry was blocked.'],
    ATR_BREAKEVEN_CONFIGURATION_INVALID: ['Entry skipped — invalid breakeven configuration', 'The configured lock would be at or beyond the activation distance.'],
  }],
  ['trades/initial-stop', { INITIAL_STOP: ['Initial stop calculation', 'This is the stop recorded when the trade was entered.'], STOP_LOSS: ['Initial stop-loss exit', 'The stored exit reason identifies an unraised effective stop hit.'], SL: ['Strategy 3 stop-loss exit', 'The stored exit reason is SL. In candle-only replay, SL wins if stop and target were both touched.'], STOP_LOSS_HIT: ['Stop threshold hit', 'This event records a stop hit. Use the stored exit reason to distinguish an initial stop from a raised stop.'] }],
  ['trades/trailing-stop', { TRAILING_STOP_LOSS: ['Raised stop-loss exit', 'The effective stop had risen above the initial stop when it was hit. Profit or loss is not used to assign this reason.'], TRAILING_STOP_UPDATED: ['Trailing stop updated', 'The recorded protection event raised the effective stop.'], TRAILING_UPDATED: ['Trailing stop updated', 'The recorded protection event updated trailing protection.'], STOP_UPDATED: ['Effective stop updated', 'The event records a change in the effective stop.'], TRAILING_STEP_CHANGED: ['Progressive trailing step changed', 'The progressive calculation selected a different tightening step.'] }],
  ['trades/breakeven', { BREAKEVEN_PROTECTION_ACTIVATED: ['Breakeven protection activated', 'The frozen strategy’s activation condition was met at this recorded observation.'], BREAKEVEN_ACTIVATED: ['Protection activated', 'The recorded event confirms protection activation. Progressive profit lock and breakeven have different settings.'] }],
  ['trades/progressive', { PROFIT_LOCK_ACTIVATED: ['Progressive profit lock activated', 'The frozen progressive trigger was met and its lock became effective.'] }],
  ['trades/market-close', { MARKET_CLOSE: ['Mandatory market-close exit', 'The persisted reason identifies an exit under the applicable market-close time rule.'], MARKET_CLOSING_EXIT: ['Market-closing exit', 'The stored reason identifies the market-closing time rule.'], MARKET_CLOSING_EXIT_TRIGGERED: ['Market-closing exit triggered', 'This event records the mandatory time exit.'], MANDATORY_EXIT: ['Mandatory exit deadline reached', 'The replay reached an exit deadline; a trigger alone is not evidence that an exit filled.'], EOD: ['Strategy 3 end-of-day exit', 'The frozen Strategy 3 EOD cutoff ended this trade. Historical replay uses the eligible cutoff candle close.'] }],
  ['atr/fixed-stop', { TARGET: ['Strategy 3 target reached', 'The stored exit reason identifies the fixed risk/reward target.'], FIXED_PLAN: ['Strategy 3 fixed entry plan', 'The recorded stop, target and settings are frozen at entry.'] }],
  ['settings/strategy-selection', { STRATEGY_SELECTED: ['Exit strategy selected at entry', 'The trade stores the selected strategy and its entry-time exit settings. The override source is shown only if recorded.'], UNKNOWN_EXIT_STRATEGY: ['Entry skipped — unknown exit strategy', 'The selected exit strategy is not supported.'] }],
  ['trades/exit-reasons', { MANUAL_SQUARE_OFF: ['Manual square-off', 'The stored reason identifies an explicit manual close.'], POSITION_CLOSED: ['Position closed', 'This event records a closure. Only a persisted reason can identify its cause.'], TRADE_EXITED: ['Trade exited', 'This event records an exit. A missing reason is not reconstructed from final P&L.'] }],
  ['backtesting/data-quality', { BACKTEST_REQUEST_ERROR: ['Backtest request could not complete', 'The request returned a validation or data error. Read the recorded message; no specific missing-data diagnosis is inferred without a structured code.'], DATA_INCOMPLETE: ['Simulation data incomplete', 'The supplied archive could not establish a complete outcome; no exit is fabricated.'], INCOMPLETE_POST_ENTRY_CANDLES: ['Missing post-entry minute', 'A required minute after entry is missing, so chronological first-touch claims are unavailable.'], INCOMPLETE_EXIT_COVERAGE: ['Missing cutoff exit coverage', 'Strategy 3 has no complete exit data through its EOD cutoff.'], HISTORICAL_OPTION_PRICE_UNAVAILABLE: ['Historical option price unavailable', 'The replay could not fill the selected contract at an eligible observation.'], OPTION_HISTORY_UNAVAILABLE: ['Candidate option history unavailable', 'The history loader could not obtain complete candidate data. A run selecting this contract will fail.'], ATR_WARMUP_UNAVAILABLE: ['ATR warmup history unavailable', 'The five-minute ATR warmup request failed. Each strategy still applies its own actual history requirements.'], BACKTEST_WARNING: ['Historical data warning', 'Read the recorded warning. Without a structured warning code, its specific cause cannot be classified safely.'], BACKTEST_REPLAY_ERROR: ['Backtest failed', 'The replay could not complete. The recorded message is shown without guessing missing decision values.'] }],
  ['backtesting/candle-limitations', { CANDLE_APPROXIMATION: ['Candle execution approximation', 'OHLC does not reveal intraminute order. Stop priority and partial-entry policy are explicit modelling assumptions.'] }],
  ['zerodha/connection', { CONNECTION_STATUS: ['Connection state', 'Broker authentication, market-data socket and browser feed are separate states.'], CONNECTION_ERROR: ['Connection error', 'A recorded connection error is available. Its underlying cause is not guessed from message text.'] }],
];
export const reasonToHelp = Object.assign(Object.create(null), Object.fromEntries(groups.flatMap(([topicId, reasons]) => Object.entries(reasons).map(([code, [title, why]]) => [code, { topicId, title, why }]))));
export function eventReason(event = {}, trade = {}) {
  const payload = event.payload ?? event;
  // Event reasons override generic event types, but never borrow a later exit
  // reason for an earlier protection update.
  const code = payload.reason_code ?? payload.rejection_reason ?? payload.failure_reason ?? (reasonToHelp[payload.reason] ? payload.reason : undefined);
  if (code) return code;
  if (['POSITION_CLOSED', 'TRADE_EXITED', 'TRADE_EXIT', 'STOP_LOSS_HIT'].includes(event.event_type)) return payload.exit_reason ?? trade.exit_reason ?? event.event_type;
  return event.event_type ?? 'UNKNOWN_REASON';
}
const present = v => v !== null && v !== undefined && v !== '';
const number = v => typeof v === 'number' && Number.isFinite(v);
export function explainDecision({ code, trade, signal, entry, event, level, currentPrice, armDistance, connection, run, message } = {}) {
  const t = trade ?? {}, e = event?.payload ?? event ?? {}, ctx = entry?.decision_context ?? signal?.decision_context ?? trade?.decision_context ?? {};
  const snapshot = t.strategy_config_snapshot ?? ctx.strategy_config_snapshot ?? {};
  const plan = t.strategy3_entry ?? ctx.strategy3_entry ?? {};
  const settings = plan.frozen_strategy_settings ?? snapshot;
  const strategy = t.strategy_type ?? ctx.strategy_type;
  const stopSource = plan.stop_source ?? ctx.attempted_stop_source;
  const definition = reasonToHelp[code];
  const topicId = definition?.topicId ?? 'troubleshooting/unknown';
  const facts = [], calculations = [];
  const add = (label, value, kind = 'Recorded', required = false) => {
    if (present(value)) facts.push({ label, value: typeof value === 'object' ? JSON.stringify(value) : value, kind });
    else if (required) facts.push({ label, value: 'Unavailable — not recorded', kind: 'Unavailable' });
  };
  add('Reason code', code);
  add('Strategy at entry', strategy);
  if (signal) {
    add('Trigger price', signal.trigger_price); add('Level price', signal.level);
    add('Approach direction', signal.direction); add('Approach distance (points)', signal.approach_distance, 'Recorded', true);
    add('Approach sample count', ctx.approach_sample_count);
    const frozen = ctx.settings_snapshot ?? {};
    add('Minimum approach filter enabled', frozen.minimum_approach_distance_enabled, 'Recorded', true);
    add('Minimum approach threshold (points)', frozen.minimum_approach_distance_points, 'Recorded', true);
    add('Lookback (minutes)', frozen.lookback_minutes, 'Recorded', true);
  }
  if (level) {
    add('Level state', level.status); add('Level trading date', level.level_date); add('Level price', level.price);
    add('Latest displayed underlying quote', currentPrice, 'Current observation', true);
    add('Current arm threshold (points)', armDistance, 'Current configuration', true);
    if (number(currentPrice) && number(level.price)) add('Current absolute distance (points)', Math.abs(currentPrice-level.price), 'Derived');
    calculations.push('These are current displayed values, not a reconstruction of the original arming event. A valid price greater than zero and sufficient distance are both required.');
  }
  if (['OPTION_ATR_UNAVAILABLE', 'INSUFFICIENT_PRE_ENTRY_CANDLES', 'ATR_FALLBACK', 'ATR_UNAVAILABLE_OR_INVALID', 'FIXED_PLAN', 'ATR_STOP_INVALID'].includes(code)) {
    add('Completed pre-entry candles', plan.pre_entry_candle_count ?? ctx.completed_candle_count, 'Recorded', true);
    add('Minimum required candles', settings.min_pre_entry_candles ?? ctx.required_candle_count, 'Recorded', true);
    add('Effective ATR sample count', plan.atr_sample_count);
    add('ATR candle timeframe', ctx.atr_candle_timeframe ?? (strategy === 'ATR_FIXED' ? '1 minute' : strategy === 'ATR' ? snapshot.atr_timeframe : undefined));
    add('Recorded stop source', plan.stop_source); add('Fallback reason', plan.fallback_reason);
  }
  if (entry) {
    add('Entry result', entry.status); add('Signal timestamp', ctx.signal_timestamp);
    add('Attempted execution timestamp', ctx.execution_timestamp ?? entry.timestamp);
    if (['BEFORE_TRADING_START', 'NEW_TRADE_CUTOFF_REACHED'].includes(code)) {
      add('Applied entry start (IST, inclusive)', ctx.trading_start_time, 'Recorded', true);
      add('Applied entry cutoff (IST, exclusive)', ctx.new_trade_cutoff_time, 'Recorded', true);
    }
  }
  const entryPrice = t.entry_price ?? ctx.entry_price;
  const atr = t.option_atr_at_entry ?? ctx.option_atr;
  const stop = t.initial_stop_loss ?? plan.initial_stop ?? ctx.initial_stop;
  if (trade || present(ctx.entry_price)) {
    add(entry?.status === 'FAILED' ? 'Attempted entry premium (₹)' : 'Entry premium (₹)', entryPrice); add('Option ATR at entry (₹)', atr);
    add('Initial stop (₹)', stop); add('Fixed target (₹)', plan.target);
    add('Quantity', t.quantity); add('Initial risk percent', t.initial_risk_percent ?? plan.initial_risk_pct ?? ctx.initial_risk_percent);
    add('Stop source', stopSource); add('Frozen fallback percentage', settings.fallback_sl_pct);
    add('Frozen risk/reward ratio', settings.risk_reward_ratio);
    add('Frozen maximum initial risk percent', settings.max_initial_risk_pct ?? settings.atr_max_sl_percent);
    add('Applied partial-entry policy', plan.applied_entry_candle_policy);
    const multiplier = strategy === 'ATR_FIXED' ? settings.atr_multiplier : strategy === 'ATR' ? settings.atr_initial_multiplier : undefined;
    add('Frozen initial ATR multiplier', multiplier);
    if (stopSource === 'FALLBACK' && number(entryPrice) && number(settings.fallback_sl_pct)) {
      calculations.push(`Derived check from recorded inputs: fallback stop = ${entryPrice} × (1 − ${settings.fallback_sl_pct} / 100) = ${format(entryPrice*(1-settings.fallback_sl_pct/100))}.`);
    } else if ((strategy === 'ATR' || (strategy === 'ATR_FIXED' && stopSource === 'ATR')) && number(entryPrice) && number(atr) && number(multiplier)) {
      calculations.push(`Derived check from recorded inputs: ATR stop = ${entryPrice} − (${atr} × ${multiplier}) = ${format(entryPrice-atr*multiplier)}.`);
    } else if (strategy === 'LEGACY') {
      const pct = snapshot.stop_strategy === 'PROGRESSIVE' ? snapshot.initial_stop_loss_pct : snapshot.stop_loss_percentage;
      add('Frozen initial stop percent', pct);
      if (number(pct) && number(entryPrice)) calculations.push(`Derived check: percentage stop = ${entryPrice} × (1 − ${pct} / 100) = ${format(entryPrice*(1-pct/100))}.`);
    }
    if (number(entryPrice) && number(stop) && number(settings.risk_reward_ratio) && strategy === 'ATR_FIXED') calculations.push(`Derived check: target = ${entryPrice} + (${entryPrice} − ${stop}) × ${settings.risk_reward_ratio} = ${format(entryPrice+(entryPrice-stop)*settings.risk_reward_ratio)}.`);
    if (number(entryPrice) && number(stop)) add('Initial risk per unit (₹)', entryPrice-stop, 'Derived');
    const selection = ctx.strategy_selection ?? t.settings_snapshot?.exit_selection;
    if (code === 'STRATEGY_SELECTED') add('Winning override source', selection?.source, 'Recorded', true);
    if (['TRAILING_STOP_LOSS', 'TRAILING_STOP_UPDATED', 'TRAILING_UPDATED', 'STOP_UPDATED', 'TRAILING_STEP_CHANGED', 'BREAKEVEN_PROTECTION_ACTIVATED', 'BREAKEVEN_ACTIVATED', 'PROFIT_LOCK_ACTIVATED'].includes(code)) {
      add('Event price (₹)', e.price ?? e.option_price, 'Recorded', true);
      add('Event previous stop (₹)', e.previous_stop, 'Recorded', true);
      add('Event effective stop (₹)', e.current_stop, 'Recorded', true);
      add(event?.payload ? 'Timeline-reported high (may be reconstructed)' : 'Event highest premium (₹)', e.highest_price); add('Event trailing percent', e.trailing_pct); add('Event trailing step', e.trailing_step);
      add('Frozen trailing mode', snapshot.atr_trailing_mode ?? snapshot.stop_strategy);
      add('Frozen trailing percentage', snapshot.atr_trailing_percentage ?? snapshot.trailing_stop_percentage);
      add('Frozen trailing ATR multiplier', snapshot.atr_trailing_multiplier);
      add('Frozen breakeven activation mode', snapshot.atr_breakeven_activation_mode);
      add('Frozen breakeven activation threshold', snapshot.atr_breakeven_activation_threshold ?? snapshot.breakeven_activation_percent);
      add('Frozen profit-lock trigger percent', snapshot.profit_lock_trigger_pct);
      const activationCode = ['BREAKEVEN_PROTECTION_ACTIVATED', 'BREAKEVEN_ACTIVATED', 'PROFIT_LOCK_ACTIVATED'].includes(code);
      if (activationCode && number(entryPrice)) {
        let activationDistance;
        const progressive = code === 'PROFIT_LOCK_ACTIVATED' || snapshot.stop_strategy === 'PROGRESSIVE';
        if (progressive && number(snapshot.profit_lock_trigger_pct)) {
          activationDistance = entryPrice*snapshot.profit_lock_trigger_pct/100;
          add('Frozen profit-lock percent', snapshot.profit_lock_pct);
          if (number(snapshot.profit_lock_pct)) add('Derived profit-lock premium (₹)', entryPrice*(1+snapshot.profit_lock_pct/100), 'Derived');
        } else if (strategy === 'ATR') {
          const threshold = snapshot.atr_breakeven_activation_threshold;
          const mode = snapshot.atr_breakeven_activation_mode;
          if (number(threshold)) {
            if (mode === 'PERCENTAGE') activationDistance = entryPrice*threshold/100;
            if (mode === 'ATR' && number(atr)) activationDistance = atr*threshold;
            if (mode === 'R' && number(stop)) activationDistance = (entryPrice-stop)*threshold;
          }
        } else if (strategy === 'LEGACY' && number(snapshot.breakeven_activation_percent)) {
          activationDistance = entryPrice*snapshot.breakeven_activation_percent/100;
        }
        if (number(activationDistance)) add('Derived activation premium (₹)', Number((entryPrice+activationDistance).toFixed(8)), 'Derived');
      }
      // A candidate is arithmetic, not a claim that this candidate won the max.
      if (number(e.highest_price) && !event?.payload) {
        const pct = e.trailing_pct ?? (strategy === 'ATR' ? (snapshot.atr_trailing_mode === 'PERCENTAGE' ? snapshot.atr_trailing_percentage : undefined) : snapshot.trailing_stop_percentage);
        if (number(pct)) add('Derived trailing candidate (₹)', Number((e.highest_price*(1-pct/100)).toFixed(8)), 'Derived');
        else if (strategy === 'ATR' && snapshot.atr_trailing_mode === 'ATR' && number(atr) && number(snapshot.atr_trailing_multiplier)) add('Derived ATR trailing candidate (₹)', e.highest_price-atr*snapshot.atr_trailing_multiplier, 'Derived');
      }
      calculations.push('A final trade high/stop is not substituted for missing event-time values. The article explains candidate precedence; this record may not identify the winning candidate.');
    }
    if (['MARKET_CLOSE', 'MARKET_CLOSING_EXIT', 'MARKET_CLOSING_EXIT_TRIGGERED', 'EOD', 'MANDATORY_EXIT'].includes(code)) {
      add('Frozen Strategy 3 EOD cutoff (IST)', strategy === 'ATR_FIXED' ? snapshot.eod_exit_time : undefined);
      calculations.push(strategy === 'ATR_FIXED' ? 'Strategy 3 uses its frozen EOD cutoff.' : 'Generic PAPER mandatory-exit settings can change while a position is open. An entry snapshot alone does not establish the exit-time deadline.');
    }
    if (['STOP_LOSS', 'TRAILING_STOP_LOSS', 'SL'].includes(code)) add('Final recorded effective stop (₹)', t.current_stop_loss);
    if (!event || ['POSITION_CLOSED', 'TRADE_EXITED', 'TRADE_EXIT', 'STOP_LOSS_HIT', 'MARKET_CLOSING_EXIT_TRIGGERED'].includes(event.event_type)) {
      add('Recorded exit reason', t.exit_reason); add('Recorded exit price (₹)', t.exit_price); add('Recorded exit timestamp', t.exit_time);
    }
  }
  if (event) {
    add('Event type', event.event_type); add('Event timestamp', event.timestamp); add('Recorded event price (₹)', e.price ?? e.option_price);
    add('Recorded event previous stop (₹)', e.previous_stop); add('Recorded event effective stop (₹)', e.current_stop);
    add('Recorded event underlying level', e.level); add('Recorded event rejection', e.rejection_reason); add('Recorded event exit reason', e.exit_reason);
    if (event.event_type === 'LEVEL_ARMED') {
      add('Applied initial arm threshold (points)', e.initial_arm_distance_points, 'Recorded', true);
      if (number(e.price) && number(e.level)) add('Recorded arming distance (points)', Math.abs(e.price-e.level), 'Derived');
    }
  }
  if (connection) {
    add('Market data mode', connection.market_data_mode); add('Authentication state', connection.auth_status);
    add('Broker socket state', connection.connection_status); add('Last tick received', connection.last_tick_at);
    add('Instrument sync state', connection.instrument_sync_status); add('Auth error code', connection.auth_error?.code);
  }
  if (run) {
    add('Run state', run.status); add('Data source', run.data_source); add('Data resolution', run.data_resolution);
    add('Execution model', run.execution_model); add('Frozen partial-entry policy', run.settings_snapshot?.strategy3_configuration?.entry_candle_policy);
  }
  add('Recorded message', message);
  return { topicId, topic: helpRegistry[topicId], title: definition?.title ?? 'Decision details unavailable',
    why: definition?.why ?? 'This code has no documented decision mapping. Its values are shown without assigning an inferred explanation.',
    facts, calculations, missing: facts.some(f => f.kind === 'Unavailable') || (!trade && !signal && !entry && !level && !connection && !run) };
}
function format(value) { return Number.isFinite(value) ? Number(value.toFixed(8)).toString() : 'unavailable'; }

for (const code of ['API_KEY_MISSING', 'API_SECRET_MISSING', 'LOGIN_ATTEMPT_MISSING', 'LOGIN_EXPIRED', 'LOGIN_STATE_MISSING', 'LOGIN_COOKIE_MISSING', 'LOGIN_STATE_MISMATCH', 'LOGIN_DECLINED', 'REQUEST_TOKEN_MISSING', 'CREDENTIALS_MISSING', 'CREDENTIAL_WHITESPACE', 'TOKEN_EXCHANGE_NETWORK_ERROR', 'INVALID_CHECKSUM', 'REQUEST_TOKEN_REJECTED', 'API_KEY_REJECTED', 'TOKEN_EXCHANGE_REJECTED', 'TOKEN_RESPONSE_INVALID', 'SESSION_SAVE_FAILED', 'LOGIN_FAILED']) {
  reasonToHelp[code] = { topicId: 'zerodha/connection', title: 'Zerodha authentication issue', why: 'The authentication flow returned this code. The recorded credential-free message identifies the specific issue and recommended next step.' };
}

const aliases = { SIGNAL_GENERATED: 'SIGNAL_ACCEPTED', TRADE_ENTRY: 'POSITION_OPENED', TRADE_EXIT: 'POSITION_CLOSED', TRADE_TRIGGERED: 'OPTION_SELECTED', LEVEL_TOUCH: 'LEVEL_TRIGGERED', LEVEL_CROSS: 'LEVEL_TRIGGERED' };
reasonToHelp.LEVEL_TRIGGERED = { topicId: 'signals/touch-cross', title: 'Level touched or crossed', why: 'The eligible level was touched or crossed at the recorded underlying observation.' };
reasonToHelp.SIGNAL_REJECTED = { topicId: 'signals/approach', title: 'Signal rejected', why: 'The event records a rejected signal. A missing detailed reason cannot be reconstructed from the outcome.' };
for (const [code, alias] of Object.entries(aliases)) reasonToHelp[code] = reasonToHelp[alias];
