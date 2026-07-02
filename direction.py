"""
左侧/右侧入场分析引擎。
左侧 = 逆势抄底/摸底 (contrarian, bottom-fishing)
右侧 = 顺势追涨/杀跌 (trend-following, momentum)
"""
import logging
from dataclasses import dataclass, field
from typing import Optional
import yfinance as yf
import pandas as pd

from indicators import (
    fetch_intraday_data, fetch_current_price, calc_rsi, detect_trend, calc_macd,
    calc_fibonacci_levels, calc_bollinger_bands, calc_session_vwap,
    calc_volume_ratio, calc_support_resistance, get_market_sentiment,
    detect_market_session
)
from config import TICKER_PARAMS

logger = logging.getLogger(__name__)


@dataclass
class DirectionResult:
    ticker: str = ""
    company_name: str = ""
    current_price: float = 0.0
    change_pct: float = 0.0
    left_score: int = 0      # 左侧评分 0-100
    right_score: int = 0     # 右侧评分 0-100
    left_signal: str = ""    # 适合左侧/不适合
    right_signal: str = ""   # 适合右侧/不适合
    direction: str = ""      # 建议方向: '左侧', '右侧', '观望'
    buy_limit: str = ""      # 挂单建议
    take_profit: str = ""    # 止盈建议
    stop_loss: str = ""      # 止损建议
    market_session: str = "" # 盘前/盘中/盘后
    details: dict = field(default_factory=dict)
    error: Optional[str] = None


