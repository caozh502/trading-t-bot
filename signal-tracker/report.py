"""
30-day experiment report generator.
Produces a markdown summary of win rate, PnL, streaks, per-stock breakdown.

Usage: python report.py [--days 30] [--out reports/summary_YYYYMMDD.md]
"""
import os, sys, argparse, json, logging
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
from tracker_config import REPORT_DIR, EXPERIMENT_DAYS

# Telegram (reuse trading-t-bot env)
TG_TOKEN = ""
TG_CHAT = ""
for env_path in ("~/trading-t-bot/.env", "~/portfolio-monitor/.env"):
    p = os.path.expanduser(env_path)
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line.startswith("TG_BOT_TOKEN="):
                TG_TOKEN = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("TG_CHAT_ID="):
                TG_CHAT = line.split("=", 1)[1].strip().strip('"').strip("'")

def send_telegram(text: str):
    if not TG_TOKEN or not TG_CHAT:
        return False
    try:
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML"},
            timeout=10)
        return r.status_code == 200
    except Exception as e:
        logging.warning(f"telegram send failed: {e}")
        return False

def send_telegram_document(path: str, caption: str = ""):
    if not TG_TOKEN or not TG_CHAT:
        return False
    try:
        import requests
        with open(path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendDocument",
                data={"chat_id": TG_CHAT, "caption": caption},
                files={"document": (os.path.basename(path), f)},
                timeout=15)
        return r.status_code == 200
    except Exception as e:
        logging.warning(f"telegram document send failed: {e}")
        return False


