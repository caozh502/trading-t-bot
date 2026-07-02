"""
Multi-factor scoring engine for intraday trading (做T) entry decisions.
Combines technical indicators into a weighted score with clear signals.
"""

from datetime import datetime, timezone
import logging
from dataclasses import dataclass, field
from typing import Optional
import yfinance as yf

from indicators import (
    fetch_intraday_data, fetch_current_price, calc_session_vwap, calc_rsi, detect_trend,
    calc_support_resistance, calc_volume_ratio, calc_bollinger_bands,
    get_market_sentiment, detect_market_session
)
from config import TICKER_PARAMS, DEFAULT_SL_PCT, DEFAULT_TP_PCT

logger = logging.getLogger(__name__)

# ── Scoring weights ──────────────────────────────────────────────
WEIGHTS = {
    'vwap': 0.25,
    'trend': 0.25,
    'rsi': 0.20,
    'volume': 0.15,
    'price_level': 0.15,
}


@dataclass
class FactorScore:
    """Score for a single factor."""
    name: str
    score: float       # -1.0 to +1.0
    weight: float      # 0.0 to 1.0
    detail: str        # Human-readable description
    value: str = ""    # Raw value for display


@dataclass
class AnalysisResult:
    """Complete analysis result for one ticker."""
    ticker: str
    company_name: str = ""
    current_price: float = 0.0
    change_pct: float = 0.0
    total_score: float = 0.0
    signal: str = "N/A"               # ✅ 入场 / ⚠️ 观望 / ❌ 不入
    signal_color: str = "⚪"
    factors: list[FactorScore] = field(default_factory=list)
    market_sentiment: dict = field(default_factory=dict)
    support_resistance: dict = field(default_factory=dict)
    bollinger: dict = field(default_factory=dict)
    sl_tp: dict = field(default_factory=dict)  # stop-loss & take-profit
    market_session: str = ""  # 盘前 | 盘中 | 盘后 | 休市
    error: Optional[str] = None


def score_vwap(current_price: float, vwap: float) -> FactorScore:
    """Score based on VWAP position."""
    if vwap == 0:
        return FactorScore('VWAP位置', 0, WEIGHTS['vwap'], '数据不足', '-')
    
    deviation_pct = (current_price - vwap) / vwap * 100
    
    if deviation_pct > 0.5:
        score = 0.8  # Above VWAP, bullish
        detail = f"↑ 在VWAP之上 (+{deviation_pct:.2f}%)"
    elif deviation_pct > 0.1:
        score = 0.3
        detail = f"↗ 略高于VWAP (+{deviation_pct:.2f}%)"
    elif deviation_pct > -0.1:
        score = 0.0
        detail = f"➖ 贴近VWAP ({deviation_pct:.2f}%)"
    elif deviation_pct > -0.5:
        score = -0.3
        detail = f"↘ 略低于VWAP ({deviation_pct:.2f}%)"
    else:
        score = -0.8  # Below VWAP, bearish
        detail = f"↓ 在VWAP之下 ({deviation_pct:.2f}%)"
    
    return FactorScore('VWAP位置', round(score, 2), WEIGHTS['vwap'], detail, f"${vwap:.2f}")


def score_trend(trend_info: dict) -> FactorScore:
    """Score based on short-term trend."""
    direction = trend_info.get('direction', 'neutral')
    strength = trend_info.get('strength', 'weak')
    desc = trend_info.get('description', '')
    
    if direction == 'bullish':
        score = 0.8 if strength == 'strong' else 0.5
    elif direction == 'bearish':
        score = -0.8 if strength == 'strong' else -0.5
    else:
        score = 0.0
    
    ema5 = trend_info.get('ema5', 0)
    ema20 = trend_info.get('ema20', 0)
    value_str = f"EMA5={ema5} EMA20={ema20}"
    
    return FactorScore('短期趋势', round(score, 2), WEIGHTS['trend'], desc, value_str)


