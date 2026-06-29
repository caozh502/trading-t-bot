"""
1-month backtest engine for the 做T scoring strategy.
Simulates intraday trading with configurable thresholds, stop-loss, and take-profit.
"""

import sys, os, json, math
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))
from indicators import calc_rsi, calc_ema, calc_volume_ratio

# ── Market hours (ET) ──────────────────────────────────────────
# US equity market: 9:30 - 16:00 ET
MARKET_OPEN = 9 * 60 + 30   # 9:30 in minutes from midnight
MARKET_CLOSE = 16 * 60      # 16:00

def _minutes_since_midnight(dt: datetime) -> int:
    """Convert a datetime to minutes since midnight (ET-aware approx)."""
    # yfinance returns UTC timestamps; US market is ET = UTC-4/UTC-5
    # For simplicity we work in UTC and check if the time maps to market hours
    return dt.hour * 60 + dt.minute


def _is_market_hours_utc(dt: datetime) -> bool:
    """Check if a UTC time falls within US market hours (rough ET conversion)."""
    # During EDT (Mar-Nov): ET = UTC-4 → market 13:30-20:00 UTC
    # During EST (Nov-Mar): ET = UTC-5 → market 14:30-21:00 UTC
    # Simple heuristic: UTC hour between 13 and 21
    h = dt.hour
    m = dt.minute
    total_min = h * 60 + m
    return 13 * 60 + 30 <= total_min <= 20 * 60 + 0  # 13:30-20:00 UTC ≈ 9:30-16:00 ET


def _get_trading_days(df: pd.DataFrame) -> list:
    """Get list of unique trading days from index."""
    days = sorted(set(d.date() for d in df.index))
    return days


def _filter_today_bars(df: pd.DataFrame, day_date) -> pd.DataFrame:
    """Filter bars for a specific trading day."""
    return df[df.index.date == day_date].copy()


def _calculate_score(data_slice: pd.DataFrame, prev_days: pd.DataFrame) -> dict:
    """
    Calculate the 做T score using data up to the current point.
    Mimics the logic from analyzer.py but operates on a data slice.
    """
    close = data_slice['Close']
    if len(close) < 5:
        return {'score': 0.0, 'details': {}}
    
    # VWAP
    typical_price = (data_slice['High'] + data_slice['Low'] + data_slice['Close']) / 3
    if data_slice['Volume'].sum() > 0:
        vwap = (typical_price * data_slice['Volume']).sum() / data_slice['Volume'].sum()
    else:
        vwap = close.iloc[-1]
    current_price = close.iloc[-1]
    vwap_dev = (current_price - vwap) / vwap * 100 if vwap else 0
    
    # Trend (EMA5, EMA20)
    ema5 = calc_ema(close, 5)
    ema20 = calc_ema(close, 20)
    trend_bullish = ema5 > ema20
    price_above_ema5 = current_price > ema5
    price_above_ema20 = current_price > ema20
    
    # RSI
    rsi = calc_rsi(close, 14)
    
    # Volume
    if prev_days is not None and not prev_days.empty:
        today_avg_vol = data_slice['Volume'].mean()
        prev_avg_vol = prev_days['Volume'].mean()
        vol_ratio = today_avg_vol / prev_avg_vol if prev_avg_vol > 0 else 1.0
    else:
        vol_ratio = 1.0
    
    # Support/Resistance (simplified)
    prev_close = prev_days['Close'].iloc[-1] if prev_days is not None and not prev_days.empty else current_price
    today_high = data_slice['High'].max()
    today_low = data_slice['Low'].min()
    pivot = (today_high + today_low + prev_close) / 3
    r1 = 2 * pivot - today_low
    s1 = 2 * pivot - today_high
    
    dist_to_s1 = ((current_price - s1) / current_price * 100) if s1 else 99
    dist_to_r1 = ((r1 - current_price) / current_price * 100) if r1 else 99
    
    # ── Score calculation (same weights as analyzer.py) ──────
    w_vwap, w_trend, w_rsi, w_vol, w_level = 0.25, 0.25, 0.20, 0.15, 0.15
    
    # VWAP score
    if vwap_dev > 0.5:       s_vwap = 0.8
    elif vwap_dev > 0.1:     s_vwap = 0.3
    elif vwap_dev > -0.1:    s_vwap = 0.0
    elif vwap_dev > -0.5:    s_vwap = -0.3
    else:                     s_vwap = -0.8
    
    # Trend score
    bullish_signals = sum([trend_bullish, price_above_ema5, price_above_ema20])
    if bullish_signals >= 2 and trend_bullish:
        s_trend = 0.8
    elif bullish_signals >= 1:
        s_trend = 0.3
    else:
        s_trend = -0.5
    
    # RSI score
    if rsi < 25:         s_rsi = 0.6
    elif rsi < 35:       s_rsi = 0.8
    elif rsi < 45:       s_rsi = 0.3
    elif rsi < 60:       s_rsi = 0.5
    elif rsi < 70:       s_rsi = 0.0
    elif rsi < 80:       s_rsi = -0.5
    else:                s_rsi = -0.8
    
    # Volume score
    if vol_ratio >= 1.5:   s_vol = 0.8
    elif vol_ratio >= 1.0: s_vol = 0.3
    elif vol_ratio >= 0.7: s_vol = -0.2
    else:                  s_vol = -0.8
    
    # Price level score
    s_level = 0.0
    if dist_to_s1 < 0.5:   s_level = 0.7
    elif dist_to_s1 < 1.5: s_level = 0.3
    if dist_to_r1 < 0.5:   s_level = min(s_level, -0.3) if s_level < 0 else -0.3
    elif dist_to_r1 >= 1.5:
        if s_level >= 0:   s_level += 0.2
    
    total = (s_vwap * w_vwap + s_trend * w_trend + s_rsi * w_rsi +
             s_vol * w_vol + s_level * w_level)
    total = max(-1.0, min(1.0, total))
    
    return {
        'score': round(total, 2),
        'details': {
            'vwap_dev': round(vwap_dev, 2),
            's_vwap': s_vwap,
            's_trend': s_trend,
            's_rsi': s_rsi,
            's_vol': s_vol,
            's_level': s_level,
            'rsi': round(rsi, 1),
            'vol_ratio': round(vol_ratio, 2),
            'ema5': round(ema5, 2),
            'ema20': round(ema20, 2),
            'vwap': round(vwap, 2),
            's1': round(s1, 2),
            'r1': round(r1, 2),
        }
    }


