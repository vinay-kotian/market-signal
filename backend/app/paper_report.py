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

    def report(self, view="STRATEGY"):
        rows = self.trades.paper_results()
        return calculate_report(rows, view)


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
