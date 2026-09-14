Read AGENTS.md and agents/ui-agent.md.

Design the simplest UI for the current milestone.

We only need two screens:

1. Dashboard
2. Levels

## Dashboard

Show:

* Instrument
* Current simulated price
* Configured levels
* Distance from current price
* Status: WAITING / TRIGGERED / DISABLED

Add a small simulation control for development:

* Instrument selector
* Price input
* "Send Tick" button

Do not add charts.

Do not add trading controls, option information, stop loss, P&L, or Zerodha.

## Levels

Allow:

* View levels
* Add level
* Edit level
* Enable/disable level
* Delete level

Keep forms compact and simple.

## UI principles

* Minimal
* Clean
* Modular
* Tables over excessive cards
* Avoid unnecessary navigation
* Reusable components
* Responsive but desktop-first
* Clearly show state without excessive decoration

Provide:

1. Page layout
2. Components required
3. User flow
4. Loading / empty / error states
5. Suggested frontend folder structure

Do not implement code yet.
