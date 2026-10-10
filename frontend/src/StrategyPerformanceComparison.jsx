import React, { useEffect, useState } from 'react';
import { formatPrice } from './format';
import { loadStrategyComparison, reportRangeError } from './reportFilters';

export const comparisonMetrics = [
  ['Total trades', 'total_trades'], ['Win rate', 'win_rate', '%'],
  ['Net P&L', 'net_pnl'], ['Profit factor', 'profit_factor'],
  ['Maximum drawdown', 'max_drawdown'], ['Average R', 'average_r'], ['SL hits', 'sl_hits'],
];

export function ComparisonTable({ comparison }) {
  return <div className="ms-tablewrap"><table>
    <thead><tr><th scope="col">Metric</th><th scope="col">LEGACY</th><th scope="col">ATR</th></tr></thead>
    <tbody>{comparisonMetrics.map(([label, key, suffix = '']) => <tr key={key}>
      <th scope="row">{label}</th>{['LEGACY', 'ATR'].map(strategy => {
        const value = comparison.strategies[strategy][key];
        return <td className="ms-num" key={strategy}>{value == null ? '—' : `${formatPrice(value)}${suffix}`}</td>;
      })}
    </tr>)}</tbody>
  </table></div>;
}

export default function StrategyPerformanceComparison({ fromDate, toDate, view, status, instrument, refreshKey }) {
  const [comparison, setComparison] = useState(null), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const validation = reportRangeError({ fromDate, toDate });
  useEffect(() => {
    const controller = new AbortController();
    setComparison(null); setError('');
    if (validation) return () => controller.abort();
    loadStrategyComparison({ fromDate, toDate, view, status, instrument }, { signal: controller.signal })
      .then(saved => {
        if (!saved?.strategies?.LEGACY || !saved?.strategies?.ATR) throw new Error('Invalid comparison response');
        if (!controller.signal.aborted) setComparison(saved);
      })
      .catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [fromDate, toDate, view, status, instrument, refreshKey, retry, validation]);
  return <section className="ms-strategy-comparison" aria-label="Strategy Performance Comparison">
    <h3 className="ms-sectionhead">Strategy Performance Comparison</h3>
    <p className="ms-sub">Both PAPER strategies over the selected entry dates, report view, status and instrument. The history's strategy selector applies to history and its summary; this comparison always shows both strategies.</p>
    {error && <p className="ms-error" role="alert">Comparison unavailable. {error} <button className="ms-link" onClick={() => setRetry(value => value+1)}>Retry</button></p>}
    {!comparison && !error && !validation && <p role="status">Loading strategy comparison…</p>}
    {comparison && !validation && <><ComparisonTable comparison={comparison} />
      <p className="ms-sub">PAPER P&amp;L excludes brokerage and slippage. Drawdown uses closed realised results in exit order. Win rate excludes breakeven trades, matching Reports. Average R uses known entry risk on closed trades: LEGACY {comparison.strategies.LEGACY.average_r_sample_size}, ATR {comparison.strategies.ATR.average_r_sample_size}. A dash means the metric is unavailable. These are observed trades, with different entry samples possible for each strategy.</p>
    </>}
  </section>;
}
