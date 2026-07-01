"""
Vercel Serverless — Telegram Bot Webhook
Synchronous processing optimized for Vercel's 10s timeout.
"""
import sys, os, json, logging, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask, request, jsonify
from config import TELEGRAM_BOT_TOKEN, DEFAULT_WATCHLIST

app = Flask(__name__)
logger = logging.getLogger(__name__)


def _send(chat_id: int, text: str):
    """Send a Telegram message."""
    import requests
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        logger.error(f"send error: {e}")


def _analyze_fast(ticker: str) -> str:
    """Fast analysis path — minimize yfinance calls."""
    import yfinance as yf
    import pandas as pd
    from datetime import datetime, timezone
    from indicators import calc_session_vwap, calc_rsi, calc_ema, calc_volume_ratio, calc_support_resistance, calc_bollinger_bands
    
    ticker = ticker.upper()
    
    # Get ticker info (company name + current price) — one call
    t = yf.Ticker(ticker)
    info = t.info or {}
    company = str(info.get('shortName') or info.get('longName') or ticker)
    price = round(info.get('currentPrice') or info.get('regularMarketPrice') or 0, 2)
    
    # Get OHLCV data — minimal period
    df = t.history(period='3d', interval='5m')
    if df.empty:
        return f"⚠️ 无法获取 {ticker} 数据"
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    current_price = price if price > 0 else df['Close'].iloc[-1]
    
    # Calculate indicators
    vwap = calc_session_vwap(df)
    rsi = calc_rsi(df['Close'], 14)
    trend = detect_trend_fast(df)
    sr = calc_support_resistance(df)
    bb = calc_bollinger_bands(df)
    vol = calc_volume_ratio(df)
    
    # Daily change from OHLCV
    today = datetime.now(timezone.utc).date()
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    today_data = df[df.index.date == today]
    change_pct = 0.0
    if not today_data.empty:
        day_open = today_data['Open'].iloc[0]
        day_close = today_data['Close'].iloc[-1]
        if day_open:
            change_pct = (day_close - day_open) / day_open * 100
    
    # Score
    score = calculate_score_fast(current_price, vwap, rsi, trend, vol, sr)
    
    # SL/TP
    sl_tp = calc_sl_tp_fast(current_price, vwap, sr, bb, ticker)
    
    # Format
    signal = "✅ 适合入场" if score >= 0.4 else "🟡 谨慎入场" if score >= 0.2 else "⚪ 观望为宜"
    emoji = "🟢" if score >= 0.4 else "🟡" if score >= 0.2 else "⚪"
    
    # ── 三级信号共振检测 ────────────────────────────────────
    triple_banner = ""
    if score >= 0.4 and sl_tp['rr'] >= 2.0 and vol is not None and vol >= 1.5:
        triple_banner = (
            "\n🔥🔥 **三级信号共振 — 适合上仓位！** 🔥🔥\n"
            "   🟢 综合评分≥0.4 | ⭐ 盈亏比≥2.0 | 📊 放量1.5x+\n\n"
        )
    
    return (
        f"{emoji} **{ticker}** - {company}\n"
        f"`${current_price:.2f}` {change_pct:+.2f}%\n"
        f"**评分: {score:+.2f}** → {signal}\n\n"
        f"{triple_banner}"
        f"🎯 **做T计划** 📈\n"
        f"   止损: **${sl_tp['sl']:.2f}** ({sl_tp['sl_pct']:+.2f}%)\n"
        f"   止盈: **${sl_tp['tp']:.2f}** ({sl_tp['tp_pct']:+.2f}%)\n"
        f"   盈亏比: {sl_tp['rr']}:1 {'⭐' if sl_tp['rr'] >= 2.0 else '👍' if sl_tp['rr'] >= 1.0 else '👌'}\n\n"
        f"📊 VWAP {vwap:.2f} | RSI {rsi} | 量 {vol}x"
    )


def detect_trend_fast(df):
    close = df['Close']
    ema5 = calc_ema(close, 5)
    ema20 = calc_ema(close, 20)
    above_5 = close.iloc[-1] > ema5
    above_20 = close.iloc[-1] > ema20
    bullish = sum([ema5 > ema20, above_5, above_20])
    return 'bullish' if bullish >= 2 else 'bearish' if bullish == 0 else 'neutral'


