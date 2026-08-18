"""
signal-tracker config — 30-day paper trading signal experiment.
Stock pool is chosen by the AI (user gives no input).
"""
import os

# ── Stock pool (AI-chosen, cross-sector) ─────────────────────
# 5 semis + 2 AI hardware + software + auto + space
STOCK_POOL = ["NVDA", "AMD", "MU", "AVGO", "ARM",
              "SMCI", "MRVL", "PLTR", "TSLA", "RKLB"]

# Market-sentiment filter instrument (not a tradeable signal)
SENTIMENT_TICKERS = ["QQQ", "SPY"]

# ── Scan schedule (US Eastern) ───────────────────────────────
# Scan 1: 09:45 ET (open + 15 min), Scan 2: 13:00 ET (midday)
# Signals from scan 1 and 2 both settle at 16:00 ET close.
SCAN_TIMES_ET = ["09:45", "13:00"]
MAX_SIGNALS_PER_SCAN = 2          # strongest 2 per scan
MAX_SIGNALS_PER_TICKER_PER_DAY = 1
MAX_SAME_SECTOR_PER_SCAN = 1      # avoid 2 semis in same scan

# ── Trade simulation params ──────────────────────────────────
# Fixed nominal size per signal (paper): 1000 EUR equivalent
PAPER_NOMINAL = 1000.0
# Score threshold: only signals with |score| >= this qualify
MIN_SCORE_ABS = 0.20
# Direction: short allowed only if direction short score >= 55
SHORT_MIN_SCORE = 55
# Per-trade risk cap: SL distance must be >= 0.25% (avoid noise stops)
MIN_SL_PCT = 0.25
# Conservative rule: if same 5m bar touches both SL and TP, count as SL
CONSERVATIVE_SAME_BAR = True

# ── Paths ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "signals.db")
REPORT_DIR = os.path.join(BASE_DIR, "reports")
LOG_PATH = os.path.join(BASE_DIR, "tracker.log")

# ── Sector map (for same-sector dedup) ───────────────────────
SECTOR = {
    "NVDA": "semi", "AMD": "semi", "MU": "semi", "AVGO": "semi", "ARM": "semi",
    "SMCI": "aihw", "MRVL": "aihw",
    "PLTR": "soft", "TSLA": "auto", "RKLB": "space",
}

# ── Report ───────────────────────────────────────────────────
EXPERIMENT_DAYS = 30