def score_rsi(rsi_value: float) -> FactorScore:
    """Score based on RSI. For entry, we want oversold bounce or moderate bullish."""
    if rsi_value < 25:
        # Deep oversold - bounce potential but risky
        score = 0.6
        detail = f"🔻 深度超卖 ({rsi_value}) - 反弹机会"
    elif rsi_value < 35:
        # Mild oversold - good entry zone
        score = 0.8
        detail = f"✅ 超卖区 ({rsi_value}) - 潜在入场点"
    elif rsi_value < 45:
        # Slightly oversold to neutral
        score = 0.3
        detail = f"↗ 偏低 ({rsi_value})"
    elif rsi_value < 60:
        # Sweet spot for continuation
        score = 0.5
        detail = f"➖ 中性偏强 ({rsi_value}) - 趋势延续中"
    elif rsi_value < 70:
        # Getting warm
        score = 0.0
        detail = f"↗ 偏强 ({rsi_value}) - 注意超买"
    elif rsi_value < 80:
        # Overbought - avoid long entry
        score = -0.5
        detail = f"🔺 超买区 ({rsi_value}) - 不适合追多"
    else:
        # Deep overbought
        score = -0.8
        detail = f"⚠️ 深度超买 ({rsi_value}) - 警惕回调"
    
    return FactorScore('RSI(14)', round(score, 2), WEIGHTS['rsi'], detail, str(rsi_value))


def score_volume(volume_ratio: float) -> FactorScore:
    """Score based on volume confirmation."""
    if volume_ratio >= 2.0:
        score = 1.0
        detail = "🔥 巨量 (2x+) - 资金驱动明显"
    elif volume_ratio >= 1.5:
        score = 0.8
        detail = "📊 明显放量 (1.5x+) - 趋势可信"
    elif volume_ratio >= 1.0:
        score = 0.3
        detail = "📊 正常成交量"
    elif volume_ratio >= 0.7:
        score = -0.2
        detail = "📉 略有缩量"
    else:
        score = -0.8
        detail = "⚠️ 显著缩量 - 假突破风险"
    
    return FactorScore('成交量确认', round(score, 2), WEIGHTS['volume'], detail, f"{volume_ratio}x")


def score_price_level(current_price: float, sr: dict) -> FactorScore:
    """Score based on price relative to support/resistance levels."""
    s1 = sr.get('support1', 0)
    r1 = sr.get('resistance1', 0)
    prev_close = sr.get('prev_close', 0)
    
    if s1 == 0 and r1 == 0:
        return FactorScore('价位位置', 0, WEIGHTS['price_level'], '数据不足', '-')
    
    # How close to support? (as % of price)
    dist_to_support = ((current_price - s1) / current_price * 100) if s1 else 999
    dist_to_resistance = ((r1 - current_price) / current_price * 100) if r1 else 999
    
    score = 0.0
    details = []
    
    if dist_to_support < 0.5 and dist_to_support >= 0:
        # Price is at support
        score = 0.7
        details.append(f"🟢 贴近支撑位 ${s1}")
    elif dist_to_support < 1.5:
        score = 0.3
        details.append(f"↗ 接近支撑 (距 {dist_to_support:.2f}%)")
    
    if dist_to_resistance < 0.5:
        # At resistance - cautious
        score = max(score, -0.3) if score < 0 else -0.3
        details.append(f"🔴 贴近阻力位 ${r1}")
    elif dist_to_resistance < 1.5:
        score = min(score, 0.3)  # Room to run
        details.append(f"↗ 距阻力尚有 {dist_to_resistance:.2f}% 空间")
    else:
        details.append(f"✅ 距阻力较远 ({dist_to_resistance:.2f}%)")
        if score >= 0:
            score = score + 0.2
    
    change_from_open = ((current_price - sr.get('today_open', current_price)) / current_price * 100)
    details.append(f"较开盘: {change_from_open:+.2f}%")
    
    detail_str = " | ".join(details)
    value_str = f"S1=${s1} R1=${r1}"
    
    return FactorScore('价位位置', round(score, 2), WEIGHTS['price_level'], detail_str, value_str)


