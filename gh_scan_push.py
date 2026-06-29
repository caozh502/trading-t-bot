"""GitHub Actions 定时推送：扫自选股并推送到 Telegram。
用法: python gh_scan_push.py
环境变量: TG_BOT_TOKEN, TG_CHAT_ID
"""
import os, sys, requests
sys.path.insert(0, os.path.dirname(__file__))
from analyzer import analyze_ticker
from config import DEFAULT_WATCHLIST

results = []
for t in DEFAULT_WATCHLIST:
    r = analyze_ticker(t)
    sl = r.sl_tp
    emoji = r.signal_color
    score = f"{r.total_score:+.2f}"
    signal = r.signal
    sl_price = sl['sl_price']
    sl_pct = f"{sl['sl_pct']:+.2f}%"
    tp_price = sl['tp_price']
    tp_pct = f"{sl['tp_pct']:+.2f}%"
    line = f"{emoji} {t:5s} | 评分{score} | {signal:12s} | SL ${sl_price}({sl_pct}) | TP ${tp_price}({tp_pct})"
    results.append(line)

now = __import__('datetime').datetime.now()
msg = (
    f"📋 **做T信号扫描** ({now.strftime('%m/%d %H:%M')})\n\n"
    + "\n".join(results)
    + "\n\n💡 *本推送由 GitHub Actions 自动发送*\n"
    + "📌 实时对话请在本地 Bot 中使用 /t 命令"
)

token = os.environ['TG_BOT_TOKEN']
chat_id = os.environ['TG_CHAT_ID']
url = f"https://api.telegram.org/bot{token}/sendMessage"
data = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
resp = requests.post(url, data=data).json()
print(resp.get("description", resp.get("ok", "sent")))
