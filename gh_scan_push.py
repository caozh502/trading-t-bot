"""GitHub Actions 定时推送：扫自选股并推送到 Telegram。
支持盘前盘后（夜盘）实时价格。
用法: python gh_scan_push.py
环境变量: TG_BOT_TOKEN, TG_CHAT_ID
"""
import os, sys, requests
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(__file__))
from config import DEFAULT_WATCHLIST, TICKER_PARAMS, DEFAULT_SL_PCT, DEFAULT_TP_PCT
from indicators import calc_rsi, calc_ema, calc_volume_ratio

results = []

for ticker in DEFAULT_WATCHLIST:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}
        company = str(info.get('shortName') or info.get('longName') or ticker)
        
        # Get extended hours price (prepost=True includes pre/post market)
        df = t.history(period='2d', interval='5m', prepost=True, auto_adjust=True)
        if df.empty:
            results.append(f"⚠️ {ticker:5s} | 无数据")
            continue
        
        if isinstance(df.columns, type(df.columns)) and hasattr(df.columns, 'get_level_values'):
            df.columns = df.columns.get_level_values(0)
        
        # Current price: last bar (could be after-hours)
        last = df.iloc[-1]
        current_price = last['Close']
        
        # Determine if we're in after-hours
        now = datetime.now(timezone.utc)
        is_extended = False
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        last_time = df.index[-1]
        last_minutes = last_time.hour * 60 + last_time.minute
        # Regular market: 9:30-16:00 ET = 13:30-20:00 UTC
        is_extended = last_minutes < 13 * 60 + 30 or last_minutes > 20 * 60
        ext_label = "🌙" if is_extended else ""
        
        # Daily change from previous close
        prev_close = info.get('regularMarketPreviousClose', 0)
        change_pct = ((current_price - prev_close) / prev_close * 100) if prev_close else 0
        
        # Simplified score based on current data
        close_series = df['Close']
        rsi = calc_rsi(close_series, 14)
        ema5 = calc_ema(close_series, 5)
        ema20 = calc_ema(close_series, 20)
        
        # Simple scoring
        score = 0.0
        if current_price > ema5 > ema20: score += 0.4
        elif current_price > ema20: score += 0.2
        if rsi and rsi < 35: score += 0.2
        elif rsi and rsi > 70: score -= 0.2
        if current_price > prev_close: score += 0.1
        
        score = max(-1.0, min(1.0, round(score, 2)))
        signal = "✅ 适合入场" if score >= 0.4 else "🟡 谨慎入场" if score >= 0.2 else "⚪ 观望为宜"
        emoji = "🟢" if score >= 0.4 else "🟡" if score >= 0.2 else "⚪"
        
        # Per-ticker SL/TP
        sl_pct = TICKER_PARAMS.get(ticker, {}).get('sl_pct', DEFAULT_SL_PCT)
        tp_pct = TICKER_PARAMS.get(ticker, {}).get('tp_pct', DEFAULT_TP_PCT)
        sl_price = current_price * (1 - sl_pct/100)
        tp_price = current_price * (1 + tp_pct/100)
        rr_ratio = round(tp_pct / sl_pct, 2) if sl_pct else 1.0
        
        # ── 三级信号共振检测 ────────────────────────────────────
        vol_ratio = calc_volume_ratio(df)
        triple_tag = ""
        if score >= 0.4 and rr_ratio >= 2.0 and vol_ratio >= 1.5:
            triple_tag = " 🔥🔥共振"
        
        lines = (
            f"{emoji} {ticker:5s} {ext_label}{triple_tag} | ${current_price:<7.2f} {change_pct:+.2f}%"
            f" | 评分{score:+.2f} {signal}"
        )
        results.append(lines)
        
    except Exception as e:
        results.append(f"⚠️ {ticker:5s} | 出错: {str(e)[:40]}")

now = datetime.now()
msg = (
    f"📋 **自选股扫描** ({now.strftime('%m/%d %H:%M')} UTC)\n"
    f"{'─'*35}\n"
    + "\n".join(results)
    + f"\n{'─'*35}\n"
    + "🌙 = 盘后价格\n\n"
    + "💡 实时分析请在 Bot 中使用 /t 命令"
)

token = os.environ['TG_BOT_TOKEN']
chat_id = os.environ['TG_CHAT_ID']
url = f"https://api.telegram.org/bot{token}/sendMessage"
data = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
resp = requests.post(url, data=data).json()
print(resp.get("description", resp.get("ok", "sent")))