def calculate_score_fast(price, vwap, rsi, trend, vol_ratio, sr):
    score = 0.0
    if vwap and price > vwap: score += 0.25
    elif vwap: score -= 0.1
    if trend == 'bullish': score += 0.25
    elif trend == 'bearish': score -= 0.15
    if rsi < 35: score += 0.2
    elif rsi < 25: score += 0.12
    elif rsi > 75: score -= 0.2
    elif rsi > 65: score -= 0.05
    else: score += 0.1
    if vol_ratio and vol_ratio >= 1.0: score += 0.1
    if vol_ratio and vol_ratio < 0.7: score -= 0.1
    s1, r1 = sr.get('support1', 0), sr.get('resistance1', 0)
    if s1 and price > s1 and (price - s1) / price < 0.01: score += 0.15
    if r1 and r1 > price and (r1 - price) / price < 0.005: score -= 0.1
    return max(-1.0, min(1.0, round(score, 2)))


def calc_sl_tp_fast(price, vwap, sr, bb, ticker):
    from config import TICKER_PARAMS, DEFAULT_SL_PCT, DEFAULT_TP_PCT
    sl_pct = DEFAULT_SL_PCT
    tp_pct = DEFAULT_TP_PCT
    if ticker in TICKER_PARAMS:
        sl_pct = TICKER_PARAMS[ticker]['sl_pct']
        tp_pct = TICKER_PARAMS[ticker]['tp_pct']
    sl = round(price * (1 - sl_pct / 100), 2)
    tp = round(price * (1 + tp_pct / 100), 2)
    rr = round(tp_pct / sl_pct, 2) if sl_pct else 1
    return {'sl': sl, 'tp': tp, 'sl_pct': -sl_pct, 'tp_pct': tp_pct, 'rr': rr}


@app.route('/')
def index():
    return 'Trading T-Bot is running. Visit /setup to register webhook.', 200


@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram sends updates here. Process synchronously within timeout."""
    t_start = time.time()
    try:
        data = request.get_json(force=True)
        message = data.get('message', {})
        text = (message.get('text') or '').strip()
        chat_id = message.get('chat', {}).get('id')
        
        if not text or not chat_id:
            return 'ok', 200
        
        parts = text.split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []
        elapsed = time.time() - t_start
        
        # Handle commands
        if cmd in ('/start', '/help'):
            _send(chat_id, "🤖 **做T信号分析 Bot**\n\n`/t <代码>` — 分析\n`/watchlist` — 自选股\n`/spy` — 大盘\n\n例: `/t NVDA`")
        
        elif cmd == '/t' and args:
            _send(chat_id, f"🔍 正在分析 **{args[0].upper()}**...")
            try:
                reply = _analyze_fast(args[0])
                _send(chat_id, reply)
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                _send(chat_id, f"❌ 错误: {str(e)[:80]}\n`{tb[:200]}`")
                logger.error(f"/t error: {tb}")
        
        elif cmd == '/watchlist':
            _send(chat_id, "📋 正在扫描自选股...")
            lines = ["📋 **自选股做T信号扫描**\n"]
            for t in DEFAULT_WATCHLIST:
                r = _analyze_fast(t)
                lines.append(r.split('\n')[0])  # Just the title line
            _send(chat_id, "\n".join(lines))
        
        elif cmd == '/spy':
            _send(chat_id, "📊 正在获取大盘数据...")
            from indicators import get_market_sentiment, fetch_intraday_data
            s = get_market_sentiment()
            spy = fetch_intraday_data('SPY', interval='5m', period='2d')
            qqq = fetch_intraday_data('QQQ', interval='5m', period='2d')
            sp = spy['Close'].iloc[-1] if not spy.empty else 0
            qp = qqq['Close'].iloc[-1] if not qqq.empty else 0
            _send(chat_id, f"📊 **大盘情绪**\n{s.get('description','')}\n\nSPY ${sp:.2f} ({s.get('spy_change',0):+.2f}%)\nQQQ ${qp:.2f} ({s.get('qqq_change',0):+.2f}%)")
        
        else:
            _send(chat_id, "⚠️ 未知命令。发送 `/help` 查看可用命令。")
        
        logger.info(f"Webhook processed in {time.time()-t_start:.2f}s: {text}")
        return 'ok', 200
    
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        try:
            _send(chat_id, f"❌ 处理出错，请稍后重试。")
        except:
            pass
        return 'ok', 200


@app.route('/setup', methods=['GET'])
def setup_webhook():
    import requests
    bot_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    host = request.host_url.rstrip('/')
    r1 = requests.post(f"{bot_url}/setWebhook", json={"url": host + '/webhook', "drop_pending_updates": True})
    r2 = requests.post(f"{bot_url}/setMyCommands", json={"commands": [
        {"command": "t", "description": "Analyze a ticker (e.g. /t NVDA)"},
        {"command": "watchlist", "description": "Scan all watchlist stocks"},
        {"command": "spy", "description": "Market sentiment (SPY+QQQ)"},
        {"command": "help", "description": "Show help message"},
    ]})
    return jsonify({"webhook": r1.json(), "commands": r2.json()})


handler = app