def calc_sl_tp(current_price: float, vwap: float, sr: dict, bb: dict,
               trend_direction: str, total_score: float,
               ticker: str = "") -> dict:
    """
    Calculate suggested stop-loss and take-profit levels for 做T.
    Uses per-ticker optimized params from config when available.
    
    Returns dict with:
        direction: 'long' or 'short'
        sl_price, tp_price: absolute prices
        sl_pct, tp_pct: percentage from current
        rr_ratio: risk/reward ratio
        sl_basis: what the SL is based on (for display)
        tp_basis: what the TP is based on
    """
    s1 = sr.get('support1', 0)
    r1 = sr.get('resistance1', 0)
    bb_upper = bb.get('upper', 0)
    bb_lower = bb.get('lower', 0)
    
    # Per-ticker optimized params
    tp_default = DEFAULT_TP_PCT
    sl_default = DEFAULT_SL_PCT
    if ticker and ticker.upper() in TICKER_PARAMS:
        tp_default = TICKER_PARAMS[ticker.upper()]['tp_pct']
        sl_default = TICKER_PARAMS[ticker.upper()]['sl_pct']
    
    # Default: assume long direction
    if total_score >= 0.2:
        # ── LONG 做多 ────────────────────────────────────
        # Stop-loss candidates (tightest of several methods)
        sl_candidates = []
        
        # Method 1: Below S1 (if S1 exists and is reasonably close)
        if s1 > 0 and (current_price - s1) / current_price < 2.0:
            sl_candidates.append(('S1下方', round(s1 * 0.997, 2)))
        
        # Method 2: Below VWAP (if price is above VWAP)
        if vwap > 0 and current_price > vwap:
            sl_candidates.append(('VWAP下方', round(vwap * 0.997, 2)))
        
        # Method 3: Below EMA5 (if in uptrend)
        # (we'll use a fixed 0.7% fallback)
        
        # Method 4: Below lower BB
        if bb_lower > 0:
            sl_candidates.append(('布林下轨', round(bb_lower * 0.998, 2)))
        
        # Method 5: Fixed % stop (always available)
        sl_pct_fixed = sl_default
        sl_candidates.append((f'固定止损-{sl_pct_fixed:.1f}%', round(current_price * (1 - sl_pct_fixed / 100), 2)))
        
        # Pick the TIGHTEST stop (closest to current price)
        sl_candidates.sort(key=lambda x: current_price - x[1])  # smallest distance first
        sl_basis, sl_price = sl_candidates[0]
        
        # Respect per-ticker config: use configured SL as the minimum
        if ticker and ticker.upper() in TICKER_PARAMS:
            target_sl = round(current_price * (1 - sl_default / 100), 2)
            if sl_price > target_sl:  # candidate is too tight (< loss)
                sl_price = target_sl
                sl_basis = f'配置止损-{sl_default:.1f}%'
        else:
            # Minimum stop based on volatility (Bollinger bandwidth)
            bb_bandwidth = bb.get('bandwidth', 1.0)
            min_sl_pct = max(0.4, bb_bandwidth * 0.3)  # at least 0.4%, scaled with volatility
            min_sl = round(current_price * (1 - min_sl_pct / 100), 2)
            if sl_price < min_sl:  # stop is too tight (noise)
                sl_price = min_sl
                sl_basis = f'动态止损-{min_sl_pct:.1f}%'
        
        # Take-profit candidates
        tp_candidates = []
        
        # Method 1: At R1 (if reasonable)
        if r1 > 0:
            tp_candidates.append(('R1目标', r1))
        
        # Method 2: Upper BB
        if bb_upper > 0:
            tp_candidates.append(('布林上轨', bb_upper))
        
        # Method 3: Fixed % target
        tp_candidates.append((f'固定止盈+{tp_default:.1f}%', round(current_price * (1 + tp_default / 100), 2)))
        if tp_default < 2.0:
            tp_candidates.append(('固定止盈+2.0%', round(current_price * 1.020, 2)))
        
        # Pick the closest reasonable target (at least 0.3% away)
        tp_candidates.sort(key=lambda x: abs(x[1] - current_price))
        for basis, tp in tp_candidates:
            if tp > current_price and (tp - current_price) / current_price >= 0.003:
                tp_basis, tp_price = basis, tp
                break
        else:
            tp_basis, tp_price = f'固定止盈+{tp_default:.1f}%', round(current_price * (1 + tp_default / 100), 2)
        
        # Respect per-ticker TP config: use it as minimum target
        if ticker and ticker.upper() in TICKER_PARAMS:
            min_tp = round(current_price * (1 + tp_default / 100), 2)
            if tp_price < min_tp:
                tp_price = min_tp
                tp_basis = f'配置止盈+{tp_default:.1f}%'
        
        sl_pct = (sl_price - current_price) / current_price * 100
        tp_pct = (tp_price - current_price) / current_price * 100
        direction = 'long'
    
    elif total_score <= -0.4:
        # ── SHORT 做空 ────────────────────────────────────
        sl_candidates = []
        if r1 > 0:
            sl_candidates.append(('R1上方', round(r1 * 1.003, 2)))
        sl_candidates.append((f'固定止损+{sl_default:.1f}%', round(current_price * (1 + sl_default / 100), 2)))
        sl_candidates.sort(key=lambda x: x[1] - current_price)
        sl_basis, sl_price = sl_candidates[0]
        
        tp_candidates = []
        if s1 > 0:
            tp_candidates.append(('S1目标', s1))
        if bb_lower > 0:
            tp_candidates.append(('布林下轨', bb_lower))
        tp_candidates.append((f'固定止盈-{tp_default:.1f}%', round(current_price * (1 - tp_default / 100), 2)))
        tp_candidates.sort(key=lambda x: current_price - x[1])
        for basis, tp in tp_candidates:
            if tp < current_price and (current_price - tp) / current_price >= 0.003:
                tp_basis, tp_price = basis, tp
                break
        else:
            tp_basis, tp_price = '固定止盈-1.5%', round(current_price * 0.985, 2)
        
        sl_pct = (sl_price - current_price) / current_price * 100
        tp_pct = (tp_price - current_price) / current_price * 100
        direction = 'short'
    
    else:
        # ── NEUTRAL 观望 — 也给出参考 ─────────────────────
        sl_price = round(current_price * (1 - sl_default / 100), 2)
        tp_price = round(current_price * (1 + tp_default / 100), 2)
        sl_pct = -sl_default
        tp_pct = tp_default
        sl_basis = '参考止损'
        tp_basis = '参考止盈'
        direction = 'neutral'
    
    # Risk/Reward ratio (绝对值)
    risk = abs(sl_pct)
    reward = abs(tp_pct)
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0
    
    return {
        'direction': direction,
        'sl_price': round(sl_price, 2),
        'tp_price': round(tp_price, 2),
        'sl_pct': round(sl_pct, 2),
        'tp_pct': round(tp_pct, 2),
        'rr_ratio': rr_ratio,
        'sl_basis': sl_basis,
        'tp_basis': tp_basis,
    }