def run_backtest(ticker: str, lookback_days: int = 30,
                 score_threshold: float = 0.3,
                 sl_pct: float = 0.6,
                 tp_pct: float = 1.2,
                 scan_interval_min: int = 30,
                 verbose: bool = False) -> dict:
    """
    Run a 1-month backtest for a single ticker.
    
    Args:
        ticker: Stock symbol
        lookback_days: How many days of data to fetch
        score_threshold: Min score to enter a trade (0.2=cautious, 0.5=strong)
        sl_pct: Stop-loss percentage (e.g. 0.6 = -0.6%)
        tp_pct: Take-profit percentage (e.g. 1.2 = +1.2%)
        scan_interval_min: How often to scan (minutes)
    
    Returns:
        dict with trades list and summary stats
    """
    # Fetch data
    df = yf.download(ticker, period=f"{lookback_days + 10}d", interval="5m",
                     progress=False, auto_adjust=True)
    if df.empty or len(df) < 50:
        return {'error': f'Insufficient data for {ticker}', 'trades': [], 'summary': {}}
    
    # Flatten MultiIndex columns if needed
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # Filter to market hours only
    df = df[df.index.map(_is_market_hours_utc)].copy()
    if df.empty:
        return {'error': f'No market-hours data for {ticker}', 'trades': [], 'summary': {}}
    
    trading_days = sorted(set(d.date() for d in df.index))
    
    trades = []
    
    for day_idx, day in enumerate(trading_days):
        if day_idx == 0:
            continue  # Skip first day (no prev_day data)
        
        today_bars = _filter_today_bars(df, day)
        if len(today_bars) < 10:
            continue
        
        # Previous 5 days for volume baseline
        prev_days_list = [_filter_today_bars(df, trading_days[i]) 
                         for i in range(max(0, day_idx-5), day_idx)]
        prev_days = pd.concat(prev_days_list) if prev_days_list else None
        
        if prev_days is None or prev_days.empty:
            continue
        
        # Scan schedule: first scan at 10:00 ET (14:00 UTC), last at 15:30 ET (19:30 UTC)
        from datetime import datetime, timedelta, timezone
        # Get timezone from the dataframe index
        tz = df.index.tz if hasattr(df.index, 'tz') else None
        day_dt = datetime.combine(day, datetime.min.time())
        start_utc = day_dt.replace(hour=14, minute=0)  # 10:00 ET
        end_utc = day_dt.replace(hour=19, minute=30)    # 15:30 ET
        if tz:
            start_utc = start_utc.replace(tzinfo=tz)
            end_utc = end_utc.replace(tzinfo=tz)
        
        scan_times = []
        t = start_utc
        while t <= end_utc:
            scan_times.append(t)
            t += timedelta(minutes=scan_interval_min)
        
        for scan_time in scan_times:
            # Find the bar nearest to scan time
            bars_up_to_scan = today_bars[today_bars.index <= pd.Timestamp(scan_time)]
            if len(bars_up_to_scan) < 10:
                continue
            
            # Don't enter in the last 30 minutes of market
            last_bar_time = bars_up_to_scan.index[-1]
            last_bar_min = last_bar_time.hour * 60 + last_bar_time.minute
            if last_bar_min >= 19 * 60 + 30:  # 19:30 UTC = 15:30 ET
                continue
            
            # Calculate score
            score_result = _calculate_score(bars_up_to_scan, prev_days)
            score = score_result['score']
            
            if score < score_threshold:
                continue
            
            # ENTER TRADE
            entry_bar = bars_up_to_scan.iloc[-1]
            entry_price = entry_bar['Close']
            entry_time = bars_up_to_scan.index[-1]
            
            sl_price = entry_price * (1 - sl_pct / 100)
            tp_price = entry_price * (1 + tp_pct / 100)
            
            # Find exit: look at subsequent bars for SL/TP hit, or EOD
            remaining = today_bars[today_bars.index > entry_time]
            exit_price = None
            exit_time = None
            exit_reason = None
            
            for idx, bar in remaining.iterrows():
                if bar['Low'] <= sl_price:
                    exit_price = sl_price
                    exit_time = idx
                    exit_reason = 'stop_loss'
                    break
                elif bar['High'] >= tp_price:
                    exit_price = tp_price
                    exit_time = idx
                    exit_reason = 'take_profit'
                    break
            
            if exit_reason is None:
                # Close at end of day (last bar before 20:00 UTC)
                eod_bars = today_bars[today_bars.index.hour * 60 + today_bars.index.minute <= 20 * 60]
                if not eod_bars.empty and eod_bars.index[-1] > entry_time:
                    exit_bar = eod_bars.iloc[-1]
                    exit_price = exit_bar['Close']
                    exit_time = exit_bar.name
                    exit_reason = 'eod_close'
                else:
                    # Cannot find exit
                    continue
            
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            trade = {
                'day': str(day),
                'entry_time': str(entry_time),
                'exit_time': str(exit_time),
                'entry_price': round(entry_price, 2),
                'exit_price': round(exit_price, 2),
                'pnl_pct': round(pnl_pct, 2),
                'exit_reason': exit_reason,
                'score': score,
                'sl_price': round(sl_price, 2),
                'tp_price': round(tp_price, 2),
                'details': score_result['details'],
            }
            trades.append(trade)
            
            if verbose:
                print(f"  {str(day):12s} | {str(entry_time.time())[:5]} | "
                      f"score={score:+.2f} | entry=${entry_price:.2f} | "
                      f"exit={exit_reason:12s} | PnL={pnl_pct:+.2f}%")
    
    # Summary stats
    if not trades:
        return {'ticker': ticker, 'trades': [], 'summary': {'total_trades': 0, 'message': '没有触发交易'}}
    
    df_trades = pd.DataFrame(trades)
    wins = df_trades[df_trades['pnl_pct'] > 0]
    losses = df_trades[df_trades['pnl_pct'] <= 0]
    
    summary = {
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(len(wins) / len(trades) * 100, 1) if trades else 0,
        'avg_win': round(wins['pnl_pct'].mean(), 2) if not wins.empty else 0,
        'avg_loss': round(losses['pnl_pct'].mean(), 2) if not losses.empty else 0,
        'max_win': round(df_trades['pnl_pct'].max(), 2),
        'max_loss': round(df_trades['pnl_pct'].min(), 2),
        'total_return': round(df_trades['pnl_pct'].sum(), 2),
        'avg_return': round(df_trades['pnl_pct'].mean(), 2),
        'profit_factor': round(abs(wins['pnl_pct'].sum() / losses['pnl_pct'].sum()), 2) if not losses.empty and losses['pnl_pct'].sum() != 0 else float('inf'),
        'exit_reasons': df_trades['exit_reason'].value_counts().to_dict(),
        'avg_score': round(df_trades['score'].mean(), 2),
    }
    
    return {'ticker': ticker, 'trades': trades, 'summary': summary}


