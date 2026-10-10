"""Run-scoped realised performance; optional flat costs are separate from execution pricing."""
from decimal import Decimal

from app.paper_report import calculate_report, realised_risk_metrics


def backtest_summary(trades, transaction_cost_per_order=None):
    fee = Decimal(str(transaction_cost_per_order or 0))
    report = calculate_report([dict(status=t.status, realised_pnl=float(Decimal(str(t.realised_pnl))-2*fee) if t.status == 'CLOSED' else None,
        exclude_from_strategy_metrics=False) for t in trades], view='RAW').model_dump(mode='json')
    closed = sorted((t for t in trades if t.status == 'CLOSED'), key=lambda t: (t.exit_time, t.trade_id))
    gross = [Decimal(str(t.realised_pnl)) for t in closed]
    pnls = [pnl-2*fee for pnl in gross]
    costs = fee * (2*len(closed) + len(trades)-len(closed))
    returns = [pnl / (Decimal(str(t.entry_price))*t.quantity)*100 for t, pnl in zip(closed, pnls)]
    capital = sum((Decimal(str(t.entry_price)) * t.quantity for t in closed), Decimal(0))
    total = sum(pnls, Decimal(0))
    risk_metrics = realised_risk_metrics([dict(initial_risk_amount=getattr(t, 'initial_risk_amount', None),
                                              exit_reason=getattr(t, 'exit_reason', None)) for t in closed], pnls)
    return {**report, 'win_rate': 100 * report['winning_trades'] / len(closed) if closed else 0,
        'wins': report['winning_trades'], 'losses': report['losing_trades'],
        'breakeven': report['breakeven_trades'], 'gross_pnl': float(sum(gross, Decimal(0))), 'net_pnl': float(sum(gross, Decimal(0))-costs),
        'transaction_costs': float(costs), **risk_metrics,
        'costs_supported': transaction_cost_per_order is not None, 'total_return_percent': float(total / capital * 100) if capital else 0,
        'average_pnl': float(total / len(closed)) if closed else 0,
        'average_return_percent': float(sum(returns, Decimal(0)) / len(closed)) if closed else 0,
        'best_trade': max((float(p) for p in pnls), default=None),
        'worst_trade': min((float(p) for p in pnls), default=None)}
