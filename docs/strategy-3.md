# Strategy 3: fixed ATR stop and risk/reward target

Select **Strategy 3 · ATR fixed SL / target** in Exit Strategy settings or Backtest.
Its API identifier is `ATR_FIXED`. Entry signals, option selection and sizing keep
using the existing engine. Existing `LEGACY` and five-minute Wilder `ATR`
strategies retain their own rules. Execution remains PAPER or isolated BACKTEST.

## Calculation and data

Option candle timestamps are timezone-aware **minute start times**, normalized to
Asia/Kolkata. ATR uses completed candles ending at/before the actual trade entry;
the entry price comes from the execution/trade record. Sort order does not affect
results. The first candle has no TR; across a missing minute no previous close is
invented. Use the latest available valid TRs (up to the period) and their simple
mean. Fifteen contiguous candles supply fourteen TRs. Gaps are recorded in
`data_quality_warnings`; duplicate timestamps, contract mismatches, invalid OHLC,
and naive/misaligned timestamps are rejected.

Defaults:

```json
{
  "atr_period": 14,
  "atr_multiplier": 0.75,
  "atr_method": "SMA",
  "min_pre_entry_candles": 2,
  "fallback_sl_pct": 20,
  "risk_reward_ratio": 2,
  "eod_exit_time": "15:25:00",
  "max_initial_risk_pct": null,
  "slippage_model": "none",
  "entry_candle_policy": "SKIP_PARTIAL_ENTRY_CANDLE"
}
```

`stop = entry - ATR * multiplier`; invalid ATR/history/stop uses the percentage
fallback. Invalid fallback rejects entry. A configured maximum initial risk
rejects an over-limit entry without tightening its stop. `target = entry +
(entry - stop) * risk_reward_ratio`. Both levels and the settings are frozen in
`strategy3_entry` / `strategy_config_snapshot`, including the EOD deadline. There
is no trailing, breakeven adjustment, partial exit or other automatic exit signal.
Existing explicit manual square-off controls remain available.

PAPER receives observed option quotes and can fetch read-only completed minute
history from Zerodha before entry. Simulated/recorded quotes also build minute
buckets; these represent observed samples, not complete exchange OHLC. Inadequate
history uses fallback. PAPER SL/target fills use the observed quote. At/after EOD,
PAPER waits for a real quote rather than inventing a historical close.

## Backtest API

`POST /backtests/run` (or `/backtests/jobs`) accepts existing session, levels,
contract catalogue and tick inputs, plus:

```json
{
  "exit_strategy": "ATR_FIXED",
  "strategy3_configuration": {
    "atr_multiplier": 0.75,
    "risk_reward_ratio": 2,
    "eod_exit_time": "15:25"
  },
  "minute_candles": [
    {
      "symbol": "EXACT-OPTION-CONTRACT-SYMBOL",
      "timestamp": "2026-10-20T10:00:00+05:30",
      "open": 100,
      "high": 104,
      "low": 98,
      "close": 101,
      "volume": 1000
    }
  ]
}
```

This is a fragment to add to the existing backtest request, not a complete
request. Supply pre-entry history and post-entry coverage for the selected
contract. JSON archive/upload files support the same `minute_candles` array.
Zerodha historical replay already supplies one-minute candles. Do not pass the
old five-minute `candles` array as Strategy 3 minute history.

Minute exits evaluate low <= stop first, then high >= target. A same-candle
collision exits at SL. Theoretical SL/target fill prices are their fixed levels;
EOD uses the close of the candle completing at the configured cutoff. Candles
after cutoff are excluded. A partial entry minute is skipped by default;
`FULL_CANDLE_APPROXIMATION` explicitly enables the compatibility approximation.
Actual tick observations can trigger exits chronologically after entry.

Missing post-entry minutes or missing cutoff coverage produce `DATA_INCOMPLETE`
with an explicit reason. An unclosed trade keeps null exit/P&L fields and receives
`simulation_status: DATA_INCOMPLETE`; no close is fabricated. Incomplete jobs
remain viewable as saved results. Invalid duplicate candles reject the request.

Results include the full frozen entry plan (ATR, sample count, source/fallback
reason, stop distance, target, risk, entry policy, warnings/settings), actual
entry/exit timestamps, SL/TARGET/EOD reasons, quantity, gross/net P&L, holding
seconds, and gross realized R-multiple. Flat `transaction_cost_per_order` is
charged separately per entry and exit; no brokerage/tax schedule or executable
OHLC pricing is assumed. Aggregate average R retains the existing net-cost
reporting convention. The existing seven-run Legacy/ATR-multiplier comparison
remains available; run Strategy 3 using its separate selection.

## Reuse with trade records

`app.fixed_atr.simulate_trade(...)` accepts an actual entry price/time, quantity,
trade ID, instrument, exact option symbol, candles and `FixedAtrSettings`.
It returns CLOSED, REJECTED or DATA_INCOMPLETE, including explicit reasons and
quality warnings. Brokerage, taxes, slippage cost and other fees are independent
nonnegative cost inputs. `entry_plan` and `candle_exit` are shared with the
platform. There are no broker, database or clock dependencies in this module.

Tests: `cd backend && .venv/bin/python -m pytest tests/test_fixed_atr.py -q`.
