# MARKET SIGNAL - AGENTS.md

## Project Overview

This is a production-grade trading signal and paper-trading platform focused on options BUYING strategies.

The platform:
- Tracks live prices using Kite WebSocket
- Allows users to define daily levels for instruments
- Detects level touches
- Executes paper trades based on strategy rules
- Maintains trailing stoploss logic
- Exits trades before EOD if targets are not achieved
- Captures market direction and velocity
- Supports future AI and LangGraph integration

IMPORTANT:
- System runs in PAPER_TRADING mode initially
- Real trading is disabled by default
- This system is strictly OPTIONS BUYING ONLY
- Fresh option selling is strictly forbidden

---

# Core Tech Stack

Backend:
- FastAPI
- Python
- SQLAlchemy
- SQLite initially

Frontend:
- React
- Tailwind
- daisyUI

Broker:
- Zerodha Kite

Architecture:
- Modular multi-agent architecture
- Event/workflow driven
- LangGraph-ready for future migration

---

# Architecture Principles

1. Keep strategy deterministic
2. Separate strategy from execution
3. Keep agents isolated
4. Keep workflows modular
5. Use DTO-based communication
6. Every decision must be auditable
7. Design system to be LangGraph-ready later
8. Avoid tight coupling
9. Keep broker integration isolated
10. Safety over aggressiveness

---

# Current Architecture

Current architecture is NOT using LangGraph.

The system uses:
- FastAPI
- SQLite
- SQLAlchemy
- React
- Tailwind
- daisyUI

Workflows are orchestrated manually using workflow classes.

Future migration to LangGraph should be easy.

---

# Main Workflow

Tick
→ MarketAgent
→ LevelAgent
→ StrategyAgent
→ RiskAgent
→ TradeExecutionAgent
→ PaperTradingAgent / BrokerClient
→ AuditAgent

Workflow orchestration happens in:

app/workflows/tick_workflow.py

---

# Agent Architecture

Agents are logical modules with isolated responsibilities.

Agents MUST NOT tightly couple with each other.

Agents communicate only using DTOs and workflow orchestration.

---

# Agent Contract Rules

Every agent must have a narrow contract.

- MarketAgent emits MarketContext only
- LevelAgent emits LevelContext only
- StrategyAgent emits StrategySignal only
- RiskAgent emits RiskDecision only
- TradeExecutionAgent emits TradeAction / ExecutionResult only
- PaperTradingAgent updates simulated orders, positions, trades, and P&L only
- AuditAgent records DTOs, decisions, signals, executions, and state changes

IMPORTANT:
- Market data must not know strategy rules
- Strategy must not execute trades
- Paper trading must not decide signals
- Risk must not rewrite strategy intent
- UI must not contain trading rules
- Tests must prove every trading rule with deterministic data

---

# Agents

## MarketAgent

Responsibilities:
- Process live/mock ticks
- Detect direction
- Detect velocity
- Normalize tick data
- Generate MarketContext

Must NOT:
- Place trades
- Access UI
- Contain strategy logic
- Detect strategy-specific level touches

---

## LevelAgent

Responsibilities:
- Fetch active daily levels
- Validate level structure
- Prepare level context

Must NOT:
- Make trade decisions

---

## StrategyAgent

Responsibilities:
- Evaluate strategy-specific level touches
- Generate BUY / SELL / HOLD signals
- Manage trailing stoploss logic
- Implement L0/L1/L2/L3 logic
- Generate StrategySignal

Rules:
- L1 is the entry price and creates BUY signal when reached from either direction
- L0 remains the initial protective stoploss/reference after confirmed entry
- Do not automatically move L0 by a fixed percentage after entry
- Trailing stoploss activates only after L1 entry and confirmed order
- StrategySignal must capture whether price came to L1 from above or from below
- Upper levels become progressive target checkpoints
- If multiple upper levels exist, intermediate target breaches should not auto-sell
- On each upper target breach, keep tracking the next higher level and tighten trailing stoploss
- Trailing stoploss must protect profit
- Emit EOD_EXIT signal before square-off time when position is still open

