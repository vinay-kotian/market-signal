"""Run-scoped realised performance; costs are not modelled in this version."""
from decimal import Decimal

from app.paper_report import calculate_report


def backtest_summary(trades):
    report = calculate_report([dict(status=t.status, realised_pnl=t.realised_pnl,
        exclude_from_strategy_metrics=False) for t in trades], view='RAW').model_dump(mode='json')
    closed = sorted((t for t in trades if t.status == 'CLOSED'), key=lambda t: (t.exit_time, t.trade_id))
    pnls = [Decimal(str(t.realised_pnl)) for t in closed]
    returns = [Decimal(str(t.realised_pnl_percentage)) for t in closed]
    capital = sum((Decimal(str(t.entry_price)) * t.quantity for t in closed), Decimal(0))
    total = sum(pnls, Decimal(0))
    equity = peak = drawdown = Decimal(0)
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {**report, 'win_rate': 100 * report['winning_trades'] / len(closed) if closed else 0,
        'wins': report['winning_trades'], 'losses': report['losing_trades'],
        'breakeven': report['breakeven_trades'], 'gross_pnl': float(total), 'net_pnl': float(total),
        'costs_supported': False, 'total_return_percent': float(total / capital * 100) if capital else 0,
        'average_pnl': float(total / len(closed)) if closed else 0,
        'average_return_percent': float(sum(returns, Decimal(0)) / len(closed)) if closed else 0,
        'best_trade': max((float(p) for p in pnls), default=None),
        'worst_trade': min((float(p) for p in pnls), default=None), 'max_drawdown': float(drawdown)}
