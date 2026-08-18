"""
Daily scan: score pool via trading-t-bot analyzer, pick strongest signals,
store to SQLite. Run via cron at US 09:45 and 13:00 ET (= 15:45 / 19:00 CEST).

Usage: python record.py [--date YYYY-MM-DD] [--force]
"""
import sys, os, argparse, json
from datetime import datetime, timezone, timedelta

# Reuse the battle-tested analyzer from trading-t-bot
TBT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TBT_DIR not in sys.path:
    sys.path.append(TBT_DIR)  # append so local config.py wins

from tracker_config import (STOCK_POOL, SECTOR, SCAN_TIMES_ET, MAX_SIGNALS_PER_SCAN,
                            MAX_SIGNALS_PER_TICKER_PER_DAY, MAX_SAME_SECTOR_PER_SCAN,
                            MIN_SCORE_ABS, SHORT_MIN_SCORE, MIN_SL_PCT)
import db
import logging

logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker.log"),
                    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ET = timezone(timedelta(hours=-4))  # EDT (summer)


def now_et() -> datetime:
    return datetime.now(timezone.utc).astimezone(ET)


def parse_sl_tp(analyzer_result):
    """Extract SL/TP/direction from AnalysisResult.sl_tp dict."""
    sl_tp = getattr(analyzer_result, "sl_tp", None)
    if not sl_tp:
        return None, None, None
    return (sl_tp.get("sl_price"), sl_tp.get("tp_price"), sl_tp.get("direction"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    db.init_db()
    now = now_et()
    scan_date = args.date or now.strftime("%Y-%m-%d")

    # Which scan slot are we in? Determine from current ET time.
    cur_hm = now.strftime("%H:%M")
    # Map to nearest slot: if before 11:30 ET -> slot 09:45, else slot 13:00
    scan_time_et = "09:45" if now.hour < 12 else "13:00"
    if args.force and args.date:
        scan_time_et = "13:00"  # manual backfill -> treat as second slot

    logging.info(f"Scan start date={scan_date} slot={scan_time_et} cur_et={cur_hm}")

    # Existing signals today per ticker (for dedup)
    existing = db.get_signals_for_date(scan_date)
    existing_tickers = {r["ticker"] for r in existing}

    from analyzer import analyze_ticker  # import after path setup

    candidates = []
    for t in STOCK_POOL:
        if t in existing_tickers and not args.force:
            logging.info(f"skip {t}: already signaled today")
            continue
        try:
            r = analyze_ticker(t)
        except Exception as e:
            logging.warning(f"{t} analyze error: {e}")
            continue
        if getattr(r, "error", None):
            logging.warning(f"{t} error result: {r.error}")
            continue
        price = getattr(r, "current_price", None)
        score = getattr(r, "total_score", None)
        if not price or score is None:
            logging.warning(f"{t} no price/score (price={price}, score={score})")
            continue
        candidates.append({"ticker": t, "score": score, "price": price, "result": r})
        logging.info(f"{t}: score={score:.3f} price={price:.2f}")

    if not candidates:
        logging.info("no candidates scored")
        print(json.dumps({"date": scan_date, "slot": scan_time_et, "signals": []}))
        return

    # Direction decision: long if score >= MIN_SCORE_ABS; short if direction short >= SHORT_MIN_SCORE
    chosen = []
    sector_counts = {}
    for c in sorted(candidates, key=lambda x: -abs(x["score"])):
        t = c["ticker"]
        r = c["result"]
        sl, tp, sl_tp_dir = parse_sl_tp(r)

        # Direction decision: analyzer's sl_tp already picks long/short by score.
        # Override to short only when direction analysis strongly favors short.
        direction = sl_tp_dir if sl_tp_dir in ("long", "short") else None
        if direction is None:
            continue
        if direction == "long" and c["score"] < MIN_SCORE_ABS:
            continue
        if direction == "short":
            short_s = getattr(r, "short_score", 0) or 0
            if short_s < SHORT_MIN_SCORE or c["score"] > -0.15:
                continue

        if sl is None or tp is None or sl <= 0 or tp <= 0:
            logging.warning(f"{t}: no usable SL/TP (sl={sl}, tp={tp}) — skipping")
            continue
        sl_pct = abs(c["price"] - sl) / c["price"] * 100
        if sl_pct < MIN_SL_PCT:
            logging.warning(f"{t}: SL too tight {sl_pct:.2f}% < {MIN_SL_PCT}% — skipping")
            continue
        # Sector dedup
        sec = SECTOR.get(t, "other")
        if sector_counts.get(sec, 0) >= MAX_SAME_SECTOR_PER_SCAN:
            logging.info(f"{t}: sector {sec} already picked this scan — skip")
            continue
        chosen.append({
            "scan_date": scan_date,
            "scan_time_et": scan_time_et,
            "ticker": t,
            "sector": sec,
            "direction": direction,
            "score": c["score"],
            "entry_price": c["price"],
            "sl": sl,
            "tp": tp,
            "signal_text": f"score={c['score']:.2f} dir={direction}",
        })
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
        if len(chosen) >= MAX_SIGNALS_PER_SCAN:
            break

    for sig in chosen:
        db.insert_signal(sig)
        logging.info(f"SIGNAL {sig['scan_date']} {sig['scan_time_et']} {sig['ticker']} "
                     f"{sig['direction']} @{sig['entry_price']:.2f} SL={sig['sl']:.2f} TP={sig['tp']:.2f}")

    print(json.dumps({"date": scan_date, "slot": scan_time_et,
                      "signals": [{k: v for k, v in s.items() if k != "signal_text"} for s in chosen]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