def print_summary(result: dict, params_desc: str = ""):
    """Pretty-print backtest summary."""
    if 'error' in result:
        print(f"❌ {result['error']}")
        return
    
    s = result['summary']
    if s.get('total_trades', 0) == 0:
        print(f"📊 {result['ticker']}: {s.get('message', '无交易')}")
        return
    
    print(f"\n{'='*55}")
    print(f"📊 {result['ticker']}  {params_desc}")
    print(f"{'='*55}")
    print(f"  总交易:         {s['total_trades']}")
    print(f"  胜率:           {s['win_rate']}% ({s['wins']}胜/{s['losses']}负)")
    print(f"  平均盈利:       +{s['avg_win']}%")
    print(f"  平均亏损:       {s['avg_loss']}%")
    print(f"  最大盈利:       +{s['max_win']}%")
    print(f"  最大亏损:       {s['max_loss']}%")
    print(f"  总收益:         {s['total_return']:+.2f}%")
    print(f"  平均每笔:        {s['avg_return']:+.2f}%")
    print(f"  盈亏比:          {s['profit_factor']}:1")
    print(f"  平均评分:        {s['avg_score']:+.2f}")
    if 'exit_reasons' in s:
        reasons = s['exit_reasons']
        total = sum(reasons.values())
        reason_str = " | ".join(f"{k}: {v}({v/total*100:.0f}%)" for k, v in sorted(reasons.items()))
        print(f"  退出原因:       {reason_str}")