def compute_signal(total_score: float) -> tuple:
    """Convert total score to signal text and emoji. Uses backtest-optimized thresholds."""
    if total_score >= 0.4:  # backtest: 0.4 gives better balance than 0.5
        return "✅ 适合入场", "🟢"
    elif total_score >= 0.2:
        return "🟡 谨慎入场", "🟡"
    elif total_score >= -0.2:
        return "⚪ 观望为宜", "⚪"
    elif total_score >= -0.5:
        return "🔶 不建议入场", "🟠"
    else:
        return "🔴 强烈回避", "🔴"


def analyze_ticker(ticker: str) -> AnalysisResult:
    """
    Full analysis pipeline for a single ticker.
    
    Args:
        ticker: Stock symbol (e.g., 'AAPL')
    
    Returns:
        AnalysisResult with all scores and signal
    """
    result = AnalysisResult(ticker=ticker.upper())
    
    try:
        # 1. Fetch ticker info (company name, current price)
        t = yf.Ticker(ticker)
        info = t.info or {}
        result.company_name = str(info.get('shortName') or info.get('longName') or '')
        result.current_price = round(info.get('currentPrice') or info.get('regularMarketPrice') or 0, 2)
        
        # 2. Fetch intraday data for analysis
        df = fetch_intraday_data(ticker, interval='5m', period='5d')
        
        if df.empty:
            # Fallback: try with 15m data
            df = fetch_intraday_data(ticker, interval='15m', period='1mo')
        
        if df.empty:
            result.error = f"⚠️ 无法获取 {ticker} 的行情数据"
            return result
        
        # Calculate daily change from OHLCV data (more reliable than yfinance info)
        if not df.empty and len(df) >= 2:
            today = datetime.now(timezone.utc).date()
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC')
            today_data = df[df.index.date == today]
            prev_data = df[df.index.date < today]
            if not today_data.empty:
                day_open = today_data['Open'].iloc[0]
                day_close = today_data['Close'].iloc[-1]
                if day_open and day_open != 0:
                    result.change_pct = round((day_close - day_open) / day_open * 100, 2)
            elif not prev_data.empty:
                # Pre-market: compare to previous close
                prev_close = prev_data['Close'].iloc[-1]
                current_price = result.current_price if result.current_price > 0 else df['Close'].iloc[-1]
                if prev_close:
                    result.change_pct = round((current_price - prev_close) / prev_close * 100, 2)
        
        # Detect market session (pre-market / regular / after-hours)
        result.market_session = detect_market_session(df)
        
        # 3. Calculate all indicators
        vwap = calc_session_vwap(df)
        trend_info = detect_trend(df)
        rsi_val = calc_rsi(df['Close'], 14)
        vol_ratio = calc_volume_ratio(df)
        sr = calc_support_resistance(df)
        bb = calc_bollinger_bands(df)
        sentiment = get_market_sentiment()
        
        # 4. Score each factor
        current_price = result.current_price if result.current_price > 0 else df['Close'].iloc[-1]
        
        factors = [
            score_vwap(current_price, vwap),
            score_trend(trend_info),
            score_rsi(rsi_val),
            score_volume(vol_ratio),
            score_price_level(current_price, sr),
        ]
        
        # 5. Apply market sentiment adjustment (±0.1)
        sentiment_adj = 0.0
        if sentiment['direction'] == 'bullish':
            sentiment_adj = 0.1
        elif sentiment['direction'] == 'bearish':
            sentiment_adj = -0.1
        
        # 6. Compute total weighted score
        total = sum(f.score * f.weight for f in factors) + sentiment_adj
        total = max(-1.0, min(1.0, total))  # Clamp to [-1, 1]
        
        result.factors = factors
        result.total_score = round(total, 2)
        result.signal, result.signal_color = compute_signal(total)
        result.support_resistance = sr
        result.bollinger = bb
        result.market_sentiment = sentiment
        
        # 7. Update price with extended hours (pre/post market) if available
        ext_price = fetch_current_price(ticker)
        if ext_price["price"] > 0:
            current_price = ext_price["price"]
            result.current_price = ext_price["price"]
            result.change_pct = ext_price["change_pct"]
        
        # 8. Calculate stop-loss / take-profit levels
        result.sl_tp = calc_sl_tp(
            current_price, vwap, sr, bb,
            trend_info.get('direction', 'neutral'),
            total, ticker=result.ticker
        )
        
    except Exception as e:
        logger.error(f"Error analyzing {ticker}: {e}")
        result.error = f"分析异常: {str(e)[:100]}"
    
    return result


