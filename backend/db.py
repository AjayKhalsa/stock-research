"""
db.py — persistence layer with a swappable backend.

Durable storage for:
  - watchlist            user's tracked symbols
  - alerts               price-level alerts (armed from trade plans / custom)
  - settings             key/value app settings (values stored as JSON)
  - fundamentals_cache   per-symbol TTL cache of the merged fundamentals payload
  - saved_screens        named, re-loadable screener universes

Two backends, chosen at import time:
  - Postgres  when DATABASE_URL is set (e.g. Render's managed Postgres). This
              is what makes the data survive restarts on hosts with an
              ephemeral disk — the watchlist and saved screens live in the
              external database, not on the container filesystem.
  - SQLite    otherwise (local dev): a file at DATA_DIR/stocklens.db, no
              services to run.

The public functions below are backend-agnostic; callers never care which is
active. SQL is written with `?` placeholders and translated to `%s` for
Postgres; the handful of dialect differences (schema types, autoincrement) are
isolated in the two schema strings and `_conn`.

Connections are short-lived per operation. On the SQLite path, existing
data/watchlist.json and data/alerts.json are migrated in on first run.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from config import DATA_DIR

# ── backend selection ─────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_PG = _DATABASE_URL.startswith(("postgres://", "postgresql://"))

DB_PATH = os.path.join(DATA_DIR, "stocklens.db")   # SQLite fallback path

if _PG:
    import psycopg
    from psycopg.rows import dict_row
    # libpq accepts both schemes, but normalize the legacy one for clarity.
    _DSN = _DATABASE_URL.replace("postgres://", "postgresql://", 1)


def _sql(q: str) -> str:
    """Translate `?` placeholders to `%s` for Postgres; no-op for SQLite.
    Safe because none of the queries below contain a literal `?`."""
    return q.replace("?", "%s") if _PG else q


@contextmanager
def _conn() -> Iterator[Any]:
    """A fresh connection with dict-style row access on both backends.

    Used as `with _conn() as c: ...`; transactions commit on a clean exit and
    every connection is explicitly closed on both backends.
    """
    if _PG:
        with psycopg.connect(_DSN, row_factory=dict_row) as c:
            yield c
        return
    c = sqlite3.connect(DB_PATH, timeout=5)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


# ── schema ────────────────────────────────────────────────────────────────────

_SCHEMA_SQLITE = """
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
    kind            TEXT NOT NULL,
    label           TEXT,
    horizon         TEXT,
    level           REAL NOT NULL,
    direction       TEXT NOT NULL,
    created_at      TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    triggered_at    TEXT,
    triggered_price REAL,
    acknowledged    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol, status);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS fundamentals_cache (
    symbol     TEXT PRIMARY KEY,
    exchange   TEXT NOT NULL DEFAULT 'NSE',
    payload    TEXT NOT NULL,
    origin     TEXT,
    fetched_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_screens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    tickers      TEXT NOT NULL,
    ranked_data  TEXT,
    computed_at  REAL,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

-- Forward-tested ("paper") trades logged from a Trade Plan's Position Sizer.
-- status: ACTIVE | WIN_T1 | WIN_T2 | STOPPED_OUT, advanced by /api/paper-trades/evaluate.
CREATE TABLE IF NOT EXISTS paper_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      VARCHAR(20) NOT NULL,
    entry_date  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    entry_price NUMERIC(10, 2) NOT NULL,
    stop_loss   NUMERIC(10, 2) NOT NULL,
    target_t1   NUMERIC(10, 2) NOT NULL,
    target_t2   NUMERIC(10, 2) NOT NULL,
    score       NUMERIC(6, 2),
    setup_type  TEXT,
    status      VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    pnl_r       NUMERIC(5, 2) NOT NULL DEFAULT 0.0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);
