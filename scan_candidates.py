"""Scan candidates for intraday trading signals."""
import sys
sys.path.insert(0, r'E:\Caleb_Space\Code\Project_t\trading-t-bot')
from analyzer import analyze_ticker

CANDIDATES = [
    "NVDA", "TSLA", "AMD", "META", "AAPL", "AMZN", "GOOGL", "MSFT",
    "PLTR", "SOFI", "MSTR", "COIN", "HOOD", "RDDT", "SMCI", "ARM",
    "AVGO", "MU", "MRVL", "INTC",
    "QQQ", "SPY", "IWM", "TQQQ", "SOXL",
]

results = []
for t in CANDIDATES:
    r = analyze_ticker(t)
    score = r.total_score if not r.error else -99
    name = (r.company_name or "?")[:24]
    signal = r.signal if not r.error else "⚠️ ERROR"
    price = f"${r.current_price:.2f}" if r.current_price else "-"
    vol_text = ""
    for f in r.factors:
        if f.name == "成交量确认":
            vol_text = f.detail[:30]
            break
    results.append((score, t, signal, price, name, vol_text))

# Sort: good entry candidates first (score >= 0.2), then watch, then avoid
def sort_key(item):
    s = item[0]
    if "适合" in item[2]: return (0, -s)
    if "谨慎" in item[2]: return (1, -s)
    if "观望" in item[2]: return (2, -s)
    if "ERROR" in item[2]: return (5, 0)
    return (3, -s)

results.sort(key=sort_key)

print(f"\n{'代码':6s} | {'评分':6s} | {'信号':16s} | {'价格':10s} | {'成交量':20s} | 名称")
print("=" * 80)
for score, t, sig, price, name, vol in results:
    s = f"{score:+.2f}" if score != -99 else " ERR"
    print(f"{t:6s} | {s:6s} | {sig:16s} | {price:10s} | {vol:20s} | {name}")

print(f"\n总计扫描 {len(CANDIDATES)} 只标的")