Must NOT:
- Access database directly
- Place orders
- Call broker APIs

---

## RiskAgent

Responsibilities:
- Validate signals
- Prevent duplicate trades
- Prevent excessive losses
- Validate EOD exit signals
- Validate trading windows
- Validate option rules
- Generate RiskDecision

Must reject:
- Fresh option SELL orders
- Short option positions
- Naked option selling
- Invalid lot sizes
- Excessive quantity
- Duplicate trades

Must allow:
- BUY CE
- BUY PE
- SELL only for closing existing bought positions

Must NOT:
- Modify strategy rules

---

## TradeExecutionAgent

Responsibilities:
- Execute approved trades
- Route orders to PaperBrokerClient initially
- Support ZerodhaBrokerClient later
- Maintain order lifecycle
- Store broker responses
- Handle failures safely

Must NOT:
- Create strategy signals
- Bypass RiskAgent
- Place live orders if disabled
- Create paper-trading state directly

IMPORTANT:
TradeExecutionAgent must NEVER place a SELL order unless it is closing an existing bought option position.

---

## PaperTradingAgent

Responsibilities:
- Simulate trades
- Maintain positions
- Update P&L
- Close trades
- Maintain trade lifecycle
- Apply simulated fills, slippage, and brokerage assumptions

Must NOT:
- Decide strategy
- Call Zerodha or any live broker API

---

## AuditAgent

Responsibilities:
- Store all decisions
- Store all signals
- Store all trade events
- Maintain full audit trail

Audit logs are mandatory.

---

## BacktestAgent

Responsibilities:
- Replay historical/mock ticks
- Validate strategy behaviour
- Generate P&L reports
- Measure win/loss ratio
- Measure drawdown

---

## QAAgent

Responsibilities:
- Generate edge-case market conditions
- Validate workflows
- Validate strategy correctness

Test scenarios:
- L1 buy trigger
- L0 is used as the initial protective stoploss after entry
- Trailing stoploss moves upward during favorable movement
- Trailing stoploss never moves downward for an open long position
- Duplicate BUY signal is rejected while a position is open
- SELL_TO_OPEN is rejected
- EOD exit only happens for open positions
- Fast breakout
- Sudden reversal
- Gap up
- Gap down
- False breakout
- Sideways market
- Stoploss hit
- EOD square-off

---

# Trading Mode

The system must support two trading modes:

1. PAPER_TRADING
2. LIVE_TRADING

Default mode must always be:

PAPER_TRADING

LIVE_TRADING must be disabled unless explicitly enabled through configuration.

Required config:

TRADING_MODE=PAPER
ENABLE_LIVE_TRADING=false
BROKER=ZERODHA

---

# Broker Integration

Broker integration must be isolated.

Create a broker abstraction:

- BrokerClient interface
- PaperBrokerClient
- ZerodhaBrokerClient

Hosted Zerodha session design:
- KITE_API_KEY and KITE_API_SECRET live in server environment
- Daily access tokens must be created through /zerodha/login or /zerodha/callback
- Daily access tokens must be stored in broker_sessions, not manually edited into .env
- /zerodha/status must report whether today's DB session is active
- /zerodha/logout must deactivate today's active session

StrategyAgent and RiskAgent must NEVER call Zerodha directly.

Only TradeExecutionAgent can call broker clients.

---

# Options Trading Rules

The system is OPTIONS BUYING ONLY.

Allowed:
- Buy CE
- Buy PE
- Sell only to close an existing bought position

Not allowed:
- Fresh option selling
- Short option positions
- Naked option selling
- Sell-to-open trades

Allowed flows:

BUY_TO_OPEN:
- Allowed for CE and PE

SELL_TO_CLOSE:
- Allowed only if an existing open BUY position exists

SELL_TO_OPEN:
- Strictly forbidden

---

# Strategy Rules

For every instrument:
- There can be N levels
- Levels are valid for a trading day
- Levels can be added/updated/deleted daily

Level logic:

L0:
- Initial resistance/reference level
- Becomes stoploss reference after entry