"""

# Postgres variant: BIGSERIAL for autoincrement, DOUBLE PRECISION for the epoch
# timestamps (PG REAL is a lossy 4-byte float). Column names/semantics match.
_SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol      TEXT PRIMARY KEY,
    exchange    TEXT NOT NULL DEFAULT 'NSE',
    name        TEXT,
    added_at    DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id              TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    exchange        TEXT NOT NULL DEFAULT 'NSE',
    kind            TEXT NOT NULL,
    label           TEXT,
    horizon         TEXT,
    level           DOUBLE PRECISION NOT NULL,
    direction       TEXT NOT NULL,
    created_at      TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    triggered_at    TEXT,
    triggered_price DOUBLE PRECISION,
    acknowledged    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol, status);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS fundamentals_cache (
    symbol     TEXT PRIMARY KEY,
    exchange   TEXT NOT NULL DEFAULT 'NSE',
    payload    TEXT NOT NULL,
    origin     TEXT,
    fetched_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_screens (
    id           BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    tickers      TEXT NOT NULL,
    ranked_data  TEXT,
    computed_at  DOUBLE PRECISION,
    created_at   DOUBLE PRECISION NOT NULL,
    updated_at   DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id          SERIAL PRIMARY KEY,
    symbol      VARCHAR(20) NOT NULL,
    entry_date  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    entry_price NUMERIC(10, 2) NOT NULL,
    stop_loss   NUMERIC(10, 2) NOT NULL,
    target_t1   NUMERIC(10, 2) NOT NULL,
    target_t2   NUMERIC(10, 2) NOT NULL,
    score       NUMERIC(6, 2),
    setup_type  TEXT,
    status      VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    pnl_r       NUMERIC(5, 2) NOT NULL DEFAULT 0.0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);
"""


def _migrate_saved_screens_columns() -> None:
    """Additive migration for saved_screens.ranked_data/computed_at, added
    after this table already existed in deployed databases — CREATE TABLE
    IF NOT EXISTS alone never touches an existing table's columns. Safe to
    run on every startup: each ADD COLUMN is skipped once already present,
    on both backends, and nothing here can drop or alter existing rows."""
    if _PG:
        with _conn() as c:
            with c.cursor() as cur:
                cur.execute("ALTER TABLE saved_screens ADD COLUMN IF NOT EXISTS ranked_data TEXT")
                cur.execute("ALTER TABLE saved_screens ADD COLUMN IF NOT EXISTS computed_at DOUBLE PRECISION")
        return
    with _conn() as c:
        existing = {row[1] for row in c.execute("PRAGMA table_info(saved_screens)").fetchall()}
        if "ranked_data" not in existing:
            c.execute("ALTER TABLE saved_screens ADD COLUMN ranked_data TEXT")
        if "computed_at" not in existing:
            c.execute("ALTER TABLE saved_screens ADD COLUMN computed_at REAL")


def init() -> None:
    """Create schema (idempotent). SQLite path also migrates legacy JSON once."""
    if _PG:
        print("[db] Using Postgres — persistent across restarts.")
        with _conn() as c:
            with c.cursor() as cur:
                for stmt in _SCHEMA_PG.split(";"):
                    if stmt.strip():
                        cur.execute(stmt)
        _migrate_saved_screens_columns()
        return
    print(f"[db] Using local SQLite at {DB_PATH} — EPHEMERAL on most hosts "
          f"(e.g. Render's free plan wipes this on every restart/redeploy). "
          f"Set DATABASE_URL to a Postgres connection string to persist data "
          f"across restarts.")
    with _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA_SQLITE)
    _migrate_saved_screens_columns()
    _migrate_legacy_json()


# ── one-time migration from the old JSON files (SQLite path only) ─────────────

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
        rows = c.execute(_sql(
            "SELECT symbol, exchange, name FROM watchlist ORDER BY added_at"
        )).fetchall()
    return [dict(r) for r in rows]


def watchlist_add(symbol: str, exchange: str = "NSE", name: str = "") -> list:
    with _conn() as c:
        c.execute(_sql(
            "INSERT INTO watchlist(symbol, exchange, name, added_at) "
            "VALUES (?,?,?,?) ON CONFLICT DO NOTHING"),
            (symbol.upper(), exchange, name or symbol.upper(), time.time()),
        )
    return watchlist_all()


def watchlist_remove(symbol: str) -> list:
    with _conn() as c:
        c.execute(_sql("DELETE FROM watchlist WHERE symbol = ?"), (symbol.upper(),))
    return watchlist_all()


# ── alerts ────────────────────────────────────────────────────────────────────

_ALERT_COLS = ("id", "symbol", "exchange", "kind", "label", "horizon", "level",
               "direction", "created_at", "status", "triggered_at",
               "triggered_price", "acknowledged")


def _row_to_alert(r) -> dict:
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
        return [_row_to_alert(r) for r in c.execute(_sql(q), args).fetchall()]


def alerts_insert(alert: dict) -> None:
    with _conn() as c:
        c.execute(
            _sql(f"INSERT INTO alerts({','.join(_ALERT_COLS)}) "
                 f"VALUES ({','.join('?' * len(_ALERT_COLS))})"),
            tuple(1 if (k == "acknowledged" and alert.get(k)) else
                  (0 if k == "acknowledged" else alert.get(k))
                  for k in _ALERT_COLS),
        )


