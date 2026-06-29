"""
Vercel Serverless — Telegram Bot Webhook
Responds instantly to Telegram, processes analysis in background thread.
"""
import sys, os, json, logging, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask, request, jsonify
from analyzer import analyze_ticker, analyze_multiple, format_result
from config import TELEGRAM_BOT_TOKEN, DEFAULT_WATCHLIST

app = Flask(__name__)
logger = logging.getLogger(__name__)


@app.route('/')
def index():
    return 'Trading T-Bot is running. Visit /setup to register webhook.', 200


def _send_reply(chat_id: int, text: str):
    """Send a Telegram message (called from background thread)."""
    import requests
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=15)
    except Exception as e:
        logger.error(f"send_reply error: {e}")


def _process_command_async(chat_id: int, cmd: str, args: list):
    """Process command in background thread and send result."""
    try:
        if cmd in ('/start', '/help'):
            reply = (
                "🤖 **做T信号分析 Bot**\n\n"
                "`/t <代码>` — 分析单只股票\n"
                "`/watchlist` — 扫描自选股\n"
                "`/spy` — 大盘情绪\n\n"
                "例: `/t NVDA`"
            )
        
        elif cmd == '/t' and args:
            ticker = args[0].upper()
            _send_reply(chat_id, f"🔍 正在分析 **{ticker}**...")
            result = analyze_ticker(ticker)
            reply = format_result(result, verbose=True)
        
        elif cmd == '/watchlist':
            _send_reply(chat_id, "📋 正在扫描自选股...")
            results = analyze_multiple(DEFAULT_WATCHLIST)
            lines = ["📋 **自选股做T信号扫描**\n"]
            buy = watch = avoid = 0
            for r in results:
                s = f"{r.total_score:+.2f}"
                lines.append(f"{r.signal_color} {r.ticker:6s} | 评分{s} | {r.signal}")
                if "入场" in r.signal: buy += 1
                elif "观望" in r.signal or "谨慎" in r.signal: watch += 1
                else: avoid += 1
            lines.append(f"\n✅ {buy} | ⚪ {watch} | ❌ {avoid}")
            reply = "\n".join(lines)
        
        elif cmd == '/spy':
            _send_reply(chat_id, "📊 正在获取大盘数据...")
            from indicators import get_market_sentiment, fetch_intraday_data
            s = get_market_sentiment()
            spy = fetch_intraday_data('SPY', interval='5m', period='2d')
            qqq = fetch_intraday_data('QQQ', interval='5m', period='2d')
            sp = spy['Close'].iloc[-1] if not spy.empty else 0
            qp = qqq['Close'].iloc[-1] if not qqq.empty else 0
            reply = (
                f"📊 **大盘情绪**\n{s.get('description','')}\n\n"
                f"SPY ${sp:.2f} ({s.get('spy_change',0):+.2f}%)\n"
                f"QQQ ${qp:.2f} ({s.get('qqq_change',0):+.2f}%)"
            )
        
        else:
            reply = "⚠️ 未知命令。发送 `/help` 查看可用命令。"
        
        _send_reply(chat_id, reply)
    
    except Exception as e:
        logger.error(f"Async processing error: {e}")
        _send_reply(chat_id, f"❌ 处理出错，请稍后重试。\n`{str(e)[:100]}`")


@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram sends updates here. Respond instantly, process async."""
    try:
        data = request.get_json(force=True)
        message = data.get('message', {})
        text = (message.get('text') or '').strip()
        chat_id = message.get('chat', {}).get('id')
        
        if text and chat_id:
            parts = text.split()
            cmd = parts[0].lower()
            args = parts[1:] if len(parts) > 1 else []
            
            # Launch background thread for processing
            t = threading.Thread(
                target=_process_command_async,
                args=(chat_id, cmd, args)
            )
            t.start()
        
        return 'ok', 200  # Respond immediately to Telegram
    
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'ok', 200


@app.route('/setup', methods=['GET'])
def setup_webhook():
    """One-time: register webhook URL + bot commands."""
    import requests
    bot_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    host = request.host_url.rstrip('/')
    
    webhook_url = host + '/webhook'
    r1 = requests.post(f"{bot_url}/setWebhook", json={
        "url": webhook_url, "drop_pending_updates": True
    })
    
    r2 = requests.post(f"{bot_url}/setMyCommands", json={
        "commands": [
            {"command": "t", "description": "Analyze a ticker (e.g. /t NVDA)"},
            {"command": "watchlist", "description": "Scan all watchlist stocks"},
            {"command": "spy", "description": "Market sentiment (SPY+QQQ)"},
            {"command": "help", "description": "Show help message"},
        ]
    })
    
    return jsonify({
        "webhook": r1.json(),
        "commands": r2.json(),
        "webhook_url": webhook_url,
    })


# Vercel entry point
handler = app