L1:
- BUY entry price and trailing-stop activation threshold
- BUY is valid when price reaches L1 from below or from above

L2/L3/L4:
- Progressive target checkpoints
- Intermediate targets should tighten trailing stoploss, not force an automatic sell
- Strategy should continue testing the next higher configured level while the position remains open

Level touch definition:
- A level is touched when last_price equals the level price within tick-size tolerance
- A level is also touched when price crosses the level between two consecutive ticks
- Touch detection belongs to StrategyAgent because it depends on strategy rules

L1 entry definition:
- L1 is reached when last_price equals L1 within tick-size tolerance
- L1 is also reached when price crosses L1 between two consecutive ticks
- Entry is valid whether price reaches L1 from below or from above
- If price moves from below L1 to L1 or above, entry_approach_direction is BELOW_TO_L1
- If price moves from above L1 to L1 or below, entry_approach_direction is ABOVE_TO_L1
- If first observed price is already at L1, entry_approach_direction is UNKNOWN_AT_LEVEL
- StrategySignal must include entry_approach_direction and entry_velocity
- Trailing stoploss must not activate before L1 is reached and entry is confirmed

When price reaches L1:
- Generate BUY signal
- RiskAgent validates the BUY signal
- TradeExecutionAgent routes approved action to PaperTradingAgent in PAPER_TRADING mode
- After confirmed entry, use L0 as the initial protective stoploss/reference
- Do not apply any automatic 50% L0 adjustment
- Activate trailing stoploss from that point onward
- Reset upper target checkpoint tracking at entry; only post-entry target moves count

Trailing stoploss:
- Must be configurable by fixed points, percentage, ATR, or level-based distance
- Must activate only after L1 is reached and entry is confirmed
- Must use L0 as the first stoploss value unless strategy config explicitly overrides it
- Must trail from the post-entry high-water mark for long positions
- Must move upward with favorable movement
- Must never move downward for an open long position
- Must tighten when an upper target checkpoint is breached
- Must allow the position to continue toward higher configured targets
- Must emit an audit event every time it changes

Upper target handling:
- If only one upper target exists, exit behavior must follow strategy configuration
- If multiple upper targets exist, L2/L3/etc. are checkpoints unless explicitly configured otherwise
- Breaching an intermediate target must emit TARGET_CHECKPOINT_REACHED and update trailing stoploss
- The strategy must then continue monitoring the next higher target
- SELL or PARTIAL_SELL should occur only when strategy config explicitly enables target exit, final target exit, trailing stoploss hit, stoploss hit, or EOD exit

EOD rule:
- Exit all open trades before market close
- Maximize profit or minimize loss at EOD
- StrategyAgent emits EOD_EXIT
- RiskAgent validates EOD_EXIT timing and position state
- TradeExecutionAgent executes the exit through PaperTradingAgent or BrokerClient
- No position should remain open after configured square-off time

---

# Market Rules

MarketAgent must:
- Track direction
- Track velocity
- Detect rapid movement
- Support live and mock ticks

Velocity examples:
- FAST_UP
- SLOW_UP
- FAST_DOWN
- SIDEWAYS

---

# DTO Rules

Agents communicate only using DTOs.

Required DTOs:
- Tick
- MarketContext
- LevelContext
- StrategySignal
- RiskDecision
- TradeAction
- ExecutionResult
- AgentEvent

---

# Database Rules

SQLite initially.

Tables:
- instruments
- daily_level_sets
- levels
- ticks
- orders
- paper_trades
- positions
- trade_events
- audit_logs
- strategy_runs
- strategy_configs
- backtest_results

Database rules:
- Levels must belong to a daily_level_set
- daily_level_sets must include instrument, trading_day, status, created_by, and updated_by
- Level updates and deletes must be audit logged
- SQLite is acceptable initially, but repositories must keep migration to PostgreSQL simple

---

# UI Requirements

Frontend:
- React
- Tailwind
- daisyUI

Dashboard should include:
- Instrument management
- Level management
- Live prices
- Open trades
- Trade history
- P&L
- Strategy events
- Risk events
- Trading mode
- System health