def alerts_delete(alert_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(_sql("DELETE FROM alerts WHERE id = ?"), (alert_id,))
        return cur.rowcount > 0


def alerts_delete_plan_set(symbol: str, horizon: str) -> None:
    with _conn() as c:
        c.execute(_sql("DELETE FROM alerts WHERE symbol = ? AND horizon = ?"),
                  (symbol.upper(), horizon))


def alerts_acknowledge(alert_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(_sql("UPDATE alerts SET acknowledged = 1 WHERE id = ?"), (alert_id,))
        return cur.rowcount > 0


def alerts_mark_triggered(alert_id: str, triggered_at: str, price: float) -> None:
    with _conn() as c:
        c.execute(
            _sql("UPDATE alerts SET status='triggered', triggered_at=?, triggered_price=? "
                 "WHERE id = ? AND status = 'active'"),
            (triggered_at, price, alert_id),
        )


# ── settings ──────────────────────────────────────────────────────────────────

def get_setting(key: str, default: Any = None) -> Any:
    with _conn() as c:
        r = c.execute(_sql("SELECT value FROM settings WHERE key = ?"), (key,)).fetchone()
    if r is None:
        return default
    try:
        return json.loads(r["value"])
    except Exception:
        return default


def set_setting(key: str, value: Any) -> None:
    with _conn() as c:
        c.execute(
            _sql("INSERT INTO settings(key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value"),
            (key, json.dumps(value)),
        )


# ── fundamentals TTL cache ────────────────────────────────────────────────────

def cache_get(symbol: str) -> Optional[dict]:
    """Return {payload, origin, fetched_at, age_seconds} or None."""
    with _conn() as c:
        r = c.execute(
            _sql("SELECT payload, origin, fetched_at FROM fundamentals_cache WHERE symbol = ?"),
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
            _sql("INSERT INTO fundamentals_cache(symbol, exchange, payload, origin, fetched_at) "
                 "VALUES (?,?,?,?,?) "
                 "ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload, "
                 "origin=excluded.origin, fetched_at=excluded.fetched_at, "
                 "exchange=excluded.exchange"),
            (symbol.upper(), exchange, json.dumps(payload), origin, time.time()),
        )


# ── saved screens (persistent, re-loadable screener universes) ────────────────

def _json_nan_safe(obj):
    """Replace NaN/Inf with None recursively before json.dumps — Python's
    json module emits bare NaN by default (invalid per the JSON spec), which
    a browser's JSON.parse rejects outright on the way back out over the API."""
    if isinstance(obj, float):
        return None if (obj != obj or obj in (float("inf"), float("-inf"))) else obj
    if isinstance(obj, dict):
        return {k: _json_nan_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_nan_safe(v) for v in obj]
    return obj


def _row_to_screen(r, with_tickers: bool = True) -> dict:
    try:
        tickers = json.loads(r["tickers"])
    except Exception:
        tickers = []
    out = {
        "id": r["id"],
        "name": r["name"],
        "count": len(tickers),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }
    if with_tickers:
        out["tickers"] = tickers
        out["computed_at"] = r["computed_at"] if "computed_at" in r.keys() else None
        raw = r["ranked_data"] if "ranked_data" in r.keys() else None
        try:
            out["ranked_data"] = json.loads(raw) if raw else None
        except Exception:
            out["ranked_data"] = None
    return out


def screens_all() -> list:
    """All saved screens, newest first, WITHOUT the (large) ticker/ranked-data
    payloads — enough to populate a dropdown."""
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT * FROM saved_screens ORDER BY updated_at DESC"
        )).fetchall()
    return [_row_to_screen(r, with_tickers=False) for r in rows]


def screen_get(screen_id: int) -> Optional[dict]:
    """Full payload (tickers + cached ranked_data/computed_at, if any) for
    one saved screen."""
    with _conn() as c:
        r = c.execute(_sql("SELECT * FROM saved_screens WHERE id = ?"),
                      (screen_id,)).fetchone()
    return _row_to_screen(r) if r else None