def analyze_multiple(tickers: list[str]) -> list[AnalysisResult]:
    """Analyze multiple tickers."""
    return [analyze_ticker(t) for t in tickers]


def format_result(result: AnalysisResult, verbose: bool = True) -> str:
    """Format analysis result for Telegram display."""
    if result.error:
        return f"{result.error}"
    
    lines = []
    
    # Header
    change_str = f"{result.change_pct:+.2f}%" if result.change_pct else ""
    lines.append(
        f"{result.signal_color} **{result.ticker}**"
        f"{' - ' + result.company_name if result.company_name else ''}"
    )
    lines.append(f"`${result.current_price:.2f}` {change_str}")
    if result.market_session:
        lines.append(f"⏰ {result.market_session}")
    lines.append(f"**评分: {result.total_score:+.2f}** → {result.signal}")
    lines.append("")
    
    # ── 三级信号共振检测 ────────────────────────────────────
    volume_ratio_high = any(
        f.name == '成交量确认' and f.score >= 0.8
        for f in result.factors
    )
    if (result.total_score >= 0.4
            and result.sl_tp.get('rr_ratio', 0) >= 2.0
            and volume_ratio_high):
        lines.append("🔥🔥 **三级信号共振 — 适合上仓位！** 🔥🔥")
        lines.append("   🟢 综合评分≥0.4 | ⭐ 盈亏比≥2.0 | 📊 放量1.5x+")
        lines.append("")
    
    # Factor breakdown
    for f in result.factors:
        bar = _score_bar(f.score)
        lines.append(f"{bar} **{f.name}**: {f.detail}")
        if verbose and f.value:
            lines.append(f"   └─ {f.value}")
    
    # Market sentiment
    if result.market_sentiment:
        sent = result.market_sentiment
        lines.append("")
        lines.append(f"📊 **大盘情绪**: {sent.get('description', 'N/A')}")
        lines.append(f"   SPY: {sent.get('spy_change', 0):+.2f}% | QQQ: {sent.get('qqq_change', 0):+.2f}%")
    
    # Support/Resistance
    if verbose and result.support_resistance:
        sr = result.support_resistance
        lines.append("")
        lines.append(f"📐 **关键价位**")
        lines.append(f"   阻力2: ${sr.get('resistance2', 0)}")
        lines.append(f"   阻力1: ${sr.get('resistance1', 0)}")
        lines.append(f"   ──── 当前 ${result.current_price:.2f} ────")
        lines.append(f"   支撑1: ${sr.get('support1', 0)}")
        lines.append(f"   支撑2: ${sr.get('support2', 0)}")
    
    # Bollinger
    if verbose and result.bollinger and result.bollinger.get('upper'):
        bb = result.bollinger
        bb_pos = bb.get('position', 0.5)
        bb_signal = "上轨" if bb_pos > 0.8 else "下轨" if bb_pos < 0.2 else "中轨附近"
        lines.append("")
        lines.append(f"📉 **布林带**")
        lines.append(f"   上轨 ${bb['upper']} | 中轨 ${bb['middle']} | 下轨 ${bb['lower']}")
        lines.append(f"   带宽 {bb['bandwidth']}% | 价格在 {bb_signal} ({(bb_pos*100):.0f}%位置)")
    
    # Stop-Loss / Take-Profit
    if result.sl_tp:
        sl = result.sl_tp
        dir_emoji = "📈" if sl['direction'] == 'long' else "📉" if sl['direction'] == 'short' else "➖"
        rr = sl['rr_ratio']
        rr_icon = "⭐" if rr >= 2.0 else "👍" if rr >= 1.5 else "👌"
        lines.append("")
        lines.append(f"🎯 **做T计划** {dir_emoji}")
        lines.append(f"   止损: **${sl['sl_price']:.2f}** ({sl['sl_pct']:+.2f}%) ← {sl['sl_basis']}")
        lines.append(f"   止盈: **${sl['tp_price']:.2f}** ({sl['tp_pct']:+.2f}%) → {sl['tp_basis']}")
        lines.append(f"   盈亏比: {rr}:1 {rr_icon}")
    
    return "\n".join(lines)


def _score_bar(score: float, width: int = 10) -> str:
    """Visual bar for score (e.g., ██████░░░░ for 0.6)."""
    filled = max(0, min(width, int((score + 1) / 2 * width)))
    empty = width - filled
    if score >= 0:
        return "🟢" + "█" * filled + "░" * empty
    else:
        return "🔴" + "█" * filled + "░" * empty


if __name__ == '__main__':
    # Quick test
    import sys
    test_ticker = sys.argv[1] if len(sys.argv) > 1 else 'AAPL'
    result = analyze_ticker(test_ticker)
    print(format_result(result, verbose=True))