def parameter_sweep(ticker: str, lookback_days: int = 30,
                    score_thresholds: list = None,
                    sl_values: list = None,
                    tp_values: list = None) -> list:
    """
    Sweep over multiple parameter combinations to find optimal settings.
    """
    if score_thresholds is None:
        score_thresholds = [0.2, 0.3, 0.4, 0.5]
    if sl_values is None:
        sl_values = [0.4, 0.6, 0.8, 1.0]
    if tp_values is None:
        tp_values = [0.8, 1.0, 1.2, 1.5, 2.0]
    
    results = []
    for threshold in score_thresholds:
        for sl in sl_values:
            for tp in tp_values:
                if tp <= sl:  # Skip if TP not greater than SL
                    continue
                r = run_backtest(ticker, lookback_days, threshold, sl, tp, verbose=False)
                if 'error' in r or r['summary'].get('total_trades', 0) == 0:
                    continue
                s = r['summary']
                results.append({
                    'threshold': threshold,
                    'sl_pct': sl,
                    'tp_pct': tp,
                    'total_trades': s['total_trades'],
                    'win_rate': s['win_rate'],
                    'total_return': s['total_return'],
                    'profit_factor': s['profit_factor'],
                    'avg_return': s['avg_return'],
                    'max_loss': s['max_loss'],
                })
    
    return sorted(results, key=lambda x: x['total_return'], reverse=True)


if __name__ == '__main__':
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'QQQ'
    
    print(f"\n🔍 回测 {ticker} — 默认参数 (threshold=0.3, SL=0.6%, TP=1.2%)")
    result = run_backtest(ticker, lookback_days=30, verbose=True)
    print_summary(result, "默认参数")
    
    print(f"\n\n🔬 参数扫描 (寻找最优参数组合)...")
    sweep = parameter_sweep(ticker)
    print(f"\n{'='*60}")
    print(f"🏆 {ticker} 最优参数排名 (按总收益排序)")
    print(f"{'='*60}")
    print(f"{'门槛':>6s} | {'止损':>5s} | {'止盈':>5s} | {'交易':>5s} | {'胜率':>6s} | {'总收益':>8s} | {'盈亏比':>7s}")
    print("-" * 55)
    for r in sweep[:10]:
        print(f"{r['threshold']:>5.1f} | {r['sl_pct']:>4.1f}% | {r['tp_pct']:>4.1f}% | "
              f"{r['total_trades']:>4d} | {r['win_rate']:>5.1f}% | "
              f"{r['total_return']:>+7.2f}% | {r['profit_factor']:>6.1f}:1")