def analyze_direction(ticker: str) -> DirectionResult:
    """
    Analyze whether a stock is suitable for left-side or right-side entry.
    Returns scores for both directions plus order suggestions.
    """
    result = DirectionResult(ticker=ticker.upper())
    
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        result.company_name = str(info.get('shortName') or info.get('longName') or '')
        result.current_price = round(info.get('currentPrice') or info.get('regularMarketPrice') or 0, 2)
        
        # Fetch data
        df = fetch_intraday_data(ticker, interval='15m', period='1mo')
        if df.empty:
            df = fetch_intraday_data(ticker, interval='5m', period='5d')
        if df.empty:
            result.error = f"⚠️ 无法获取 {ticker} 行情数据"
            return result
        
        # Update price with extended hours (pre/post market) if available
        ext = fetch_current_price(ticker)
        if ext["price"] > 0:
            result.current_price = ext["price"]
            result.change_pct = ext["change_pct"]
        
        # Detect market session
        result.market_session = detect_market_session(df)
        
        # Calculate all indicators
        close = df['Close']
        high = df['High']
        low = df['Low']
        volume = df['Volume']
        
        current_price = result.current_price if result.current_price > 0 else close.iloc[-1]
        result.current_price = current_price
        
        # ─── Compute indicators ────────────────────────────
        rsi = calc_rsi(close, 14)
        trend = detect_trend(df)
        macd = calc_macd(close, 12, 26, 9)
        fib = calc_fibonacci_levels(df, lookback=60)
        bb = calc_bollinger_bands(df)
        vwap = calc_session_vwap(df)
        vol_ratio = calc_volume_ratio(df)
        sr = calc_support_resistance(df)
        
        # ─── 左侧评分 (Contrarian / Bottom-fishing) ────────
        left = 0
        left_factors = []
        
        # RSI oversold
        if rsi < 25:
            left += 30
            left_factors.append(("RSI深度超卖", 30, f"RSI={rsi}"))
        elif rsi < 35:
            left += 25
            left_factors.append(("RSI超卖", 25, f"RSI={rsi}"))
        elif rsi < 45:
            left += 10
            left_factors.append(("RSI偏低", 10, f"RSI={rsi}"))
        
        # Price near Fibonacci 0.618/0.786 support (uptrend pullback)
        fib_levels = fib.get('levels', {})
        for key in ['支0.618', '支0.786', '支0.500']:
            if key in fib_levels:
                fib_val = fib_levels[key]
                dist = abs(current_price - fib_val) / current_price * 100
                if dist < 1.0:
                    left += 20
                    left_factors.append((f"贴近{key}", 20, f"${fib_val}"))
                    break
        
        # Price near lower Bollinger Band
        if bb.get('lower', 0) > 0:
            dist_to_lower = (current_price - bb['lower']) / current_price * 100
            if dist_to_lower < 0.5:
                left += 15
                left_factors.append(("触及布林下轨", 15, f"${bb['lower']}"))
            elif dist_to_lower < 1.5:
                left += 8
                left_factors.append(("接近布林下轨", 8, f"${bb['lower']}"))
        
        # MACD bullish divergence (price down, MACD up)
        if macd.get('histogram_dir') == 'rising' and trend.get('direction') == 'bearish':
            left += 15
            left_factors.append(("MACD底背离", 15, "价格跌但MACD升"))
        
        # Volume climax (high volume on red days)
        if vol_ratio and vol_ratio > 1.5:
            left += 10
            left_factors.append(("放量下跌", 10, f"量{vol_ratio}x"))
        
        # Price near support
        s1 = sr.get('support1', 0)
        if s1 > 0:
            dist_s1 = (current_price - s1) / current_price * 100
            if 0 <= dist_s1 < 1.0:
                left += 10
                left_factors.append(("贴近支撑S1", 10, f"${s1}"))
        
        # Trend is bearish (contrarian opportunity)
        if trend.get('direction') == 'bearish':
            left += 5
            left_factors.append(("逆势机会", 5, "下跌中"))
        
        left = min(100, left)
        left_factors.sort(key=lambda x: x[1], reverse=True)
        
        # ─── 右侧评分 (Trend-following / Momentum) ────────
        right = 0
        right_factors = []
        
        # Strong trend
        if trend.get('direction') == 'bullish' and trend.get('strength') == 'strong':
            right += 25
            right_factors.append(("强劲多头", 25, trend['description']))
        elif trend.get('direction') == 'bullish':
            right += 15
            right_factors.append(("偏多", 15, trend['description']))
        
        # RSI sweet spot (45-65)
        if 45 <= rsi <= 65:
            right += 20
            right_factors.append(("RSI黄金区", 20, f"RSI={rsi}"))
        elif 35 <= rsi < 45:
            right += 10
            right_factors.append(("RSI中性偏低", 10, f"RSI={rsi}"))
        elif 65 < rsi <= 75:
            right += 5
            right_factors.append(("RSI偏强", 5, f"RSI={rsi}"))
        
        # MACD bullish
        if macd.get('cross') == 'bullish':
            right += 20
            right_factors.append(("MACD金叉", 20, ""))
        elif macd.get('macd', 0) > macd.get('signal', 0):
            right += 10
            right_factors.append(("MACD多头", 10, "线上"))
        
        # Volume confirmation
        if vol_ratio and vol_ratio >= 1.2:
            right += 15
            right_factors.append(("放量确认", 15, f"量{vol_ratio}x"))
        elif vol_ratio and vol_ratio >= 1.0:
            right += 5
            right_factors.append(("成交量正常", 5, f"量{vol_ratio}x"))
        
        # Price above VWAP
        if vwap > 0 and current_price > vwap:
            right += 10
            right_factors.append(("VWAP上方", 10, f"${vwap}"))
        
        # Price breaking above Fibonacci resistance
        if fib.get('trend') == 'uptrend':
            for key in ['阻0.618', '阻0.500', '阻0.382']:
                if key in fib_levels:
                    fib_val = fib_levels[key]
                    if current_price > fib_val:
                        right += 10
                        right_factors.append((f"突破{key}", 10, f"${fib_val}"))
                        break
        
        # Price above EMAs
        if trend.get('above_ema5') and trend.get('above_ema20'):
            right += 5
            right_factors.append(("EMA上方", 5, ""))
        
        right = min(100, right)
        right_factors.sort(key=lambda x: x[1], reverse=True)
        
        # ─── Determine direction ────────────────────────────
        diff = right - left
        if left >= 55 and left > right:
            direction = '左侧'
            signal_left = "✅ 适合左侧入场"
            signal_right = "❌ 不适合右侧"
        elif right >= 55 and right > left:
            direction = '右侧'
            signal_right = "✅ 适合右侧入场"
            signal_left = "❌ 不适合左侧"
        elif left >= 40 and right < 40:
            direction = '左侧'
            signal_left = "🟡 可考虑左侧"
            signal_right = "❌ 不适合右侧"
        elif right >= 40 and left < 40:
            direction = '右侧'
            signal_right = "🟡 可考虑右侧"
            signal_left = "❌ 不适合左侧"
        elif abs(diff) < 15:
            direction = '观望'
            signal_left = "⚪ 信号不明确"
            signal_right = "⚪ 信号不明确"
        else:
            direction = '右侧' if diff > 0 else '左侧'
            signal_right = "可考虑右侧" if diff > 0 else "不推荐右侧"
            signal_left = "可考虑左侧" if diff < 0 else "不推荐左侧"
        
        result.left_score = left
        result.right_score = right
        result.left_signal = signal_left
        result.right_signal = signal_right
        result.direction = direction
        
        # ─── 挂单建议 ──────────────────────────────────────
        if direction == '左侧':
            # Buy limit near Fibonacci support
            fib_618 = fib_levels.get('支0.618', 0)
            fib_786 = fib_levels.get('支0.786', 0)
            bb_lower = bb.get('lower', 0)
            
            candidates = []
            if fib_618: candidates.append(('Fib 0.618', fib_618))
            if fib_786: candidates.append(('Fib 0.786', fib_786))
            if bb_lower: candidates.append(('布林下轨', bb_lower))
            
            if candidates:
                candidates.sort(key=lambda x: x[1])
                best_label, best_price = candidates[0]
                result.buy_limit = f"挂单 ${best_price:.2f} ({best_label})"
                sl = candidates[0][1] * 0.995 if len(candidates) > 1 else best_price * 0.995
                result.stop_loss = f"止损 ${sl:.2f} (低于{best_label} -0.5%)"
            else:
                result.buy_limit = "等待RSI<30或触及支撑"
                result.stop_loss = "自定止损 -2%"
            
            # TP: Fib retracement or R1
            for key in ['支0.382', '支0.500']:
                if key in fib_levels and fib_levels[key] > current_price:
                    tp = fib_levels[key]
                    result.take_profit = f"止盈 ${tp:.2f} ({key}, +{(tp-current_price)/current_price*100:.1f}%)"
                    break
            if not result.take_profit and sr.get('resistance1', 0) > current_price:
                tp = sr['resistance1']
                result.take_profit = f"止盈 ${tp:.2f} (R1, +{(tp-current_price)/current_price*100:.1f}%)"
            if not result.take_profit:
                result.take_profit = f"止盈 ${current_price*1.03:.2f} (+3%目标)"
        
        elif direction == '右侧':
            ema5 = trend.get('ema5', 0)
            buy_price = 0
            buy_label = ""
            if vwap > 0 and current_price > vwap:
                buy_price = vwap
                buy_label = "VWAP回调"
            elif ema5 > 0:
                buy_price = ema5
                buy_label = "EMA5回调"
        
            if buy_price > 0 and buy_price < current_price:
                result.buy_limit = f"挂单 ${buy_price:.2f} ({buy_label})"
            else:
                result.buy_limit = f"现价入场 ${current_price:.2f}"
        
            sl = 0
            ema20 = trend.get('ema20', 0)
            s1 = sr.get('support1', 0)
            sl = max(ema20, s1) if ema20 and s1 else (ema20 or s1)
            if sl > 0 and sl < current_price:
                sl_pct = (current_price - sl) / current_price * 100
                result.stop_loss = f"止损 ${sl:.2f} ({sl_pct:.1f}%)"
            else:
                result.stop_loss = f"止损 ${current_price * 0.985:.2f} (-1.5%)"
        
            # TP: Fibonacci extension or resistance
            for key in ['延1.272', '延1.618']:
                if key in fib_levels and fib_levels[key] > current_price:
                    tp = fib_levels[key]
                    result.take_profit = f"止盈 ${tp:.2f} ({key}, +{(tp-current_price)/current_price*100:.1f}%)"
                    break
            if not result.take_profit and sr.get('resistance1', 0) > current_price:
                tp = sr['resistance1']
                result.take_profit = f"止盈 ${tp:.2f} (R1, +{(tp-current_price)/current_price*100:.1f}%)"
            if not result.take_profit:
                result.take_profit = f"止盈 ${current_price*1.02:.2f} (+2%目标)"
        else:
            result.buy_limit = "等待明确信号"
            result.stop_loss = "-"
            result.take_profit = "-"

        # Store details for display
        result.details = {
            'rsi': rsi,
            'macd': macd,
            'trend': trend,
            'fib': fib,
            'bb': bb,
            'vwap': vwap,
            'vol_ratio': vol_ratio,
            'left_factors': left_factors,
            'right_factors': right_factors,
            'sr': sr,
        }
        
    except Exception as e:
        logger.error(f"Direction analysis error for {ticker}: {e}")
        result.error = f"分析异常: {str(e)[:100]}"
    
    return result


