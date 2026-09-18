# 2026-09-17: RAW PAPER versus corrected replay

Status: RAW baseline retrieved; corrected replay pending historical tick data and confirmation of the correction.

Source: `https://stockpi.vkotian.com/api/trades/history`, pages 1 and 2 with page size 100. Retrieved 2026-09-18T03:43:31.759708+00:00. All 159 unique trades were returned; each is PAPER and entered on 2026-09-17 in Asia/Kolkata.

Scope: entry-day cohort, using each trade’s recorded outcome. This is not a reconstruction of intraday marked-to-market equity. The server response has no classification or version fields; RAW includes every record regardless. No server records were changed.

| Metric | RAW PAPER | Corrected BACKTEST |
| --- | ---: | --- |
| Recorded trades | 159 | Pending |
| Open | 0 | Pending |
| Closed | 159 | Pending |
| Wins | 77 | Pending |
| Losses | 82 | Pending |
| Breakeven | 0 | Pending |
| Win rate (%) | 48.43 | Pending |
| Gross profit | 155,788.75 | Pending |
| Gross loss | 62,699.00 | Pending |
| Net P&L | 93,089.75 | Pending |
| Profit factor | 2.48 | Pending |

Win rate excludes breakeven trades. Gross loss is a positive amount. Realised metrics use CLOSED trades, following the shared reporting implementation.

## Entry concentration

| Trigger level | Recorded entries |
| --- | ---: |
| 23231 | 10 |
| 23280 | 148 |
| 23361 | 1 |

Repeated entries are evidence to investigate, not sufficient on their own to classify each trade as invalid. Do not treat deduplicating these rows as a corrected backtest: a skipped entry changes subsequent level state and option exposure.

## Replay inputs still needed

- Timestamped underlying and option tick history, plus instrument metadata for the actual contracts traded.
- The day’s original levels/settings and starting state, including any carried positions.
- Confirmation that the level-rearming correction is the intended fix, and the time it was deployed that day.

The current runner selects synthetic contracts and begins with fresh level state. A faithful real-market replay must address those differences. The existing source code stores a bounded in-memory underlying history and latest option quotes; those are not a full historical tick archive. Server-side archives have not yet been inspected.

See [strategy-changelog.md](strategy-changelog.md) for the version baseline and replay status.
