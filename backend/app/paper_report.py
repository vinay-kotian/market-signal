"""Read-only performance calculations from persisted PAPER positions."""
from decimal import Decimal
from typing import Optional, Literal

from pydantic import BaseModel


class PaperTradingReport(BaseModel):
    view: Literal["RAW", "STRATEGY"]
    recorded_trades: int
    included_trades: int
    excluded_trades: int
    total_trades: int
    open_trades: int
    closed_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_pnl: float
    average_profit: float
    average_loss: float
    maximum_profit: float
    maximum_loss: float
    profit_factor: Optional[float]


class PaperReportingService:
    def __init__(self, trades):
        self.trades = trades

    def report(self, view="STRATEGY", **filters):
        rows = self.trades.paper_results(**filters)
        return calculate_report(rows, view)

    def strategy_comparison(self, view='STRATEGY', **filters):
        # Compare both frozen entry strategies, independent of the history's
        # single-strategy selector, in one database snapshot.
        filters.pop('strategy_type', None)
        rows = self.trades.performance_rows(**filters)
        comparison = {}
        for strategy in ('LEGACY', 'ATR'):
            group = [row for row in rows if row['strategy_type'] == strategy]
            report = calculate_report(group, view).model_dump(mode='json')
            closed = [row for row in group if row['status'] == 'CLOSED'
                      and (view == 'RAW' or not row['exclude_from_strategy_metrics'])]
            pnls = [Decimal(str(row['realised_pnl'])) for row in closed]
            comparison[strategy] = {**report, **realised_risk_metrics(closed, pnls)}
        return dict(view=view, mode='PAPER', strategies=comparison,
                    costs_included=False, drawdown_basis='CLOSED_REALISED_PNL')

    def export_csv(self, **filters):
        from app.report_csv import CSV_FIELDS, csv_chunks
        # The report/history already use persisted trade results. Export those
        # exact values, including null results for OPEN trades.
        return csv_chunks(self.trades.export_rows(CSV_FIELDS, **filters))


def calculate_report(rows, view="STRATEGY"):
    if view not in ('RAW', 'STRATEGY'):
        raise ValueError('Unknown report view')
    recorded = len(rows)
    included = [row for row in rows if not row['exclude_from_strategy_metrics']]
    excluded = recorded - len(included)
    if view == 'STRATEGY':
        rows = included
    closed = [Decimal(str(row['realised_pnl'])) for row in rows if row['status'] == 'CLOSED']
    profits = [pnl for pnl in closed if pnl > 0]
    losses = [-pnl for pnl in closed if pnl < 0]
    decided = len(profits) + len(losses)
    gross_profit, gross_loss = sum(profits, Decimal(0)), sum(losses, Decimal(0))
    return PaperTradingReport(
        view=view, recorded_trades=recorded, included_trades=recorded - excluded, excluded_trades=excluded,
        total_trades=len(rows), open_trades=len(rows) - len(closed), closed_trades=len(closed),
        winning_trades=len(profits), losing_trades=len(losses),
        breakeven_trades=len(closed) - len(profits) - len(losses),
        win_rate=100 * len(profits) / decided if decided else 0,
        gross_profit=gross_profit, gross_loss=gross_loss, net_pnl=gross_profit - gross_loss,
        average_profit=gross_profit / len(profits) if profits else 0,
        average_loss=gross_loss / len(losses) if losses else 0,
        maximum_profit=max(profits, default=0), maximum_loss=max(losses, default=0),
        profit_factor=gross_profit / gross_loss if gross_loss else None,
    )


def realised_risk_metrics(closed, pnls):
    """Shared report/replay metrics over closed trades in exit-time order.

    Older trades with unknown entry risk remain in P&L/drawdown but cannot
    contribute a reconstructed R value.
    """
    equity = peak = drawdown = Decimal(0)
    rs = []
    for row, pnl in zip(closed, pnls):
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak-equity)
        risk = row['initial_risk_amount']
        if risk is not None and risk > 0:
            rs.append(pnl / Decimal(str(risk)))
    return dict(max_drawdown=float(drawdown),
                average_r=float(sum(rs, Decimal(0))/len(rs)) if rs else None,
                average_r_sample_size=len(rs),
                sl_hits=sum(row['exit_reason'] in ('STOP_LOSS', 'TRAILING_STOP_LOSS') for row in closed))
