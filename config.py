"""
Configuration for the trading T-bot.
Edit this file to customize watchlist, weights, and parameters.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
ALLOWED_CHAT_IDS = os.getenv("TG_ALLOWED_CHAT_IDS", "")

# ── Factor weights (should sum to 1.0) ────────────────────────
WEIGHTS = {
    "vwap": 0.25,        # VWAP position
    "trend": 0.25,       # Short-term trend (EMA)
    "rsi": 0.20,         # RSI oversold/oversold
    "volume": 0.15,      # Volume confirmation
    "price_level": 0.15, # Support/resistance proximity
}

# ── Signal thresholds (backtest-optimized) ─────────────────────
# Backtest (30d) showed optimal: threshold=0.2~0.3, TP=1.5~2.0%, SL=0.4~0.6%
SIGNAL_THRESHOLDS = {
    "strong_buy": 0.4,    # >= 0.4 → ✅ 适合入场 (was 0.5)
    "cautious_buy": 0.2,  # >= 0.2 → 🟡 谨慎入场 (was 0.2, kept)
    "cautious_sell": -0.2, # <= -0.2 → 🟠
    "strong_sell": -0.5,   # <= -0.5 → 🔴
}

# ── Default SL/TP (backtest-optimized) ─────────────────────────
DEFAULT_SL_PCT = 0.5      # Stop-loss: 0.5% (tight but not too tight)
DEFAULT_TP_PCT = 1.5      # Take-profit: 1.5% (backtest shows 1.5-2% optimal)

# ── Per-ticker overrides (based on 30-day backtest) ────────────
TICKER_PARAMS = {
    "MRVL": {"sl_pct": 0.4, "tp_pct": 2.0, "threshold_bias": 0.0},
    "RKLB": {"sl_pct": 0.4, "tp_pct": 2.0, "threshold_bias": 0.0},
    "NVDA": {"sl_pct": 0.6, "tp_pct": 1.2, "threshold_bias": 0.05},
    "MU":   {"sl_pct": 0.5, "tp_pct": 1.5, "threshold_bias": 0.05},
    "QQQ":  {"sl_pct": 0.5, "tp_pct": 1.2, "threshold_bias": -0.05},
}

# ── Indicator parameters ──────────────────────────────────────
INDICATOR_PARAMS = {
    "rsi_period": 14,
    "ema_fast": 5,
    "ema_slow": 20,
    "bollinger_period": 20,
    "bollinger_std": 2,
}

# ── Default watchlist (your key stocks) ───────────────────────
# Edit this list to match your portfolio / focus stocks
DEFAULT_WATCHLIST = [
    "TSM",    # 台积电 — 全球半导体景气风向标 (持仓TSFA)
    "MRVL",   # 迈威尔 — AI算力/网络芯片主线 (持仓9MW)
    "RKLB",   # Rocket Lab — 高beta成长, 风险偏好温度计 (持仓6RJ)
    "ASTS",   # AST SpaceMobile — 卫星通信+散户情绪 (持仓NPA)
    "GOOGL",  # 谷歌 — 大盘科技/纳指核心权重
]

# ── Intraday data params ──────────────────────────────────────
INTRADAY_INTERVAL = "5m"    # Bar size: 1m, 5m, 15m, 30m
INTRADAY_PERIOD = "5d"      # Lookback: 1d, 5d, 1mo, 3mo

# ── Market benchmarks ─────────────────────────────────────────
MARKET_BENCHMARKS = ["SPY", "QQQ"]

# ── Display ───────────────────────────────────────────────────
VERBOSE_DEFAULT = True       # Show full detail (SR levels, Bollinger)
