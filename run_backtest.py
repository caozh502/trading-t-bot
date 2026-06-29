"""Full backtest: 5 tickers x parameter sweep."""
import sys, os, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, r'E:\Caleb_Space\Code\Project_t\trading-t-bot')
os.chdir(r'E:\Caleb_Space\Code\Project_t\trading-t-bot')

from backtest import run_backtest, print_summary

TICKERS = ['MRVL', 'RKLB', 'NVDA', 'MU', 'QQQ']

# Grid search parameters
THRESHOLDS = [0.2, 0.3, 0.4, 0.5]
SL_VALUES = [0.4, 0.6, 0.8, 1.0]
TP_VALUES = [0.8, 1.0, 1.2, 1.5, 2.0]

all_results = []

for ticker in TICKERS:
    print(f"\n{'#'*60}")
    print(f"#   {ticker}")
    print(f"{'#'*60}")
    
    best_configs = []
    
    for th in THRESHOLDS:
        for sl in SL_VALUES:
            for tp in TP_VALUES:
                if tp <= sl * 1.2:  # TP should be at least 1.2x SL
                    continue
                
                r = run_backtest(ticker, lookback_days=30,
                                score_threshold=th, sl_pct=sl, tp_pct=tp,
                                verbose=False)
                
                if 'error' in r:
                    continue
                
                s = r['summary']
                if s['total_trades'] < 3:
                    continue
                
                # Score: prefer high win rate + good profit factor
                score_metric = s['total_return']
                
                all_results.append({
                    'ticker': ticker,
                    'threshold': th,
                    'sl': sl,
                    'tp': tp,
                    'trades': s['total_trades'],
                    'win_rate': s['win_rate'],
                    'total_return': s['total_return'],
                    'profit_factor': s['profit_factor'],
                    'avg_return': s['avg_return'],
                })
                
                best_configs.append(all_results[-1])
    
    # Show top 5 for this ticker
    best_configs.sort(key=lambda x: x['total_return'], reverse=True)
    print(f"{'门槛':>5s} {'止损%':>6s} {'止盈%':>6s} {'交易':>5s} {'胜率':>6s} {'总收益':>8s} {'盈亏比':>7s}")
    print("-" * 50)
    for c in best_configs[:5]:
        print(f"{c['threshold']:>4.1f}  {c['sl']:>4.1f}%  {c['tp']:>4.1f}%  "
              f"{c['trades']:>4d}  {c['win_rate']:>5.1f}%  "
              f"{c['total_return']:>+7.2f}%  {c['profit_factor']:>5.1f}:1")

# ── Overall best configurations ───────────────────────────────
print(f"\n\n{'='*65}")
print(f"  🏆 全局最优参数 (按总收益排名)")
print(f"{'='*65}")
print(f"{'代码':>5s} {'门槛':>5s} {'止损%':>6s} {'止盈%':>6s} {'交易':>5s} {'胜率':>6s} {'总收益':>8s} {'盈亏比':>7s}")
print("-" * 60)

all_results.sort(key=lambda x: x['total_return'], reverse=True)
for c in all_results[:15]:
    print(f"{c['ticker']:>5s} {c['threshold']:>4.1f}  {c['sl']:>4.1f}%  {c['tp']:>4.1f}%  "
          f"{c['trades']:>4d}  {c['win_rate']:>5.1f}%  "
          f"{c['total_return']:>+7.2f}%  {c['profit_factor']:>5.1f}:1")

# ── Per-ticker best config ────────────────────────────────────
print(f"\n\n{'='*65}")
print(f"  📋 各股票最佳参数 (基于总收益)")
print(f"{'='*65}")
for ticker in TICKERS:
    ticker_results = [r for r in all_results if r['ticker'] == ticker]
    if ticker_results:
        best = max(ticker_results, key=lambda x: x['total_return'])
        print(f"  {ticker:5s}: threshold={best['threshold']:.1f}, SL={best['sl']:.1f}%, "
              f"TP={best['tp']:.1f}% → 总收益{best['total_return']:+.2f}%, "
              f"胜率{best['win_rate']:.0f}%, {best['trades']}笔交易")