def format_direction_result(r: DirectionResult) -> str:
    """Format direction analysis for Telegram display."""
    if r.error:
        return r.error
    
    lines = []
    emoji_dir = "🔵" if r.direction == '左侧' else "🔴" if r.direction == '右侧' else "⚪"
    
    # Header
    lines.append(f"{emoji_dir} **{r.ticker}** - {r.company_name}")
    change_str = f"{r.change_pct:+.2f}%" if r.change_pct else ""
    lines.append(f"`${r.current_price:.2f}` {change_str}")
    if r.market_session:
        lines.append(f"⏰ {r.market_session}")
    lines.append("")
    
    # Scores
    left_bar = _bar(r.left_score, 100)
    right_bar = _bar(r.right_score, 100)
    lines.append(f"📊 **方向评分**")
    lines.append(f"{left_bar} **左侧 (抄底)**: {r.left_score}/100 — {r.left_signal}")
    lines.append(f"{right_bar} **右侧 (追势)**: {r.right_score}/100 — {r.right_signal}")
    lines.append(f"**建议**: {emoji_dir} **{r.direction}入场**")
    lines.append("")
    
    # Key indicators
    d = r.details
    lines.append(f"📈 **关键指标**")
    lines.append(f"   RSI(14): {d.get('rsi', 'N/A')}  |  MACD: {d.get('macd', {}).get('cross', 'N/A')}")
    lines.append(f"   趋势: {d.get('trend', {}).get('description', 'N/A')}")
    lines.append(f"   布林位置: {d.get('bb', {}).get('position', 'N/A')}%")
    lines.append(f"   量比: {d.get('vol_ratio', 'N/A')}x")
    lines.append("")
    
    # Fibonacci zone
    fib = d.get('fib', {})
    if fib.get('current_zone'):
        lines.append(f"🎯 **斐波那契区间**")
        lines.append(f"   当前在: {fib['current_zone']}")
        lines.append(f"   高点: ${fib.get('high', 0)}  |  低点: ${fib.get('low', 0)}")
        lines.append("")
    
    # Order suggestions
    lines.append(f"💰 **挂单建议**")
    lines.append(f"   入场: {r.buy_limit}")
    if r.take_profit:
        lines.append(f"   止盈: {r.take_profit}")
    lines.append(f"   止损: {r.stop_loss}")
    lines.append("")
    
    # Factor breakdown (top 3)
    if r.direction == '左侧':
        factors = d.get('left_factors', [])[:3]
        label = "左侧依据"
    elif r.direction == '右侧':
        factors = d.get('right_factors', [])[:3]
        label = "右侧依据"
    else:
        factors = []
        label = ""
    
    if factors:
        lines.append(f"📋 **{label}**")
        for name, score, val in factors:
            val_str = f" ({val})" if val else ""
            lines.append(f"   +{score} {name}{val_str}")
    
    return "\n".join(lines)


def _bar(score: int, max_score: int = 100, width: int = 10) -> str:
    """Visual score bar."""
    filled = min(width, max(0, int(score / max_score * width)))
    empty = width - filled
    if score >= 60:
        color = "🟢"
    elif score >= 40:
        color = "🟡"
    else:
        color = "🔴"
    return color + "█" * filled + "░" * empty


if __name__ == '__main__':
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'NVDA'
    r = analyze_direction(ticker)
    print(format_direction_result(r))