def generate_markdown(stats: dict, rows: list, days: int) -> str:
    L = []
    L.append(f"# 30日信号追踪实验总结报告")
    L.append("")
    L.append(f"**实验周期**: 最近 {days} 个交易日 · **生成时间**: {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')}")
    L.append("")
    L.append(f"> 股票池由AI选定(10只跨行业) · 每日2次扫描(09:45/13:00 ET) · 每扫描最多2信号 · "
             f"按当日5分钟K线时间顺序模拟执行 · 同根K线同时触SL/TP按保守(亏损)计")
    L.append("")

    # ── Headline stats ──
    L.append("## 总览")
    L.append("")
    L.append("| 指标 | 数值 |")
    L.append("|------|------|")
    L.append(f"| 信号总数 | {stats['total_signals']} |")
    L.append(f"| 已结算 | {stats['settled']} |")
    L.append(f"| 盈利笔数 | {stats['wins']} |")
    L.append(f"| 亏损笔数 | {stats['losses']} |")
    L.append(f"| 平局 | {stats['flat']} |")
    L.append(f"| **胜率** | **{stats['win_rate']*100:.1f}%** |")
    L.append(f"| 平均盈利 | +{stats['avg_win']:.2f}% |")
    L.append(f"| 平均亏损 | {stats['avg_loss']:.2f}% |")
    L.append(f"| 盈亏比 | {abs(stats['avg_win']/stats['avg_loss']):.2f} |" if stats['avg_loss'] else "| 盈亏比 | ∞ |")
    L.append(f"| 单笔平均 | {stats['avg_pnl']:+.2f}% |")
    L.append(f"| 累计收益(每笔等额) | **{stats['total_pnl_pct']:+.2f}%** |")
    L.append("")

    # ── By direction ──
    L.append("## 按方向")
    L.append("")
    for d in ("long", "short"):
        sub = [r for r in rows if r["direction"] == d]
        if not sub:
            continue
        w = sum(1 for r in sub if r["pnl_pct"] > 0)
        l_ = sum(1 for r in sub if r["pnl_pct"] < 0)
        tot = sum(r["pnl_pct"] for r in sub)
        L.append(f"- **{'做多' if d=='long' else '做空'}**: {len(sub)}笔 · 胜率 {w/len(sub)*100:.0f}% "
                 f"({w}胜/{l_}负) · 累计 {tot:+.2f}%")
    L.append("")

    # ── By ticker ──
    L.append("## 按股票")
    L.append("")
    L.append("| 股票 | 信号数 | 胜/负 | 胜率 | 累计% |")
    L.append("|------|-------|-------|------|-------|")
    by_t = {}
    for r in rows:
        by_t.setdefault(r["ticker"], []).append(r)
    for t, sub in sorted(by_t.items(), key=lambda x: -sum(r["pnl_pct"] for r in x[1])):
        w = sum(1 for r in sub if r["pnl_pct"] > 0)
        l_ = sum(1 for r in sub if r["pnl_pct"] < 0)
        tot = sum(r["pnl_pct"] for r in sub)
        L.append(f"| {t} | {len(sub)} | {w}/{l_} | {w/len(sub)*100:.0f}% | {tot:+.2f}% |")
    L.append("")

    # ── Exit reasons ──
    L.append("## 出场原因")
    L.append("")
    reasons = {}
    for r in rows:
        reasons[r["exit_reason"]] = reasons.get(r["exit_reason"], 0) + 1
    for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
        pct = v / len(rows) * 100 if rows else 0
        label = {"SL": "止损", "TP": "止盈", "EOD": "收盘平仓", "NO_DATA": "无数据"}.get(k, k)
        L.append(f"- **{label}**: {v}笔 ({pct:.0f}%)")
    L.append("")

    # ── Max losing streak ──
    cur_streak = max_streak = 0
    for r in sorted(rows, key=lambda x: x["id"]):
        if r["pnl_pct"] < 0:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0
    L.append(f"- **最大连亏**: {max_streak}笔")
    L.append("")

    # ── Daily pnl curve ──
    L.append("## 每日累计收益")
    L.append("")
    L.append("```")
    L.append("日期        信号  当日%   累计%")
    daily = {}
    for r in rows:
        daily.setdefault(r["scan_date"], []).append(r)
    cum = 0.0
    for d in sorted(daily.keys()):
        sub = daily[d]
        day_pnl = sum(r["pnl_pct"] for r in sub)
        cum += day_pnl
        L.append(f"{d}  {len(sub):>3}  {day_pnl:+7.2f}  {cum:+8.2f}")
    L.append("```")
    L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=EXPERIMENT_DAYS)
    ap.add_argument("--out", default=None)
    ap.add_argument("--notify", action="store_true",
                    help="push report summary + file to Telegram after writing")
    args = ap.parse_args()

    db.init_db()
    rows = db.get_all_with_settlement()
    # Only include settled rows that were actually simulated
    rows = [r for r in rows if r["exit_reason"] != "NO_DATA"]
    stats = db.stats_summary()
    # Recompute stats excluding NO_DATA (db.stats_summary already excludes them)
    stats["total_signals"] = len(rows)

    os.makedirs(REPORT_DIR, exist_ok=True)
    out = args.out or os.path.join(REPORT_DIR, f"summary_{datetime.now().strftime('%Y%m%d_%H%M')}.md")
    md = generate_markdown(stats, rows, args.days)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"Report written: {out}")
    print(md)

    if args.notify:
        final = "📊 <b>30天实验总结报告已生成</b>" if "summary_final" in out else "📊 <b>信号追踪日报</b>"
        lines = [
            final,
            f"信号: {stats['total_signals']}笔 · 胜率: {stats['win_rate']*100:.1f}%",
            f"平均盈利: +{stats['avg_win']:.2f}% · 平均亏损: {stats['avg_loss']:.2f}%",
            f"累计收益(等额): <b>{stats['total_pnl_pct']:+.2f}%</b>",
            f"报告: {out}",
        ]
        ok_msg = send_telegram("\n".join(lines))
        ok_doc = send_telegram_document(out, caption="📄 完整报告")
        logging.info(f"telegram notify: msg={ok_msg} doc={ok_doc}")
        print(f"[notify] telegram msg={ok_msg} doc={ok_doc}")


if __name__ == "__main__":
    main()
