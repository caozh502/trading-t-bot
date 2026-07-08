"""
Technical indicator calculations for intraday trading analysis.
Uses yfinance for data, pandas for calculations.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, timezone
import logging
import requests

# Global session using requests (SSL disabled for Railway compatibility)
import os
os.environ['PYTHONHTTPSVERIFY'] = '0'

_session = requests.Session()
_session.verify = False
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
})
import urllib3
urllib3.disable_warnings()

def get_session():
    return _session

logger = logging.getLogger(__name__)


def fetch_intraday_data(ticker: str, interval: str = "5m", period: str = "5d") -> pd.DataFrame:
    """
    Fetch intraday price data.
    
    Args:
        ticker: Stock symbol (e.g., 'AAPL')
        interval: '1m', '5m', '15m', '30m', '1h'
        period: '1d', '5d', '1mo', etc. (max depends on interval)
    
    Returns:
        DataFrame with OHLCV data, or empty DataFrame on failure
    """
    try:
        # For 1m data, max period is 7d; for 5m, max is 60d
        t = yf.Ticker(ticker, session=get_session())
        df = t.history(period=period, interval=interval)
        if df.empty:
            logger.warning(f"No data returned for {ticker} ({interval}/{period})")
            return pd.DataFrame()
        return df
    except Exception as e:
        logger.error(f"Error fetching intraday data for {ticker}: {e}")
        return pd.DataFrame()


def fetch_current_price(ticker: str) -> dict:
    """
    Fetch the most recent price including extended hours (pre/post market).
    Returns dict with price, change_pct, and source label.
    Falls back to regular market price if extended hours unavailable.
    """
    import yfinance as yf
    result = {"price": 0, "change_pct": 0, "source": ""}
    try:
        t = yf.Ticker(ticker, session=get_session())
        # Try with extended hours first
        df = t.history(period="2d", interval="5m", prepost=True)
        if df.empty:
            # Fallback to regular hours
            df = t.history(period="2d", interval="5m")
        if df.empty:
            # Last resort: info
            info = t.info or {}
            result["price"] = info.get("currentPrice") or info.get("regularMarketPrice") or 0
            return result
        
        if isinstance(df.columns, type(df.columns)) and hasattr(df.columns, 'get_level_values'):
            df.columns = df.columns.get_level_values(0)
        
        # Most recent price
        last = df.iloc[-1]
        result["price"] = round(float(last["Close"]), 2)
        
        # Previous close for change calculation
        info = t.info or {}
        prev_close = info.get("regularMarketPreviousClose", 0)
        if prev_close:
            result["change_pct"] = round((result["price"] - prev_close) / prev_close * 100, 2)
        
        # Determine source
        from datetime import timezone
        last_time = df.index[-1]
        if last_time.tzinfo is None:
            last_time = last_time.tz_localize("UTC")
        et_minutes = last_time.hour * 60 + last_time.minute - 4 * 60  # EDT offset
        if et_minutes < 0:
            et_minutes += 24 * 60
        if et_minutes < 9 * 60 + 30 or et_minutes >= 16 * 60:
            result["source"] = "ext"
        else:
            result["source"] = "regular"
        
        return result
    except Exception as e:
        logger.error(f"Error fetching extended price for {ticker}: {e}")
        return result


def calc_vwap(df: pd.DataFrame) -> float:
    """
    Calculate Volume-Weighted Average Price from intraday data.
    VWAP = Σ(Price_i * Volume_i) / Σ(Volume_i)
    
    Uses typical price = (High + Low + Close) / 3
    """
    if df.empty or 'Volume' not in df.columns:
        return 0.0
    df = df.copy()
    df['TypicalPrice'] = (df['High'] + df['Low'] + df['Close']) / 3
    df['PV'] = df['TypicalPrice'] * df['Volume']
    cumul_pv = df['PV'].sum()
    cumul_vol = df['Volume'].sum()
    if cumul_vol == 0:
        return 0.0
    return cumul_pv / cumul_vol


def calc_session_vwap(df: pd.DataFrame) -> float:
    """
    Calculate VWAP for today's session only (intraday).
    Filters to today's data if available.
    """
    if df.empty:
        return 0.0
    today = datetime.now(timezone.utc).date()
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    today_data = df[df.index.date == today]
    if today_data.empty:
        today_data = df  # fallback to all data
    return calc_vwap(today_data)


def calc_rsi(series: pd.Series, period: int = 14) -> float:
    """
    Calculate RSI (Relative Strength Index).
    RSI = 100 - (100 / (1 + RS))
    RS = AvgGain / AvgLoss over the period
    """
    if len(series) < period + 1:
        return 50.0  # neutral default
    
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    
    avg_gain = gain.rolling(window=period, min_periods=period).mean().iloc[-1]
    avg_loss = loss.rolling(window=period, min_periods=period).mean().iloc[-1]
    
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 1)


def calc_ema(series: pd.Series, period: int) -> float:
    """Calculate EMA (Exponential Moving Average) for the latest value."""
    if len(series) < period:
        return series.iloc[-1] if len(series) > 0 else 0.0
    ema = series.ewm(span=period, adjust=False).mean()
    return round(ema.iloc[-1], 2)


def detect_trend(df: pd.DataFrame) -> dict:
    """
    Detect short-term trend direction using 5EMA and 20EMA.
    
    Returns:
        dict with:
            direction: 'bullish', 'bearish', 'neutral'
            strength: 'strong', 'moderate', 'weak'
            ema5: float
            ema20: float
            description: str
    """
    if df.empty or len(df) < 20:
        return {'direction': 'neutral', 'strength': 'weak', 
                'ema5': 0, 'ema20': 0, 'description': '数据不足'}
    
    close = df['Close']
    ema5 = calc_ema(close, 5)
    ema20 = calc_ema(close, 20)
    
    # Check current and previous bar for direction
    ema5_series = close.ewm(span=5, adjust=False).mean()
    ema20_series = close.ewm(span=20, adjust=False).mean()
    
    # Current relationship
    ema5_above_20 = ema5 > ema20
    
    # Trend of EMAs themselves (are they sloping up or down?)
    ema5_slope = ema5_series.diff().iloc[-3:].mean() if len(ema5_series) >= 3 else 0
    ema20_slope = ema20_series.diff().iloc[-3:].mean() if len(ema20_series) >= 3 else 0
    
    # Price relative to EMAs
    last_close = close.iloc[-1]
    price_above_ema5 = last_close > ema5
    price_above_ema20 = last_close > ema20
    
    # Scoring
    bullish_signals = sum([
        ema5_above_20,
        ema5_slope > 0,
        ema20_slope > 0,
        price_above_ema5,
        price_above_ema20
    ])
    
    bearish_signals = sum([
        not ema5_above_20,
        ema5_slope < 0,
        ema20_slope < 0,
        not price_above_ema5,
        not price_above_ema20
    ])
    
    if bullish_signals >= 4:
        direction, strength, desc = 'bullish', 'strong', '强劲多头排列'
    elif bullish_signals == 3:
        direction, strength, desc = 'bullish', 'moderate', '偏多'
    elif bearish_signals >= 4:
        direction, strength, desc = 'bearish', 'strong', '强劲空头排列'
    elif bearish_signals == 3:
        direction, strength, desc = 'bearish', 'moderate', '偏空'
    else:
        direction, strength, desc = 'neutral', 'weak', '横盘震荡'
    
    return {
        'direction': direction,
        'strength': strength,
        'ema5': round(ema5, 2),
        'ema20': round(ema20, 2),
        'description': desc,
        'above_ema5': price_above_ema5,
        'above_ema20': price_above_ema20
    }


def calc_support_resistance(df: pd.DataFrame) -> dict:
    """
    Calculate key support and resistance levels.
    
    Uses:
    - Yesterday's close
    - Today's open
    - Intraday high/low
    - Pivot points
    
    Returns:
        dict with support, resistance levels
    """
    if df.empty:
        return {'support1': 0, 'support2': 0, 'resistance1': 0, 'resistance2': 0,
                'today_open': 0, 'prev_close': 0, 'today_high': 0, 'today_low': 0}
    
    today = datetime.now(timezone.utc).date()
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    
    # Split into today and previous data
    today_data = df[df.index.date == today]
    prev_data = df[df.index.date < today]
    
    if len(today_data) == 0:
        # Pre-market / no intraday data yet
        today_data = df.tail(2)
    
    today_high = today_data['High'].max() if not today_data.empty else 0
    today_low = today_data['Low'].min() if not today_data.empty else 0
    today_open = today_data['Open'].iloc[0] if not today_data.empty else 0
    
    # Previous close = last bar of previous day
    if not prev_data.empty:
        prev_close = prev_data['Close'].iloc[-1]
    else:
        prev_close = df['Close'].iloc[0] if not df.empty else 0
    
    # Simple pivot points
    pivot = (today_high + today_low + prev_close) / 3 if prev_close else 0
    
    r1 = 2 * pivot - today_low if pivot else 0
    r2 = pivot + (today_high - today_low) if pivot else 0
    s1 = 2 * pivot - today_high if pivot else 0
    s2 = pivot - (today_high - today_low) if pivot else 0
    
    return {
        'support1': round(s1, 2),
        'support2': round(s2, 2),
        'resistance1': round(r1, 2),
        'resistance2': round(r2, 2),
        'today_open': round(today_open, 2),
        'prev_close': round(prev_close, 2),
        'today_high': round(today_high, 2),
        'today_low': round(today_low, 2),
        'pivot': round(pivot, 2)
    }


def calc_volume_ratio(df: pd.DataFrame) -> float:
    """
    Calculate current volume vs average volume.
    Compares today's volume so far to the average per-bar volume of previous days.
    """
    if df.empty or 'Volume' not in df.columns:
        return 1.0
    
    today = datetime.now(timezone.utc).date()
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    
    today_data = df[df.index.date == today]
    prev_data = df[df.index.date < today]
    
    if len(today_data) == 0 or len(prev_data) == 0:
        return 1.0
    
    today_avg_vol = today_data['Volume'].mean()
    prev_avg_vol = prev_data['Volume'].mean()
    
    if prev_avg_vol == 0:
        return 1.0
    
    ratio = today_avg_vol / prev_avg_vol
    return round(ratio, 2)


def calc_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: int = 2) -> dict:
    """
    Calculate Bollinger Bands.
    """
    if df.empty or len(df) < period:
        return {'upper': 0, 'middle': 0, 'lower': 0, 'bandwidth': 0, 'position': 0.5}
    
    close = df['Close']
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    
    upper = sma.iloc[-1] + (std_dev * std.iloc[-1])
    middle = sma.iloc[-1]
    lower = sma.iloc[-1] - (std_dev * std.iloc[-1])
    
    current = close.iloc[-1]
    if upper == lower:
        position = 0.5
    else:
        position = (current - lower) / (upper - lower)
    
    bandwidth = ((upper - lower) / middle * 100) if middle != 0 else 0
    
    return {
        'upper': round(upper, 2),
        'middle': round(middle, 2),
        'lower': round(lower, 2),
        'bandwidth': round(bandwidth, 2),
        'position': round(position, 2)
    }


def get_market_sentiment() -> dict:
    """
    Get overall market sentiment from SPY and QQQ.
    Returns dict with direction and description.
    """
    try:
        spy_data = fetch_intraday_data('SPY', interval='5m', period='2d')
        qqq_data = fetch_intraday_data('QQQ', interval='5m', period='2d')
        
        spy_change = 0
        qqq_change = 0
        
        if not spy_data.empty and len(spy_data) >= 2:
            spy_change = ((spy_data['Close'].iloc[-1] - spy_data['Close'].iloc[0]) 
                         / spy_data['Close'].iloc[0] * 100)
        
        if not qqq_data.empty and len(qqq_data) >= 2:
            qqq_change = ((qqq_data['Close'].iloc[-1] - qqq_data['Close'].iloc[0]) 
                         / qqq_data['Close'].iloc[0] * 100)
        
        avg_change = (spy_change + qqq_change) / 2
        
        if avg_change > 0.5:
            direction, desc = 'bullish', '🔥 大盘偏强'
        elif avg_change > 0.1:
            direction, desc = 'slightly_bullish', '📈 大盘略强'
        elif avg_change > -0.1:
            direction, desc = 'neutral', '➖ 大盘震荡'
        elif avg_change > -0.5:
            direction, desc = 'slightly_bearish', '📉 大盘略弱'
        else:
            direction, desc = 'bearish', '❄️ 大盘偏弱'
        
        return {
            'direction': direction,
            'description': desc,
            'spy_change': round(spy_change, 2),
            'qqq_change': round(qqq_change, 2)
        }
    except Exception as e:
        logger.error(f"Error getting market sentiment: {e}")
        return {'direction': 'unknown', 'description': '无法获取', 'spy_change': 0, 'qqq_change': 0}


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal_period: int = 9) -> dict:
    """
    Calculate MACD (Moving Average Convergence Divergence).
    
    Returns:
        macd: MACD line (fast EMA - slow EMA)
        signal: Signal line (EMA of MACD)
        histogram: MACD - Signal
        cross: 'bullish' (macd crossed above signal), 'bearish', or 'none'
    """
    if len(close) < slow + signal_period:
        return {'macd': 0, 'signal': 0, 'histogram': 0, 'cross': 'none'}
    
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    
    # Detect cross
    macd_curr = macd_line.iloc[-1]
    signal_curr = signal_line.iloc[-1]
    macd_prev = macd_line.iloc[-2] if len(macd_line) >= 2 else macd_curr
    signal_prev = signal_line.iloc[-2] if len(signal_line) >= 2 else signal_curr
    
    if macd_prev <= signal_prev and macd_curr > signal_curr:
        cross = 'bullish'
    elif macd_prev >= signal_prev and macd_curr < signal_curr:
        cross = 'bearish'
    else:
        cross = 'none'
    
    return {
        'macd': round(macd_curr, 4),
        'signal': round(signal_curr, 4),
        'histogram': round(histogram.iloc[-1], 4),
        'cross': cross,
        'histogram_dir': 'rising' if histogram.iloc[-1] > histogram.iloc[-2] else 'falling',
    }


def calc_fibonacci_levels(df: pd.DataFrame, lookback: int = 60) -> dict:
    """
    Calculate Fibonacci retracement and extension levels from recent swing high/low.
    
    Args:
        df: DataFrame with High/Low columns
        lookback: Number of bars to look back for swing points
    
    Returns:
        dict with high, low, and retracement/extension levels
    """
    if df.empty or len(df) < lookback:
        return {'high': 0, 'low': 0, 'levels': {}, 'current_zone': ''}
    
    recent = df.tail(lookback)
    high = recent['High'].max()
    low = recent['Low'].min()
    diff = high - low
    
    if diff == 0:
        return {'high': high, 'low': low, 'levels': {}, 'current_zone': ''}
    
    # Downward retracement (from high to low): levels above current
    # Upward retracement (from low to high): levels below current
    # Determine trend direction
    first_close = recent['Close'].iloc[0]
    last_close = recent['Close'].iloc[-1]
    uptrend = last_close > first_close
    
    if uptrend:
        swing_high = high
        swing_low = low
    else:
        swing_high = high  # actually the high of the range
        swing_low = low    # actually the low of the range
    
    ratios = [0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.414, 1.618]
    levels = {}
    
    for r in ratios:
        if uptrend:
            # Retracement down from high, extension up from high
            level = swing_high - (swing_high - swing_low) * r
            label = f"{'支' if r <= 1.0 else '延'}{r:.3f}"
        else:
            # Retracement up from low, extension down from low
            level = swing_low + (swing_high - swing_low) * r
            label = f"{'阻' if r <= 1.0 else '延'}{r:.3f}"
        levels[label] = round(level, 2)
    
    # Determine current zone
    current_price = last_close
    zone = ""
    sorted_levels = sorted(levels.items(), key=lambda x: x[1])
    for i, (label, level) in enumerate(sorted_levels):
        if i == 0 and current_price < level:
            zone = f"低于{label} ({level})"
            break
        if i == len(sorted_levels) - 1 and current_price > level:
            zone = f"高于{label} ({level})"
            break
        if i < len(sorted_levels) - 1:
            next_label, next_level = sorted_levels[i + 1]
            if current_price >= level and current_price < next_level:
                zone = f"{label}~{next_label} ({level}-{next_level})"
                break
    
    return {
        'high': round(high, 2),
        'low': round(low, 2),
        'trend': 'uptrend' if uptrend else 'downtrend',
        'levels': levels,
        'current_zone': zone,
    }


def detect_market_session(df=None) -> str:
    """Detect current market session based on current ET time."""
    from datetime import datetime, timezone
    try:
        now_utc = datetime.now(timezone.utc)
        et_minutes = now_utc.hour * 60 + now_utc.minute - 4 * 60  # EDT
        if et_minutes < 0:
            et_minutes += 24 * 60
        if et_minutes < 4 * 60:
            return "🌙 盘后"
        elif et_minutes < 9 * 60 + 30:
            return "🌅 盘前"
        elif et_minutes < 16 * 60:
            return "📊 盘中"
        else:
            return "🌙 盘后"
    except Exception:
        return ""


if __name__ == '__main__':
    # Quick test
    df = fetch_intraday_data('AAPL')
    if not df.empty:
        print(f"AAPL intraday data: {len(df)} bars")
        print(f"Close: {df['Close'].iloc[-1]:.2f}")
        print(f"VWAP: {calc_vwap(df):.2f}")
        print(f"RSI(14): {calc_rsi(df['Close'])}")
        print(f"Trend: {detect_trend(df)}")
        print(f"Volume ratio: {calc_volume_ratio(df)}")
        print(f"Market sentiment: {get_market_sentiment()}")
