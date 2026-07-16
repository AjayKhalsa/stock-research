"""
db.py — SQLite persistence layer (stdlib sqlite3, no ORM dependency).

Replaces the ephemeral JSON files with durable storage for:
  - watchlist            user's tracked symbols
  - alerts               price-level alerts (armed from trade plans / custom)
  - settings             key/value app settings (values stored as JSON)
  - fundamentals_cache   per-symbol TTL cache of the merged fundamentals
                         payload (Screener.in + yfinance overlay)

Connections are short-lived per operation (safe under uvicorn's single
process; SQLite WAL mode keeps readers and the odd concurrent writer happy).
On first run, existing data/watchlist.json and data/alerts.json are migrated
in automatically; the JSON files are left in place as a backup.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Optional

from config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "stocklens.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol      TEXT PRIMARY KEY,
    exchange    TEXT NOT NULL DEFAULT 'NSE',
    name        TEXT,
    added_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id              TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    exchange        TEXT NOT NULL DEFAULT 'NSE',
    kind            TEXT NOT NULL,             -- entry | stop | target | custom
    label           TEXT,
    horizon         TEXT,                      -- swing | positional | NULL
    level           REAL NOT NULL,
    direction       TEXT NOT NULL,             -- above | below
    created_at      TEXT,
    status          TEXT NOT NULL DEFAULT 'active',   -- active | triggered
    triggered_at    TEXT,
    triggered_price REAL,
    acknowledged    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol, status);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT                                  -- JSON-encoded
);

CREATE TABLE IF NOT EXISTS fundamentals_cache (
    symbol     TEXT PRIMARY KEY,
    exchange   TEXT NOT NULL DEFAULT 'NSE',
    payload    TEXT NOT NULL,                   -- JSON: merged fundamentals dict
    origin     TEXT,                            -- 'yfinance+screener' | 'screener'
    fetched_at REAL NOT NULL                    -- unix epoch
);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    """Create schema (idempotent) and migrate legacy JSON files once."""
    with _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)
    _migrate_legacy_json()


# ── one-time migration from the old JSON files ────────────────────────────────

def _migrate_legacy_json() -> None:
    wl_json = os.path.join(DATA_DIR, "watchlist.json")
    al_json = os.path.join(DATA_DIR, "alerts.json")

    with _conn() as c:
        if c.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 0 \
                and os.path.exists(wl_json):
            try:
                items = json.load(open(wl_json))
                for w in items:
                    c.execute(
                        "INSERT OR IGNORE INTO watchlist(symbol, exchange, name, added_at) "
                        "VALUES (?,?,?,?)",
                        (w.get("symbol"), w.get("exchange", "NSE"),
                         w.get("name"), time.time()),
                    )
                print(f"[db] migrated {len(items)} watchlist items from JSON")
            except Exception as e:
                print(f"[db] watchlist migration failed: {e}")

        if c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0 \
                and os.path.exists(al_json):
            try:
                items = json.load(open(al_json))
                for a in items:
                    c.execute(
                        "INSERT OR IGNORE INTO alerts(id, symbol, exchange, kind, label, "
                        "horizon, level, direction, created_at, status, triggered_at, "
                        "triggered_price, acknowledged) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (a.get("id"), a.get("symbol"), a.get("exchange", "NSE"),
                         a.get("kind", "custom"), a.get("label"), a.get("horizon"),
                         a.get("level"), a.get("direction"), a.get("created_at"),
                         a.get("status", "active"), a.get("triggered_at"),
                         a.get("triggered_price"), 1 if a.get("acknowledged") else 0),
                    )
                print(f"[db] migrated {len(items)} alerts from JSON")
            except Exception as e:
                print(f"[db] alerts migration failed: {e}")


# ── watchlist ─────────────────────────────────────────────────────────────────

def watchlist_all() -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT symbol, exchange, name FROM watchlist ORDER BY added_at"
        ).fetchall()
    return [dict(r) for r in rows]


def watchlist_add(symbol: str, exchange: str = "NSE", name: str = "") -> list:
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO watchlist(symbol, exchange, name, added_at) "
            "VALUES (?,?,?,?)",
            (symbol.upper(), exchange, name or symbol.upper(), time.time()),
        )
    return watchlist_all()


def watchlist_remove(symbol: str) -> list:
    with _conn() as c:
        c.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),))
    return watchlist_all()


# ── alerts ────────────────────────────────────────────────────────────────────

_ALERT_COLS = ("id", "symbol", "exchange", "kind", "label", "horizon", "level",
               "direction", "created_at", "status", "triggered_at",
               "triggered_price", "acknowledged")


def _row_to_alert(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["acknowledged"] = bool(d.get("acknowledged"))
    return d


def alerts_all(symbol: Optional[str] = None) -> list:
    q = "SELECT * FROM alerts"
    args: tuple = ()
    if symbol:
        q += " WHERE symbol = ?"
        args = (symbol.upper(),)
    q += " ORDER BY created_at"
    with _conn() as c:
        return [_row_to_alert(r) for r in c.execute(q, args).fetchall()]


def alerts_insert(alert: dict) -> None:
    with _conn() as c:
        c.execute(
            f"INSERT INTO alerts({','.join(_ALERT_COLS)}) "
            f"VALUES ({','.join('?' * len(_ALERT_COLS))})",
            tuple(1 if (k == "acknowledged" and alert.get(k)) else
                  (0 if k == "acknowledged" else alert.get(k))
                  for k in _ALERT_COLS),
        )


def alerts_delete(alert_id: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    return cur.rowcount > 0


def alerts_delete_plan_set(symbol: str, horizon: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM alerts WHERE symbol = ? AND horizon = ?",
                  (symbol.upper(), horizon))


def alerts_acknowledge(alert_id: str) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
    return cur.rowcount > 0


def alerts_mark_triggered(alert_id: str, triggered_at: str, price: float) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE alerts SET status='triggered', triggered_at=?, triggered_price=? "
            "WHERE id = ? AND status = 'active'",
            (triggered_at, price, alert_id),
        )


# ── settings ──────────────────────────────────────────────────────────────────

def get_setting(key: str, default: Any = None) -> Any:
    with _conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if r is None:
        return default
    try:
        return json.loads(r["value"])
    except Exception:
        return default


def set_setting(key: str, value: Any) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


# ── fundamentals TTL cache ────────────────────────────────────────────────────

def cache_get(symbol: str) -> Optional[dict]:
    """Return {payload, origin, fetched_at, age_seconds} or None."""
    with _conn() as c:
        r = c.execute(
            "SELECT payload, origin, fetched_at FROM fundamentals_cache WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchone()
    if r is None:
        return None
    try:
        payload = json.loads(r["payload"])
    except Exception:
        return None
    return {
        "payload": payload,
        "origin": r["origin"],
        "fetched_at": r["fetched_at"],
        "age_seconds": max(0, time.time() - r["fetched_at"]),
    }


def cache_put(symbol: str, exchange: str, payload: dict, origin: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO fundamentals_cache(symbol, exchange, payload, origin, fetched_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload, "
            "origin=excluded.origin, fetched_at=excluded.fetched_at, "
            "exchange=excluded.exchange",
            (symbol.upper(), exchange, json.dumps(payload), origin, time.time()),
        )


# Schema is created on import so any entry point gets a working DB.
init()
