"""
SQLite storage for signal-tracker.
Schema:
  signals(id, scan_date, scan_time_et, ticker, sector, direction, score,
          entry_price, sl, tp, signal_text, created_at)
  settlements(id, signal_id, exit_price, exit_reason, pnl_pct, settled_at)
"""
import sqlite3
from datetime import datetime, timezone

from tracker_config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_date TEXT NOT NULL,
        scan_time_et TEXT NOT NULL,
        ticker TEXT NOT NULL,
        sector TEXT,
        direction TEXT NOT NULL,          -- long | short
        score REAL NOT NULL,
        entry_price REAL NOT NULL,
        sl REAL NOT NULL,
        tp REAL NOT NULL,
        signal_text TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(scan_date, scan_time_et, ticker)
    );
    CREATE TABLE IF NOT EXISTS settlements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id INTEGER NOT NULL,
        exit_price REAL NOT NULL,
        exit_reason TEXT NOT NULL,        -- SL | TP | EOD | NO_DATA | SKIPPED
        pnl_pct REAL NOT NULL,
        settled_at TEXT NOT NULL,
        UNIQUE(signal_id)
    );
    """)
    conn.commit()
    conn.close()


def insert_signal(sig: dict) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT OR REPLACE INTO signals
               (scan_date, scan_time_et, ticker, sector, direction, score,
                entry_price, sl, tp, signal_text, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (sig["scan_date"], sig["scan_time_et"], sig["ticker"], sig.get("sector"),
             sig["direction"], sig["score"], sig["entry_price"], sig["sl"],
             sig["tp"], sig.get("signal_text", ""),
             datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_pending_signals() -> list:
    """Signals that have no settlement yet."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT s.* FROM signals s
           LEFT JOIN settlements st ON st.signal_id = s.id
           WHERE st.id IS NULL
           ORDER BY s.id""").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_signals_for_date(scan_date: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM signals WHERE scan_date = ? ORDER BY id", (scan_date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_settlement(sig_id: int, exit_price: float, reason: str, pnl_pct: float):
    conn = get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO settlements
           (signal_id, exit_price, exit_reason, pnl_pct, settled_at)
           VALUES (?,?,?,?,?)""",
        (sig_id, exit_price, reason, pnl_pct,
         datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def get_all_with_settlement() -> list:
    conn = get_conn()
    rows = conn.execute(
        """SELECT s.*, st.exit_price, st.exit_reason, st.pnl_pct
           FROM signals s JOIN settlements st ON st.signal_id = s.id
           ORDER BY s.id""").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def stats_summary() -> dict:
    rows = get_all_with_settlement()
    settled = [r for r in rows if r["exit_reason"] not in ("NO_DATA", "SKIPPED")]
    wins = [r for r in settled if r["pnl_pct"] > 0]
    losses = [r for r in settled if r["pnl_pct"] < 0]
    flat = [r for r in settled if r["pnl_pct"] == 0]
    return {
        "total_signals": len(rows),
        "settled": len(settled),
        "wins": len(wins), "losses": len(losses), "flat": len(flat),
        "win_rate": len(wins) / len(settled) if settled else 0,
        "avg_win": (sum(r["pnl_pct"] for r in wins) / len(wins)) if wins else 0,
        "avg_loss": (sum(r["pnl_pct"] for r in losses) / len(losses)) if losses else 0,
        "total_pnl_pct": sum(r["pnl_pct"] for r in settled),
        "avg_pnl": (sum(r["pnl_pct"] for r in settled) / len(settled)) if settled else 0,
    }