---

# Parallel Coding Boundaries

Agents can work in parallel only when they stay inside their ownership boundaries.

Backend/API ownership:
- backend/app/api/
- backend/app/db/
- backend/app/models/
- backend/app/schemas/

Market ownership:
- backend/app/market/
- backend/app/broker/kite_market_data.py

Strategy ownership:
- backend/app/strategy/
- backend/app/dto/strategy_dto.py

Risk ownership:
- backend/app/risk/

Trading execution ownership:
- backend/app/trading/
- backend/app/broker/

Backtesting and QA ownership:
- backend/app/backtesting/
- backend/tests/

Frontend ownership:
- frontend/

Documentation ownership:
- README.md
- docs/
- AGENTS.md

IMPORTANT:
- Agents must not rewrite files owned by another active agent unless the task explicitly requires integration.
- Shared DTOs must be changed carefully because they affect multiple agents.
- Any DTO contract change must be reflected in tests.

---

# Deterministic Testing Requirements

Every strategy rule must be covered with deterministic tick data.

Required tests:
- L1 reached from below emits BUY signal exactly once
- L1 reached from above emits BUY signal exactly once
- StrategySignal captures BELOW_TO_L1 entry approach direction
- StrategySignal captures ABOVE_TO_L1 entry approach direction
- L0 is used as the initial protective stoploss after confirmed entry
- No automatic 50% L0 adjustment is applied
- Trailing stoploss does not activate before L1 entry
- Trailing stoploss activates after L1 is reached and entry is confirmed
- Upper target checkpoints are reset at entry and only post-entry target moves count
- Trailing stoploss moves upward when high-water mark increases
- Trailing stoploss never moves downward
- Intermediate upper target breach emits TARGET_CHECKPOINT_REACHED when higher targets remain
- Intermediate upper target breach tightens trailing stoploss instead of auto-selling
- Strategy continues testing the next higher configured level after an intermediate target breach
- Final target behavior follows strategy configuration
- Stoploss hit emits SELL
- EOD_EXIT emits only before configured square-off time
- EOD_EXIT does not emit when no position is open
- Duplicate open position is rejected by RiskAgent
- SELL_TO_OPEN is rejected by RiskAgent
- BUY CE and BUY PE are allowed
- SELL_TO_CLOSE is allowed only for an existing bought position
- Velocity and direction calculations are stable for fast, slow, and sideways ticks

---

# Future AI Scope

Future AI integrations may include:
- LangGraph orchestration
- AI-based anomaly detection
- AI-assisted risk analysis
- Pattern recognition
- Strategy optimization
- Market summaries
- AI-generated backtest insights

IMPORTANT:
AI should assist workflows and analysis.
AI should NOT directly place uncontrolled trades.

---

# Coding Rules

1. Keep modules small
2. Add tests for all strategy logic
3. Use typing everywhere
4. Avoid tight coupling
5. Keep services reusable
6. Avoid business logic inside APIs
7. Use environment variables for secrets
8. Keep broker integration isolated
9. Add logs for all major decisions
10. Keep architecture production-ready
11. Prefer async architecture where useful
12. Keep services LangGraph-ready

---

# Important Safety Rules

- Real trading disabled by default
- All trades must be auditable
- Strategy decisions must be explainable
- Add kill switch support later
- Add max daily loss later
- Add circuit breaker later
- Never allow fresh option selling
- Never bypass RiskAgent
- Never allow direct StrategyAgent → Broker calls

---

# Folder Structure

backend/app/
  api/
  core/
  db/
  dto/
  agents/
  workflows/
  strategy/
  market/
  trading/
  risk/
  backtesting/
  broker/
  tests/

frontend/
  app/
  components/
  lib/

docs/

---

# Migration Goal

Current system should be easily migratable to:

MarketAgent Node
→ LevelAgent Node
→ StrategyAgent Node
→ RiskAgent Node
→ TradeExecutionAgent Node
→ PaperTradingAgent / BrokerClient Node
→ AuditAgent Node

inside LangGraph later.
