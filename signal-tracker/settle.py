"""
Settlement: for each pending signal, replay the day's 5m bars AFTER the
signal timestamp in time order. First touch of SL/TP decides exit.
No look-ahead: bars before signal time are ignored.

Usage: python settle.py [--date YYYY-MM-DD]
"""
import sys, os, argparse, json, logging
from datetime import datetime, timezone, timedelta

TBT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TBT_DIR not in sys.path:
    sys.path.append(TBT_DIR)  # append so local config.py wins

from tracker_config import CONSERVATIVE_SAME_BAR
import db

logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker.log"),
                    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ET = timezone(timedelta(hours=-4))
UTC = timezone.utc


def fetch_5m(ticker: str, days: int = 5):
    """Fetch 5m bars via yfinance (import inside to keep startup fast)."""
    import yfinance as yf
    from indicators import get_session
    df = yf.Ticker(ticker, session=get_session()).history(period=f"{days}d", interval="5m")
    if df is None or df.empty:
        return None
    return df


def settle_signal(sig: dict, df) -> dict:
    """Simulate execution. Returns exit dict or None if no data."""
    ticker = sig["ticker"]
    scan_date = sig["scan_date"]
    slot = sig["scan_time_et"]  # "09:45" or "13:00" ET
    direction = sig["direction"]
    entry = sig["entry_price"]
    sl = sig["sl"]
    tp = sig["tp"]

    # Parse signal time as ET, convert to UTC
    sig_et = datetime.strptime(f"{scan_date} {slot}", "%Y-%m-%d %H:%M").replace(tzinfo=ET)
    sig_utc = sig_et.astimezone(UTC)

    # Filter bars: same day, strictly after signal time (no look-ahead)
    day = sig_et.date()
    bars = []
    for ts, row in df.iterrows():
        # ts is UTC-aware
        if ts.date() != day:
            continue
        if ts <= sig_utc:
            continue
        o, h, l, c = row["Open"], row["High"], row["Low"], row["Close"]
        if o is None or h is None or l is None or c is None:
            continue
        bars.append((ts, o, h, l, c))

    if not bars:
        return {"exit_reason": "NO_DATA", "exit_price": entry, "pnl_pct": 0.0}

    # Walk bars in time order
    last_close = entry
    for ts, o, h, l, c in bars:
        last_close = c
        if direction == "long":
            hit_sl = l <= sl
            hit_tp = h >= tp
            if hit_sl and hit_tp:
                if CONSERVATIVE_SAME_BAR:
                    return {"exit_reason": "SL", "exit_price": sl,
                            "pnl_pct": (sl - entry) / entry * 100}
                # optimistic: assume TP first
                return {"exit_reason": "TP", "exit_price": tp,
                        "pnl_pct": (tp - entry) / entry * 100}
            if hit_sl:
                return {"exit_reason": "SL", "exit_price": sl,
                        "pnl_pct": (sl - entry) / entry * 100}
            if hit_tp:
                return {"exit_reason": "TP", "exit_price": tp,
                        "pnl_pct": (tp - entry) / entry * 100}
        else:  # short
            hit_sl = h >= sl
            hit_tp = l <= tp
            if hit_sl and hit_tp:
                if CONSERVATIVE_SAME_BAR:
                    return {"exit_reason": "SL", "exit_price": sl,
                            "pnl_pct": (entry - sl) / entry * 100}
                return {"exit_reason": "TP", "exit_price": tp,
                        "pnl_pct": (entry - tp) / entry * 100}
            if hit_sl:
                return {"exit_reason": "SL", "exit_price": sl,
                        "pnl_pct": (entry - sl) / entry * 100}
            if hit_tp:
                return {"exit_reason": "TP", "exit_price": tp,
                        "pnl_pct": (entry - tp) / entry * 100}

    # EOD: exit at last close of the day
    return {"exit_reason": "EOD", "exit_price": last_close,
            "pnl_pct": ((last_close - entry) / entry * 100) if direction == "long"
                       else ((entry - last_close) / entry * 100)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    db.init_db()
    pending = db.get_pending_signals()
    if not pending:
        print(json.dumps({"settled": 0, "msg": "no pending signals"}))
        return

    # Group by ticker to fetch 5m data once per ticker
    from collections import defaultdict
    by_ticker = defaultdict(list)
    for sig in pending:
        by_ticker[sig["ticker"]].append(sig)

    results = []
    for ticker, sigs in by_ticker.items():
        try:
            df = fetch_5m(ticker)
        except Exception as e:
            logging.error(f"{ticker} fetch failed: {e}")
            for sig in sigs:
                db.insert_settlement(sig["id"], sig["entry_price"], "NO_DATA", 0.0)
                results.append({"ticker": ticker, "date": sig["scan_date"],
                                "reason": "NO_DATA", "pnl": 0.0})
            continue
        if df is None:
            for sig in sigs:
                db.insert_settlement(sig["id"], sig["entry_price"], "NO_DATA", 0.0)
                results.append({"ticker": ticker, "date": sig["scan_date"],
                                "reason": "NO_DATA", "pnl": 0.0})
            continue
        for sig in sigs:
            out = settle_signal(sig, df)
            db.insert_settlement(sig["id"], out["exit_price"], out["exit_reason"], out["pnl_pct"])
            results.append({"ticker": ticker, "date": sig["scan_date"], "slot": sig["scan_time_et"],
                            "dir": sig["direction"], "entry": sig["entry_price"],
                            "reason": out["exit_reason"], "exit": out["exit_price"],
                            "pnl_pct": round(out["pnl_pct"], 2)})
            logging.info(f"SETTLE {ticker} {sig['scan_date']} {sig['scan_time_et']} "
                         f"{sig['direction']} -> {out['exit_reason']} pnl={out['pnl_pct']:.2f}%")

    print(json.dumps({"settled": len(results), "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
