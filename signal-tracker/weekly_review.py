"""
Weekly review + strategy-health warnings for the 30-day signal tracker.
Runs every Friday after market close. Reports only — NEVER changes parameters.

Warnings (report-only, no auto-tuning):
  1. Losing streak >= 5  -> strategy-failure risk
  2. Weekly win rate < 35% (>= 5 signals that week)
  3. Risk/reward inverted: avg_loss > avg_win * 1.2
  4. SL hit rate > 60%   -> stops too tight
  5. No signals for 3+ consecutive trading days -> no market

Sends summary + alerts to Telegram if configured.

Usage: python weekly_review.py [--out reports/weekly_YYYYMMDD.md]
"""
import os, sys, argparse, json, logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
from tracker_config import REPORT_DIR

logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker.log"),
                    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

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

def week_key(d: str) -> str:
    """ISO week of a YYYY-MM-DD date string."""
    y, m, dd = map(int, d.split("-"))
    return datetime(y, m, dd).isocalendar()[:2]  # (year, week)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    db.init_db()
    rows = db.get_all_with_settlement()
    rows = [r for r in rows if r["exit_reason"] != "NO_DATA"]

    today = datetime.now(timezone.utc).astimezone().date()
    week_ago = today - timedelta(days=7)

    # ── This week's data ────────────────────────────────────
    week_rows = [r for r in rows if r["scan_date"] >= week_ago.isoformat()]
    w_wins = sum(1 for r in week_rows if r["pnl_pct"] > 0)
    w_losses = sum(1 for r in week_rows if r["pnl_pct"] < 0)
    w_flat = len(week_rows) - w_wins - w_losses
    w_total = sum(r["pnl_pct"] for r in week_rows)
    w_win_rate = w_wins / len(week_rows) if week_rows else 0
    w_avg_win = (sum(r["pnl_pct"] for r in week_rows if r["pnl_pct"] > 0) / w_wins) if w_wins else 0
    w_avg_loss = (sum(r["pnl_pct"] for r in week_rows if r["pnl_pct"] < 0) / w_losses) if w_losses else 0

    # ── All-time (cumulative) ───────────────────────────────
    t_wins = sum(1 for r in rows if r["pnl_pct"] > 0)
    t_losses = sum(1 for r in rows if r["pnl_pct"] < 0)
    t_flat = len(rows) - t_wins - t_losses
    t_win_rate = t_wins / len(rows) if rows else 0
    t_total = sum(r["pnl_pct"] for r in rows)
    t_avg_win = (sum(r["pnl_pct"] for r in rows if r["pnl_pct"] > 0) / t_wins) if t_wins else 0
    t_avg_loss = (sum(r["pnl_pct"] for r in rows if r["pnl_pct"] < 0) / t_losses) if t_losses else 0

    # ── Warning checks ──────────────────────────────────────
    warnings = []
    # 1. Losing streak >= 5
    cur_streak = max_streak = 0
    for r in sorted(rows, key=lambda x: x["id"]):
        if r["pnl_pct"] < 0:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0
    if max_streak >= 5:
        warnings.append(f"⚠️ 最大连亏 {max_streak} 笔 (>=5) — 策略失效风险")

    # 2. Weekly win rate < 35% (with enough signals)
    if len(week_rows) >= 5 and w_win_rate < 0.35:
        warnings.append(f"⚠️ 本周胜率 {w_win_rate*100:.0f}% (<35%)")

    # 3. Risk/reward inverted
    if t_wins >= 3 and t_losses >= 3 and abs(t_avg_loss) > abs(t_avg_win) * 1.2:
        warnings.append(f"⚠️ 盈亏比失衡: 平均亏 {abs(t_avg_loss):.2f}% > 平均盈 {abs(t_avg_win):.2f}% × 1.2")

    # 4. SL hit rate > 60%
    sl_count = sum(1 for r in rows if r["exit_reason"] == "SL")
    if rows and sl_count / len(rows) > 0.60:
        warnings.append(f"⚠️ 止损出场率 {sl_count/len(rows)*100:.0f}% (>60%) — 止损可能过紧")

    # 5. No signals for 3+ consecutive trading days
    dates = sorted({r["scan_date"] for r in rows})
    if dates:
        gap_days = 0
        prev = datetime.strptime(dates[-1], "%Y-%m-%d").date()
        cursor = today
        while cursor > prev:
            if cursor.weekday() < 5:
                gap_days += 1
            cursor -= timedelta(days=1)
        if gap_days >= 3:
            warnings.append(f"⚠️ 已连续 {gap_days} 个交易日无信号")

    # ── Build report ────────────────────────────────────────
    L = []
    L.append(f"# 📊 周复盘 — 信号追踪实验")
    L.append("")
    L.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L.append("")
    L.append("## 本周 (7天)")
    L.append("")
    L.append("| 指标 | 数值 |")
    L.append("|------|------|")
    L.append(f"| 信号数 | {len(week_rows)} |")
    L.append(f"| 胜/负/平 | {w_wins}/{w_losses}/{w_flat} |")
    L.append(f"| 胜率 | {w_win_rate*100:.1f}% |")
    L.append(f"| 累计盈亏 | {w_total:+.2f}% |")
    L.append("")
    L.append("## 累计 (实验至今)")
    L.append("")
    L.append("| 指标 | 数值 |")
    L.append("|------|------|")
    L.append(f"| 信号数 | {len(rows)} |")
    L.append(f"| 胜/负/平 | {t_wins}/{t_losses}/{t_flat} |")
    L.append(f"| 胜率 | {t_win_rate*100:.1f}% |")
    L.append(f"| 平均盈利 | {t_avg_win:+.2f}% |" if t_wins else "| 平均盈利 | - |")
    L.append(f"| 平均亏损 | {t_avg_loss:.2f}% |" if t_losses else "| 平均亏损 | - |")
    L.append(f"| 累计盈亏 | **{t_total:+.2f}%** |")
    L.append("")
    if warnings:
        L.append("## 🚨 预警")
        L.append("")
        for w in warnings:
            L.append(f"- {w}")
        L.append("")
        L.append("> 预警仅作观察，不自动调整参数。30天结束后统一用数据迭代。")
    else:
        L.append("## ✅ 健康状态")
        L.append("")
        L.append("- 无预警触发，策略运行正常。")
        L.append("")
    md = "\n".join(L)

    os.makedirs(REPORT_DIR, exist_ok=True)
    out = args.out or os.path.join(REPORT_DIR, f"weekly_{datetime.now().strftime('%Y%m%d')}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    logging.info(f"Weekly review written: {out}")
    print(md)

    # ── Telegram alert (only if warnings or weekly summary) ──
    tg_lines = ["📊 <b>信号追踪周复盘</b>",
                f"本周: {len(week_rows)}信号 · 胜率 {w_win_rate*100:.0f}% · {w_total:+.2f}%",
                f"累计: {len(rows)}信号 · 胜率 {t_win_rate*100:.0f}% · {t_total:+.2f}%"]
    if warnings:
        tg_lines.append("")
        tg_lines.append("🚨 <b>预警</b>")
        tg_lines.extend(warnings)
    ok = send_telegram("\n".join(tg_lines))
    logging.info(f"telegram sent: {ok}")

if __name__ == "__main__":
    main()
