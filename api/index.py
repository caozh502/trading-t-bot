"""
Vercel Serverless — Telegram Bot Webhook
Telegram → POST /api/webhook → analyze → reply
"""
import sys, os, json, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask, request, jsonify
from analyzer import analyze_ticker, analyze_multiple, format_result
from config import TELEGRAM_BOT_TOKEN, DEFAULT_WATCHLIST

app = Flask(__name__)
logger = logging.getLogger(__name__)


@app.route('/api/webhook', methods=['POST'])
def webhook():
    """Telegram sends updates here."""
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
        
        # Process command
        reply = handle_command(cmd, args)
        
        # Send reply
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": reply,
            "parse_mode": "Markdown"
        })
        
        return 'ok', 200
    
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'ok', 200


@app.route('/api/setup', methods=['GET'])
def setup_webhook():
    """One-time: register this URL as the bot's webhook."""
    url = request.host_url.rstrip('/') + '/api/webhook'
    import requests
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
        json={"url": url, "drop_pending_updates": True}
    )
    return jsonify(resp.json())


def handle_command(cmd: str, args: list) -> str:
    """Process a command and return reply text."""
    if cmd in ('/start', '/help'):
        return (
            "🤖 **做T信号分析 Bot**\n\n"
            "`/t <代码>` — 分析单只股票\n"
            "`/watchlist` — 扫描自选股\n"
            "`/spy` — 大盘情绪\n\n"
            "例: `/t NVDA`"
        )
    
    if cmd == '/t' and args:
        result = analyze_ticker(args[0].upper())
        return format_result(result, verbose=True)
    
    if cmd == '/watchlist':
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
        return "\n".join(lines)
    
    if cmd == '/spy':
        from indicators import get_market_sentiment, fetch_intraday_data
        s = get_market_sentiment()
        spy = fetch_intraday_data('SPY', interval='5m', period='2d')
        qqq = fetch_intraday_data('QQQ', interval='5m', period='2d')
        sp = spy['Close'].iloc[-1] if not spy.empty else 0
        qp = qqq['Close'].iloc[-1] if not qqq.empty else 0
        return (
            f"📊 **大盘情绪**\n{s.get('description','')}\n\n"
            f"SPY ${sp:.2f} ({s.get('spy_change',0):+.2f}%)\n"
            f"QQQ ${qp:.2f} ({s.get('qqq_change',0):+.2f}%)"
        )
    
    return "⚠️ 未知命令。发送 `/help` 查看可用命令。"


# Vercel entry point
handler = app