def screen_save(name: str, tickers: list, ranked_data: Optional[list] = None,
                 computed_at: Optional[float] = None) -> dict:
    """
    Create or replace a saved screen (upsert on name). Tickers are stored as a
    JSON array — deduped, upper-cased, order preserved.

    ranked_data: the fully-computed, cross-sectionally-ranked rows (same
    shape /api/screen-stream's "result" event carries), so loading this
    screen later can render instantly instead of re-running the whole
    fetch+rank pipeline live. Optional — a screen saved without it (or an
    older screen from before this existed) just falls back to a live re-run
    on load, same as before. Defaults computed_at to "now" when ranked_data
    is given but no explicit timestamp is provided.
    """
    seen, clean = set(), []
    for t in tickers:
        u = str(t).strip().upper()
        if u and u not in seen:
            seen.add(u)
            clean.append(u)
    now = time.time()
    ranked_json = json.dumps(_json_nan_safe(ranked_data)) if ranked_data is not None else None
    computed_at = computed_at if computed_at is not None else (now if ranked_data is not None else None)
    with _conn() as c:
        c.execute(
            _sql("INSERT INTO saved_screens"
                 "(name, tickers, ranked_data, computed_at, created_at, updated_at) "
                 "VALUES (?,?,?,?,?,?) "
                 "ON CONFLICT(name) DO UPDATE SET tickers=excluded.tickers, "
                 "ranked_data=excluded.ranked_data, computed_at=excluded.computed_at, "
                 "updated_at=excluded.updated_at"),
            (name.strip(), json.dumps(clean), ranked_json, computed_at, now, now),
        )
        r = c.execute(_sql("SELECT * FROM saved_screens WHERE name = ?"),
                      (name.strip(),)).fetchone()
    return _row_to_screen(r)


def screen_delete(screen_id: int) -> bool:
    with _conn() as c:
        cur = c.execute(_sql("DELETE FROM saved_screens WHERE id = ?"), (screen_id,))
        return cur.rowcount > 0


# ── paper trades (forward-testing log for the Position Sizer) ─────────────────

_NUMERIC_TRADE_FIELDS = ("entry_price", "stop_loss", "target_t1", "target_t2",
                          "score", "pnl_r")


def _row_to_trade(r) -> dict:
    """Postgres returns NUMERIC columns as Decimal; cast to float so both
    backends serialize identically over the API."""
    d = dict(r)
    for k in _NUMERIC_TRADE_FIELDS:
        if d.get(k) is not None:
            d[k] = float(d[k])
    return d


def paper_trade_insert(symbol: str, entry_price: float, stop_loss: float,
                        target_t1: float, target_t2: float,
                        score: Optional[float] = None,
                        setup_type: Optional[str] = None) -> dict:
    """Log a new forward-test trade; returns the created record (with id)."""
    with _conn() as c:
        r = c.execute(
            _sql("INSERT INTO paper_trades"
                 "(symbol, entry_price, stop_loss, target_t1, target_t2, score, setup_type) "
                 "VALUES (?,?,?,?,?,?,?) RETURNING *"),
            (symbol.upper(), entry_price, stop_loss, target_t1, target_t2,
             score, setup_type),
        ).fetchone()
    return _row_to_trade(r)


def paper_trades_all() -> list:
    """All logged trades, newest first."""
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT * FROM paper_trades ORDER BY id DESC"
        )).fetchall()
    return [_row_to_trade(r) for r in rows]


def paper_trades_active() -> list:
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT * FROM paper_trades WHERE status = 'ACTIVE' ORDER BY id"
        )).fetchall()
    return [_row_to_trade(r) for r in rows]


def paper_trade_update_status(trade_id: int, status: str, pnl_r: float) -> bool:
    with _conn() as c:
        cur = c.execute(
            _sql("UPDATE paper_trades SET status = ?, pnl_r = ? WHERE id = ?"),
            (status, pnl_r, trade_id),
        )
        return cur.rowcount > 0


def paper_trades_stats() -> dict:
    """Aggregate scorecard stats — computed in Python so the query stays
    identical (and trivially correct) on both backends."""
    trades = paper_trades_all()
    wins = sum(1 for t in trades if t["status"] in ("WIN_T1", "WIN_T2"))
    losses = sum(1 for t in trades if t["status"] == "STOPPED_OUT")
    active = sum(1 for t in trades if t["status"] == "ACTIVE")
    closed = wins + losses
    net_pnl_r = round(sum(t["pnl_r"] or 0.0 for t in trades), 2)
    return {
        "total_trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / closed * 100, 1) if closed else 0.0,
        "net_pnl_r": net_pnl_r,
        "active_count": active,
    }


# Schema is created on import so any entry point gets a working DB.
init()
