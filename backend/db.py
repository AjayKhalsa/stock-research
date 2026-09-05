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

Postgres connections come from a small bounded pool so concurrent dashboard
requests do not each pay for a new TLS/database handshake. On the SQLite path,
existing data/watchlist.json and data/alerts.json are migrated in on first run.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from config import DATA_DIR

# ── backend selection ─────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_PG = _DATABASE_URL.startswith(("postgres://", "postgresql://"))
_PG_FALLBACK_REASON: str | None = None
_ALLOW_EPHEMERAL_FALLBACK = os.environ.get(
    "ALLOW_EPHEMERAL_DB_FALLBACK", ""
).strip().lower() in {"1", "true", "yes"}


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))

DB_PATH = os.path.join(DATA_DIR, "stocklens.db")   # SQLite fallback path

if _PG:
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row
    # libpq accepts both schemes, but normalize the legacy one for clarity.
    _DSN = _DATABASE_URL.replace("postgres://", "postgresql://", 1)
    _POOL = ConnectionPool(
        conninfo=_DSN,
        min_size=1,
        max_size=_bounded_env_int("DB_POOL_SIZE", 6, 2, 20),
        timeout=5,
        max_idle=300,
        max_lifetime=1800,
        reconnect_timeout=10,
        kwargs={"row_factory": dict_row, "connect_timeout": 5},
        open=False,
    )
else:
    _POOL = None


def _sql(q: str) -> str:
    """Translate `?` placeholders to `%s` for Postgres; no-op for SQLite.
    Safe because none of the queries below contain a literal `?`."""
    return q.replace("?", "%s") if _PG else q


@contextmanager
def _conn() -> Iterator[Any]:
    """A pooled Postgres or short-lived SQLite connection.

    Used as `with _conn() as c: ...`; transactions commit on a clean exit.
    Postgres sessions return to the pool and SQLite connections close.
    """
    if _PG:
        # The pool bounds concurrency and reuses warm TLS sessions. Its timeout
        # prevents a saturated/unavailable database from stalling the API.
        with _POOL.connection(timeout=5) as c:
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
    added_at    REAL NOT NULL,
    note        TEXT,
    added_snapshot_id TEXT,
    updated_at  REAL
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

-- Point-in-time paper tests logged from a published or live Trade Plan.
-- ARMED entries are activated and resolved from later daily candles only.
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
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    entry_low   REAL,
    entry_high  REAL,
    signal_date TEXT,
    snapshot_id TEXT,
    model_version TEXT,
    action_at_add TEXT,
    invalidation TEXT,
    note        TEXT,
    armed_sessions INTEGER NOT NULL DEFAULT 0,
    active_sessions INTEGER NOT NULL DEFAULT 0,
    activated_at REAL,
    closed_at   REAL,
    last_evaluated_date TEXT,
    mfe_r       REAL NOT NULL DEFAULT 0,
    mae_r       REAL NOT NULL DEFAULT 0,
    exit_price  REAL,
    outcome_date TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);

-- Immutable, versioned outputs of the CFO morning pipeline.  Payloads remain
-- JSON so the analytical model can evolve without destructive migrations;
-- the indexed columns are the stable fields used for fast navigation.
CREATE TABLE IF NOT EXISTS analysis_snapshots (
    id            TEXT PRIMARY KEY,
    trading_date  TEXT NOT NULL,
    model_version TEXT NOT NULL,
    status        TEXT NOT NULL,
    payload       TEXT NOT NULL,
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analysis_snapshots_latest
    ON analysis_snapshots(status, created_at);

CREATE TABLE IF NOT EXISTS candidate_analyses (
    snapshot_id TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    sector      TEXT NOT NULL,
    global_rank INTEGER,
    sector_rank INTEGER,
    action      TEXT NOT NULL,
    score       REAL,
    confidence  REAL,
    payload     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    PRIMARY KEY(snapshot_id, symbol)
);
CREATE INDEX IF NOT EXISTS idx_candidate_snapshot_rank
    ON candidate_analyses(snapshot_id, global_rank);

CREATE TABLE IF NOT EXISTS sector_snapshots (
    snapshot_id TEXT NOT NULL,
    sector      TEXT NOT NULL,
    sector_rank INTEGER,
    payload     TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, sector)
);

CREATE TABLE IF NOT EXISTS job_runs (
    id          TEXT PRIMARY KEY,
    job_type    TEXT NOT NULL,
    status      TEXT NOT NULL,
    stage       TEXT,
    progress    INTEGER NOT NULL DEFAULT 0,
    total       INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    payload     TEXT,
    started_at  REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_job_runs_latest ON job_runs(job_type, started_at);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id            TEXT PRIMARY KEY,
    model_version TEXT NOT NULL,
    status        TEXT NOT NULL,
    payload       TEXT NOT NULL,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendation_outcomes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id   TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    action        TEXT NOT NULL,
    model_version TEXT,
    signal_date   TEXT,
    score         REAL,
    setup_type    TEXT,
    classification TEXT,
    sector        TEXT,
    market_cap_cr REAL,
    market_cap_bucket TEXT,
    market_regime TEXT,
    global_rank   INTEGER,
    sector_rank   INTEGER,
    entry_low     REAL,
    entry_high    REAL,
    entry_price   REAL,
    stop_price    REAL,
    target_t1     REAL,
    target_t2     REAL,
    signal_adjustment_factor REAL NOT NULL DEFAULT 1,
    level_adjustment_factor REAL NOT NULL DEFAULT 1,
    tracking_role TEXT NOT NULL DEFAULT 'actionable',
    status        TEXT NOT NULL DEFAULT 'ARMED',
    outcome       TEXT,
    pnl_r         REAL NOT NULL DEFAULT 0,
    invalidation  TEXT,
    armed_sessions INTEGER NOT NULL DEFAULT 0,
    active_sessions INTEGER NOT NULL DEFAULT 0,
    activated_at  REAL,
    last_evaluated_date TEXT,
    mfe_r         REAL NOT NULL DEFAULT 0,
    mae_r         REAL NOT NULL DEFAULT 0,
    exit_price    REAL,
    outcome_date  TEXT,
    opened_at     REAL NOT NULL,
    closed_at     REAL
);

CREATE TABLE IF NOT EXISTS securities (
    security_id   TEXT PRIMARY KEY,
    nse_symbol    TEXT,
    bse_code      TEXT,
    isin          TEXT,
    company_name  TEXT NOT NULL,
    sector        TEXT,
    industry      TEXT,
    market_cap_cr REAL,
    listing_date  TEXT,
    fno_flag      INTEGER,
    active_flag   INTEGER NOT NULL DEFAULT 1,
    first_seen_at REAL NOT NULL,
    last_seen_at  REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_securities_isin
    ON securities(isin) WHERE isin IS NOT NULL AND isin <> '';
CREATE INDEX IF NOT EXISTS idx_securities_nse_symbol ON securities(nse_symbol);

CREATE TABLE IF NOT EXISTS market_prices_raw (
    security_id     TEXT NOT NULL,
    trading_date    TEXT NOT NULL,
    provider        TEXT NOT NULL,
    revision_hash   TEXT NOT NULL,
    open_price      REAL,
    high_price      REAL,
    low_price       REAL,
    close_price     REAL,
    volume          REAL,
    delivery_volume REAL,
    turnover        REAL,
    source_url      TEXT,
    observed_at     REAL NOT NULL,
    PRIMARY KEY(security_id, trading_date, provider, revision_hash)
);
CREATE INDEX IF NOT EXISTS idx_market_prices_raw_date
    ON market_prices_raw(trading_date, security_id);

CREATE TABLE IF NOT EXISTS market_prices_adjusted (
    security_id      TEXT NOT NULL,
    trading_date     TEXT NOT NULL,
    provider         TEXT NOT NULL,
    revision_hash    TEXT NOT NULL,
    open_price       REAL,
    high_price       REAL,
    low_price        REAL,
    adjusted_close   REAL,
    raw_close        REAL,
    adjustment_factor REAL,
    volume           REAL,
    observed_at      REAL NOT NULL,
    PRIMARY KEY(security_id, trading_date, provider, revision_hash)
);
CREATE INDEX IF NOT EXISTS idx_market_prices_adjusted_date
    ON market_prices_adjusted(trading_date, security_id);

CREATE TABLE IF NOT EXISTS corporate_actions (
    id               TEXT PRIMARY KEY,
    security_id      TEXT NOT NULL,
    effective_date   TEXT NOT NULL,
    action_type      TEXT NOT NULL,
    adjustment_ratio REAL,
    source           TEXT NOT NULL,
    evidence_hash    TEXT NOT NULL,
    detected_at      REAL NOT NULL,
    UNIQUE(security_id, effective_date, source, evidence_hash)
);

CREATE TABLE IF NOT EXISTS financial_reports (
    id              TEXT PRIMARY KEY,
    security_id     TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    statement_type  TEXT NOT NULL,
    period_label    TEXT NOT NULL,
    filing_date     TEXT,
    observed_at     REAL NOT NULL,
    source          TEXT,
    source_document TEXT,
    payload_hash    TEXT NOT NULL,
    payload         TEXT NOT NULL,
    UNIQUE(security_id, statement_type, period_label, payload_hash)
);
CREATE INDEX IF NOT EXISTS idx_financial_reports_point_in_time
    ON financial_reports(security_id, observed_at, statement_type);

CREATE TABLE IF NOT EXISTS company_events (
    id            TEXT PRIMARY KEY,
    security_id   TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    event_date    TEXT,
    filing_date   TEXT,
    severity      TEXT,
    description   TEXT,
    source        TEXT,
    source_url    TEXT,
    evidence_hash TEXT NOT NULL,
    observed_at   REAL NOT NULL,
    UNIQUE(security_id, evidence_hash)
);

CREATE TABLE IF NOT EXISTS stock_feature_snapshots (
    security_id    TEXT NOT NULL,
    feature_date   TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    feature_scope  TEXT NOT NULL,
    revision_hash  TEXT NOT NULL,
    payload        TEXT NOT NULL,
    observed_at    REAL NOT NULL,
    PRIMARY KEY(security_id, feature_date, feature_version, feature_scope, revision_hash)
);
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_date
    ON stock_feature_snapshots(feature_date, feature_version, feature_scope);

CREATE TABLE IF NOT EXISTS human_reviews (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id           TEXT NOT NULL,
    symbol                TEXT NOT NULL,
    model_version         TEXT NOT NULL,
    recommendation_action TEXT NOT NULL,
    score_at_review       REAL,
    assessment            TEXT NOT NULL,
    tags                  TEXT NOT NULL DEFAULT '[]',
    notes                 TEXT,
    created_at            REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_human_reviews_candidate
    ON human_reviews(snapshot_id, symbol, created_at);

CREATE TABLE IF NOT EXISTS candidate_enrichments (
    symbol       TEXT NOT NULL,
    provider     TEXT NOT NULL,
    version      TEXT NOT NULL,
    as_of        TEXT,
    payload      TEXT NOT NULL,
    refreshed_at REAL NOT NULL,
    PRIMARY KEY(symbol, provider)
);
CREATE INDEX IF NOT EXISTS idx_candidate_enrichments_provider
    ON candidate_enrichments(provider, refreshed_at);
"""

# Postgres variant: BIGSERIAL for autoincrement, DOUBLE PRECISION for the epoch
# timestamps (PG REAL is a lossy 4-byte float). Column names/semantics match.
_SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol      TEXT PRIMARY KEY,
    exchange    TEXT NOT NULL DEFAULT 'NSE',
    name        TEXT,
    added_at    DOUBLE PRECISION NOT NULL,
    note        TEXT,
    added_snapshot_id TEXT,
    updated_at  DOUBLE PRECISION
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
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    entry_low   DOUBLE PRECISION,
    entry_high  DOUBLE PRECISION,
    signal_date TEXT,
    snapshot_id TEXT,
    model_version TEXT,
    action_at_add TEXT,
    invalidation TEXT,
    note        TEXT,
    armed_sessions INTEGER NOT NULL DEFAULT 0,
    active_sessions INTEGER NOT NULL DEFAULT 0,
    activated_at DOUBLE PRECISION,
    closed_at   DOUBLE PRECISION,
    last_evaluated_date TEXT,
    mfe_r       DOUBLE PRECISION NOT NULL DEFAULT 0,
    mae_r       DOUBLE PRECISION NOT NULL DEFAULT 0,
    exit_price  DOUBLE PRECISION,
    outcome_date TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);

CREATE TABLE IF NOT EXISTS analysis_snapshots (
    id            TEXT PRIMARY KEY,
    trading_date  TEXT NOT NULL,
    model_version TEXT NOT NULL,
    status        TEXT NOT NULL,
    payload       TEXT NOT NULL,
    created_at    DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analysis_snapshots_latest
    ON analysis_snapshots(status, created_at);

CREATE TABLE IF NOT EXISTS candidate_analyses (
    snapshot_id TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    sector      TEXT NOT NULL,
    global_rank INTEGER,
    sector_rank INTEGER,
    action      TEXT NOT NULL,
    score       DOUBLE PRECISION,
    confidence  DOUBLE PRECISION,
    payload     TEXT NOT NULL,
    created_at  DOUBLE PRECISION NOT NULL,
    PRIMARY KEY(snapshot_id, symbol)
);
CREATE INDEX IF NOT EXISTS idx_candidate_snapshot_rank
    ON candidate_analyses(snapshot_id, global_rank);

CREATE TABLE IF NOT EXISTS sector_snapshots (
    snapshot_id TEXT NOT NULL,
    sector      TEXT NOT NULL,
    sector_rank INTEGER,
    payload     TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, sector)
);

CREATE TABLE IF NOT EXISTS job_runs (
    id          TEXT PRIMARY KEY,
    job_type    TEXT NOT NULL,
    status      TEXT NOT NULL,
    stage       TEXT,
    progress    INTEGER NOT NULL DEFAULT 0,
    total       INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    payload     TEXT,
    started_at  DOUBLE PRECISION NOT NULL,
    finished_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_job_runs_latest ON job_runs(job_type, started_at);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id            TEXT PRIMARY KEY,
    model_version TEXT NOT NULL,
    status        TEXT NOT NULL,
    payload       TEXT NOT NULL,
    created_at    DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendation_outcomes (
    id            BIGSERIAL PRIMARY KEY,
    snapshot_id   TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    action        TEXT NOT NULL,
    model_version TEXT,
    signal_date   TEXT,
    score         DOUBLE PRECISION,
    setup_type    TEXT,
    classification TEXT,
    sector        TEXT,
    market_cap_cr DOUBLE PRECISION,
    market_cap_bucket TEXT,
    market_regime TEXT,
    global_rank   INTEGER,
    sector_rank   INTEGER,
    entry_low     DOUBLE PRECISION,
    entry_high    DOUBLE PRECISION,
    entry_price   DOUBLE PRECISION,
    stop_price    DOUBLE PRECISION,
    target_t1     DOUBLE PRECISION,
    target_t2     DOUBLE PRECISION,
    signal_adjustment_factor DOUBLE PRECISION NOT NULL DEFAULT 1,
    level_adjustment_factor DOUBLE PRECISION NOT NULL DEFAULT 1,
    tracking_role TEXT NOT NULL DEFAULT 'actionable',
    status        TEXT NOT NULL DEFAULT 'ARMED',
    outcome       TEXT,
    pnl_r         DOUBLE PRECISION NOT NULL DEFAULT 0,
    invalidation  TEXT,
    armed_sessions INTEGER NOT NULL DEFAULT 0,
    active_sessions INTEGER NOT NULL DEFAULT 0,
    activated_at  DOUBLE PRECISION,
    last_evaluated_date TEXT,
    mfe_r         DOUBLE PRECISION NOT NULL DEFAULT 0,
    mae_r         DOUBLE PRECISION NOT NULL DEFAULT 0,
    exit_price    DOUBLE PRECISION,
    outcome_date  TEXT,
    opened_at     DOUBLE PRECISION NOT NULL,
    closed_at     DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS securities (
    security_id   TEXT PRIMARY KEY,
    nse_symbol    TEXT,
    bse_code      TEXT,
    isin          TEXT,
    company_name  TEXT NOT NULL,
    sector        TEXT,
    industry      TEXT,
    market_cap_cr DOUBLE PRECISION,
    listing_date  TEXT,
    fno_flag      INTEGER,
    active_flag   INTEGER NOT NULL DEFAULT 1,
    first_seen_at DOUBLE PRECISION NOT NULL,
    last_seen_at  DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_securities_isin
    ON securities(isin) WHERE isin IS NOT NULL AND isin <> '';
CREATE INDEX IF NOT EXISTS idx_securities_nse_symbol ON securities(nse_symbol);

CREATE TABLE IF NOT EXISTS market_prices_raw (
    security_id     TEXT NOT NULL,
    trading_date    TEXT NOT NULL,
    provider        TEXT NOT NULL,
    revision_hash   TEXT NOT NULL,
    open_price      DOUBLE PRECISION,
    high_price      DOUBLE PRECISION,
    low_price       DOUBLE PRECISION,
    close_price     DOUBLE PRECISION,
    volume          DOUBLE PRECISION,
    delivery_volume DOUBLE PRECISION,
    turnover        DOUBLE PRECISION,
    source_url      TEXT,
    observed_at     DOUBLE PRECISION NOT NULL,
    PRIMARY KEY(security_id, trading_date, provider, revision_hash)
);
CREATE INDEX IF NOT EXISTS idx_market_prices_raw_date
    ON market_prices_raw(trading_date, security_id);

CREATE TABLE IF NOT EXISTS market_prices_adjusted (
    security_id      TEXT NOT NULL,
    trading_date     TEXT NOT NULL,
    provider         TEXT NOT NULL,
    revision_hash    TEXT NOT NULL,
    open_price       DOUBLE PRECISION,
    high_price       DOUBLE PRECISION,
    low_price        DOUBLE PRECISION,
    adjusted_close   DOUBLE PRECISION,
    raw_close        DOUBLE PRECISION,
    adjustment_factor DOUBLE PRECISION,
    volume           DOUBLE PRECISION,
    observed_at      DOUBLE PRECISION NOT NULL,
    PRIMARY KEY(security_id, trading_date, provider, revision_hash)
);
CREATE INDEX IF NOT EXISTS idx_market_prices_adjusted_date
    ON market_prices_adjusted(trading_date, security_id);

CREATE TABLE IF NOT EXISTS corporate_actions (
    id               TEXT PRIMARY KEY,
    security_id      TEXT NOT NULL,
    effective_date   TEXT NOT NULL,
    action_type      TEXT NOT NULL,
    adjustment_ratio DOUBLE PRECISION,
    source           TEXT NOT NULL,
    evidence_hash    TEXT NOT NULL,
    detected_at      DOUBLE PRECISION NOT NULL,
    UNIQUE(security_id, effective_date, source, evidence_hash)
);

CREATE TABLE IF NOT EXISTS financial_reports (
    id              TEXT PRIMARY KEY,
    security_id     TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    statement_type  TEXT NOT NULL,
    period_label    TEXT NOT NULL,
    filing_date     TEXT,
    observed_at     DOUBLE PRECISION NOT NULL,
    source          TEXT,
    source_document TEXT,
    payload_hash    TEXT NOT NULL,
    payload         TEXT NOT NULL,
    UNIQUE(security_id, statement_type, period_label, payload_hash)
);
CREATE INDEX IF NOT EXISTS idx_financial_reports_point_in_time
    ON financial_reports(security_id, observed_at, statement_type);

CREATE TABLE IF NOT EXISTS company_events (
    id            TEXT PRIMARY KEY,
    security_id   TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    event_date    TEXT,
    filing_date   TEXT,
    severity      TEXT,
    description   TEXT,
    source        TEXT,
    source_url    TEXT,
    evidence_hash TEXT NOT NULL,
    observed_at   DOUBLE PRECISION NOT NULL,
    UNIQUE(security_id, evidence_hash)
);

CREATE TABLE IF NOT EXISTS stock_feature_snapshots (
    security_id    TEXT NOT NULL,
    feature_date   TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    feature_scope  TEXT NOT NULL,
    revision_hash  TEXT NOT NULL,
    payload        TEXT NOT NULL,
    observed_at    DOUBLE PRECISION NOT NULL,
    PRIMARY KEY(security_id, feature_date, feature_version, feature_scope, revision_hash)
);
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_date
    ON stock_feature_snapshots(feature_date, feature_version, feature_scope);

CREATE TABLE IF NOT EXISTS human_reviews (
    id                    BIGSERIAL PRIMARY KEY,
    snapshot_id           TEXT NOT NULL,
    symbol                TEXT NOT NULL,
    model_version         TEXT NOT NULL,
    recommendation_action TEXT NOT NULL,
    score_at_review       DOUBLE PRECISION,
    assessment            TEXT NOT NULL,
    tags                  TEXT NOT NULL DEFAULT '[]',
    notes                 TEXT,
    created_at            DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_human_reviews_candidate
    ON human_reviews(snapshot_id, symbol, created_at);

CREATE TABLE IF NOT EXISTS candidate_enrichments (
    symbol       TEXT NOT NULL,
    provider     TEXT NOT NULL,
    version      TEXT NOT NULL,
    as_of        TEXT,
    payload      TEXT NOT NULL,
    refreshed_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY(symbol, provider)
);
CREATE INDEX IF NOT EXISTS idx_candidate_enrichments_provider
    ON candidate_enrichments(provider, refreshed_at);
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


def _migrate_unified_research_columns() -> None:
    """Add the unified-workspace metadata without rewriting legacy rows."""
    watchlist_columns = {
        "note": "TEXT",
        "added_snapshot_id": "TEXT",
        "updated_at": "DOUBLE PRECISION" if _PG else "REAL",
    }
    paper_columns = {
        "entry_low": "DOUBLE PRECISION" if _PG else "REAL",
        "entry_high": "DOUBLE PRECISION" if _PG else "REAL",
        "signal_date": "TEXT",
        "snapshot_id": "TEXT",
        "model_version": "TEXT",
        "action_at_add": "TEXT",
        "invalidation": "TEXT",
        "note": "TEXT",
        "armed_sessions": "INTEGER NOT NULL DEFAULT 0",
        "active_sessions": "INTEGER NOT NULL DEFAULT 0",
        "activated_at": "DOUBLE PRECISION" if _PG else "REAL",
        "closed_at": "DOUBLE PRECISION" if _PG else "REAL",
        "last_evaluated_date": "TEXT",
        "mfe_r": "DOUBLE PRECISION NOT NULL DEFAULT 0" if _PG else "REAL NOT NULL DEFAULT 0",
        "mae_r": "DOUBLE PRECISION NOT NULL DEFAULT 0" if _PG else "REAL NOT NULL DEFAULT 0",
        "exit_price": "DOUBLE PRECISION" if _PG else "REAL",
        "outcome_date": "TEXT",
    }
    outcome_columns = {
        "model_version": "TEXT",
        "signal_date": "TEXT",
        "score": "DOUBLE PRECISION" if _PG else "REAL",
        "setup_type": "TEXT",
        "classification": "TEXT",
        "sector": "TEXT",
        "market_cap_cr": "DOUBLE PRECISION" if _PG else "REAL",
        "market_cap_bucket": "TEXT",
        "market_regime": "TEXT",
        "global_rank": "INTEGER",
        "sector_rank": "INTEGER",
        "entry_low": "DOUBLE PRECISION" if _PG else "REAL",
        "entry_high": "DOUBLE PRECISION" if _PG else "REAL",
        "target_t1": "DOUBLE PRECISION" if _PG else "REAL",
        "target_t2": "DOUBLE PRECISION" if _PG else "REAL",
        "signal_adjustment_factor": "DOUBLE PRECISION NOT NULL DEFAULT 1" if _PG else "REAL NOT NULL DEFAULT 1",
        "level_adjustment_factor": "DOUBLE PRECISION NOT NULL DEFAULT 1" if _PG else "REAL NOT NULL DEFAULT 1",
        "tracking_role": "TEXT NOT NULL DEFAULT 'actionable'",
        "status": "TEXT NOT NULL DEFAULT 'ARMED'",
        "invalidation": "TEXT",
        "armed_sessions": "INTEGER NOT NULL DEFAULT 0",
        "active_sessions": "INTEGER NOT NULL DEFAULT 0",
        "activated_at": "DOUBLE PRECISION" if _PG else "REAL",
        "last_evaluated_date": "TEXT",
        "mfe_r": "DOUBLE PRECISION NOT NULL DEFAULT 0" if _PG else "REAL NOT NULL DEFAULT 0",
        "mae_r": "DOUBLE PRECISION NOT NULL DEFAULT 0" if _PG else "REAL NOT NULL DEFAULT 0",
        "exit_price": "DOUBLE PRECISION" if _PG else "REAL",
        "outcome_date": "TEXT",
    }
    human_review_columns = {
        "tags": "TEXT NOT NULL DEFAULT '[]'",
    }
    if _PG:
        with _conn() as c:
            with c.cursor() as cur:
                for name, sql_type in watchlist_columns.items():
                    cur.execute(f"ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS {name} {sql_type}")
                for name, sql_type in paper_columns.items():
                    cur.execute(f"ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS {name} {sql_type}")
                for name, sql_type in outcome_columns.items():
                    cur.execute(f"ALTER TABLE recommendation_outcomes ADD COLUMN IF NOT EXISTS {name} {sql_type}")
                for name, sql_type in human_review_columns.items():
                    cur.execute(f"ALTER TABLE human_reviews ADD COLUMN IF NOT EXISTS {name} {sql_type}")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_status "
                            "ON recommendation_outcomes(status, symbol)")
        return
    with _conn() as c:
        for table, columns in (("watchlist", watchlist_columns),
                               ("paper_trades", paper_columns),
                               ("recommendation_outcomes", outcome_columns),
                               ("human_reviews", human_review_columns)):
            existing = {row[1] for row in c.execute(f"PRAGMA table_info({table})").fetchall()}
            for name, sql_type in columns.items():
                if name not in existing:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
        c.execute("CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_status "
                  "ON recommendation_outcomes(status, symbol)")


def init() -> None:
    """Create schema (idempotent). SQLite path also migrates legacy JSON once."""
    if _PG:
        print("[db] Using Postgres — persistent across restarts.")
        _POOL.open(wait=True, timeout=8)
        with _conn() as c:
            with c.cursor() as cur:
                for stmt in _SCHEMA_PG.split(";"):
                    if stmt.strip():
                        cur.execute(stmt)
        _migrate_saved_screens_columns()
        _migrate_unified_research_columns()
        _seed_candidate_enrichments()
        return
    print(f"[db] Using local SQLite at {DB_PATH} — EPHEMERAL on most hosts "
          f"(e.g. Render's free plan wipes this on every restart/redeploy). "
          f"Set DATABASE_URL to a Postgres connection string to persist data "
          f"across restarts.")
    with _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA_SQLITE)
    _migrate_saved_screens_columns()
    _migrate_unified_research_columns()
    _migrate_legacy_json()
    _seed_candidate_enrichments()


def storage_status() -> dict:
    status = {
        "backend": "postgres" if _PG else "sqlite",
        "durable": bool(_PG),
        "fallback_reason": _PG_FALLBACK_REASON,
    }
    if _PG and _POOL is not None:
        status["pool"] = _POOL.get_stats()
    return status


def ping() -> bool:
    """Verify that the active persistence backend can serve a trivial query."""
    with _conn() as c:
        c.execute("SELECT 1").fetchone()
    return True


def _initialize_with_fallback() -> None:
    global _PG, _PG_FALLBACK_REASON
    try:
        init()
    except Exception as exc:
        if not _PG:
            raise
        _PG_FALLBACK_REASON = f"{type(exc).__name__}: {exc}"
        if _POOL is not None:
            _POOL.close()
        if not _ALLOW_EPHEMERAL_FALLBACK:
            print("[db] Postgres initialization failed; refusing an ephemeral "
                  "fallback to protect durable data. Render should restart the "
                  f"service. Reason: {_PG_FALLBACK_REASON}")
            raise
        print("[db] Postgres initialization failed; ALLOW_EPHEMERAL_DB_FALLBACK "
              f"is enabled. Using local SQLite. Reason: {_PG_FALLBACK_REASON}")
        _PG = False
        init()


def close() -> None:
    """Release pooled database connections during a graceful API shutdown."""
    if _POOL is not None:
        _POOL.close()


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
            "SELECT symbol, exchange, name, added_at, note, added_snapshot_id, updated_at "
            "FROM watchlist ORDER BY added_at"
        )).fetchall()
    return [dict(r) for r in rows]


def watchlist_add(symbol: str, exchange: str = "NSE", name: str = "",
                  note: str = "", added_snapshot_id: Optional[str] = None) -> list:
    now = time.time()
    with _conn() as c:
        c.execute(_sql(
            "INSERT INTO watchlist(symbol, exchange, name, added_at, note, added_snapshot_id, updated_at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
            "exchange = excluded.exchange, name = excluded.name, "
            "note = CASE WHEN excluded.note <> '' THEN excluded.note ELSE watchlist.note END, "
            "updated_at = excluded.updated_at"),
            (symbol.upper(), exchange, name or symbol.upper(), now, note or "",
             added_snapshot_id, now),
        )
    return watchlist_all()


def watchlist_get(symbol: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute(_sql(
            "SELECT symbol, exchange, name, added_at, note, added_snapshot_id, updated_at "
            "FROM watchlist WHERE symbol = ?"
        ), (symbol.upper(),)).fetchone()
    return dict(row) if row else None


def watchlist_update(symbol: str, note: Optional[str] = None, name: Optional[str] = None) -> Optional[dict]:
    current = watchlist_get(symbol)
    if not current:
        return None
    with _conn() as c:
        c.execute(_sql(
            "UPDATE watchlist SET note = ?, name = ?, updated_at = ? WHERE symbol = ?"
        ), (current.get("note") if note is None else note,
            current.get("name") if name is None else name,
            time.time(), symbol.upper()))
    return watchlist_get(symbol)


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


# ── CFO workspace snapshots and daily jobs ───────────────────────────────────

def _loads_payload(raw: Any, default: Any) -> Any:
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def create_job_run(job_type: str = "daily_cfo") -> dict:
    job_id = uuid.uuid4().hex
    started = time.time()
    with _conn() as c:
        c.execute(
            _sql("INSERT INTO job_runs(id, job_type, status, stage, progress, total, "
                 "started_at) VALUES (?,?,?,?,?,?,?)"),
            (job_id, job_type, "running", "queued", 0, 0, started),
        )
    return get_job_run(job_id) or {"id": job_id, "status": "running"}


def update_job_run(job_id: str, *, status: Optional[str] = None,
                   stage: Optional[str] = None, progress: Optional[int] = None,
                   total: Optional[int] = None, error: Optional[str] = None,
                   payload: Optional[dict] = None) -> None:
    fields, values = [], []
    for column, value in (("status", status), ("stage", stage),
                          ("progress", progress), ("total", total),
                          ("error", error)):
        if value is not None:
            fields.append(f"{column} = ?")
            values.append(value)
    if payload is not None:
        fields.append("payload = ?")
        values.append(json.dumps(_json_nan_safe(payload)))
    if status in {"completed", "failed"}:
        fields.append("finished_at = ?")
        values.append(time.time())
    if not fields:
        return
    values.append(job_id)
    with _conn() as c:
        c.execute(_sql(f"UPDATE job_runs SET {', '.join(fields)} WHERE id = ?"), tuple(values))


def _row_to_job(row) -> Optional[dict]:
    if not row:
        return None
    out = dict(row)
    out["payload"] = _loads_payload(out.get("payload"), {})
    return out


def get_job_run(job_id: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute(_sql("SELECT * FROM job_runs WHERE id = ?"), (job_id,)).fetchone()
    return _row_to_job(row)


def latest_job_run(job_type: str = "daily_cfo") -> Optional[dict]:
    with _conn() as c:
        row = c.execute(
            _sql("SELECT * FROM job_runs WHERE job_type = ? ORDER BY started_at DESC LIMIT 1"),
            (job_type,),
        ).fetchone()
    return _row_to_job(row)


def _as_finite_float(value) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _recommendation_outcome_values(snapshot_id: str, item: dict, *,
                                   model_version: str, trading_date: str,
                                   opened_at: float,
                                   market_regime: Optional[str],
                                   allow_observational: bool = False) -> Optional[tuple]:
    """Return a validated automatic forward-test row for actionable states."""
    action = item.get("action")
    actionable = action in {"BUY_NOW", "WAIT_FOR_ENTRY"}
    if not actionable and not (allow_observational and action in {"WATCH", "AVOID"}):
        return None
    plan = item.get("trade_plan") or {}
    entry = plan.get("entry") or {}
    stop = plan.get("stop") or {}
    targets = plan.get("targets") or []
    low = _as_finite_float(entry.get("low"))
    high = _as_finite_float(entry.get("high"))
    stop_price = _as_finite_float(stop.get("price"))
    t1 = _as_finite_float((targets[0] or {}).get("price")) if targets else None
    t2_candidate = (_as_finite_float((targets[1] or {}).get("price"))
                    if len(targets) > 1 else None)
    t2 = t2_candidate if t2_candidate is not None else t1
    signal_factor = _as_finite_float(
        ((item.get("evidence") or {}).get("price") or {}).get("adjustment_factor")
    ) or 1.0
    if signal_factor <= 0:
        signal_factor = 1.0
    if (None in (low, high, stop_price, t1, t2) or low <= 0 or high < low
            or stop_price <= 0 or stop_price >= low or t1 <= high or t2 < t1):
        return None
    return (
        snapshot_id, str(item.get("symbol") or "").upper(), item["action"],
        model_version, trading_date, _as_finite_float(item.get("score")),
        item.get("setup_type"), item.get("classification"), item.get("sector"),
        _as_finite_float(item.get("market_cap_cr")), item.get("market_cap_bucket"),
        market_regime, item.get("global_rank"), item.get("sector_rank"),
        low, high, (low + high) / 2, stop_price, t1, t2,
        signal_factor, 1.0, "actionable" if actionable else "observational",
        "ARMED", None, 0.0,
        plan.get("invalidation"), opened_at,
    )


def publish_analysis_snapshot(summary: dict, candidates: list[dict],
                              sectors: list[dict], *, model_version: str,
                              trading_date: str) -> str:
    """Atomically publish one immutable snapshot and all of its children."""
    snapshot_id = uuid.uuid4().hex
    now = time.time()
    safe_summary = dict(summary)
    safe_summary["snapshot_id"] = snapshot_id
    safe_summary["model_version"] = model_version
    safe_summary["trading_date"] = trading_date
    market_regime = ((summary.get("market_regime") or {}).get("state")
                     if isinstance(summary.get("market_regime"), dict) else None)
    observational_remaining = {"WATCH": 20, "AVOID": 5}
    with _conn() as c:
        existing_observations = c.execute(_sql(
            "SELECT action, COUNT(*) AS count FROM recommendation_outcomes "
            "WHERE model_version = ? AND signal_date = ? "
            "AND tracking_role = 'observational' GROUP BY action"
        ), (model_version, trading_date)).fetchall()
        for row in existing_observations:
            action = row["action"]
            if action in observational_remaining:
                observational_remaining[action] = max(
                    0, observational_remaining[action] - int(row["count"] or 0)
                )
        c.execute(
            _sql("INSERT INTO analysis_snapshots(id, trading_date, model_version, status, "
                 "payload, created_at) VALUES (?,?,?,?,?,?)"),
            (snapshot_id, trading_date, model_version, "valid",
             json.dumps(_json_nan_safe(safe_summary)), now),
        )
        for item in candidates:
            c.execute(
                _sql("INSERT INTO candidate_analyses(snapshot_id, symbol, sector, "
                     "global_rank, sector_rank, action, score, confidence, payload, created_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)"),
                (snapshot_id, item.get("symbol"), item.get("sector") or "Unclassified",
                 item.get("global_rank"), item.get("sector_rank"), item.get("action") or "WATCH",
                 item.get("score"), item.get("confidence"),
                 json.dumps(_json_nan_safe(item)), now),
            )
            outcome_values = _recommendation_outcome_values(
                snapshot_id, item, model_version=model_version,
                trading_date=trading_date, opened_at=now,
                market_regime=market_regime,
                allow_observational=(
                    observational_remaining.get(item.get("action"), 0) > 0
                ),
            )
            if outcome_values:
                existing_outcome = c.execute(_sql(
                    "SELECT id FROM recommendation_outcomes "
                    "WHERE model_version = ? AND signal_date = ? AND symbol = ? LIMIT 1"
                ), (model_version, trading_date,
                    str(item.get("symbol") or "").upper())).fetchone()
                if existing_outcome:
                    continue
                if item.get("action") in observational_remaining:
                    observational_remaining[item["action"]] -= 1
                c.execute(_sql(
                    "INSERT INTO recommendation_outcomes(snapshot_id, symbol, action, "
                    "model_version, signal_date, score, setup_type, classification, "
                    "sector, market_cap_cr, market_cap_bucket, market_regime, "
                    "global_rank, sector_rank, entry_low, entry_high, "
                    "entry_price, stop_price, target_t1, target_t2, signal_adjustment_factor, "
                    "level_adjustment_factor, tracking_role, "
                    "status, outcome, pnl_r, invalidation, opened_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                ), outcome_values)
        for item in sectors:
            c.execute(
                _sql("INSERT INTO sector_snapshots(snapshot_id, sector, sector_rank, payload) "
                     "VALUES (?,?,?,?)"),
                (snapshot_id, item.get("sector") or "Unclassified", item.get("rank"),
                 json.dumps(_json_nan_safe(item))),
            )
    return snapshot_id


def latest_analysis_snapshot() -> Optional[dict]:
    with _conn() as c:
        row = c.execute(_sql(
            "SELECT * FROM analysis_snapshots WHERE status = 'valid' "
            "ORDER BY created_at DESC LIMIT 1"
        )).fetchone()
    if not row:
        return None
    out = _loads_payload(row["payload"], {})
    out.update({"snapshot_id": row["id"], "trading_date": row["trading_date"],
                "model_version": row["model_version"], "created_at": row["created_at"]})
    return out


def snapshot_candidates(snapshot_id: Optional[str] = None, limit: int = 100) -> list:
    if not snapshot_id:
        latest = latest_analysis_snapshot()
        snapshot_id = latest.get("snapshot_id") if latest else None
    if not snapshot_id:
        return []
    with _conn() as c:
        rows = c.execute(
            _sql("SELECT payload FROM candidate_analyses WHERE snapshot_id = ? "
                 "ORDER BY global_rank LIMIT ?"),
            (snapshot_id, max(1, min(int(limit), 500))),
        ).fetchall()
    return [_loads_payload(r["payload"], {}) for r in rows]


def candidate_analysis(symbol: str, snapshot_id: Optional[str] = None) -> Optional[dict]:
    if not snapshot_id:
        latest = latest_analysis_snapshot()
        snapshot_id = latest.get("snapshot_id") if latest else None
    if not snapshot_id:
        return None
    with _conn() as c:
        row = c.execute(
            _sql("SELECT payload FROM candidate_analyses WHERE snapshot_id = ? AND symbol = ?"),
            (snapshot_id, symbol.upper()),
        ).fetchone()
    return _loads_payload(row["payload"], {}) if row else None


def human_review_add(snapshot_id: str, symbol: str, assessment: str,
                     notes: str = "", tags: Optional[list[str]] = None) -> Optional[dict]:
    """Append an immutable review tied to the exact recommendation row."""
    now = time.time()
    normalized_tags = list(dict.fromkeys(tags or []))
    with _conn() as c:
        recommendation = c.execute(_sql(
            "SELECT ca.action, ca.score, snapshots.model_version "
            "FROM candidate_analyses ca JOIN analysis_snapshots snapshots "
            "ON snapshots.id = ca.snapshot_id "
            "WHERE ca.snapshot_id = ? AND ca.symbol = ?"
        ), (snapshot_id, symbol.upper())).fetchone()
        if not recommendation:
            return None
        row = c.execute(_sql(
            "INSERT INTO human_reviews(snapshot_id, symbol, model_version, "
            "recommendation_action, score_at_review, assessment, tags, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) RETURNING *"
        ), (snapshot_id, symbol.upper(), recommendation["model_version"],
            recommendation["action"], recommendation["score"], assessment,
            json.dumps(normalized_tags), notes, now)).fetchone()
    result = dict(row)
    if result.get("score_at_review") is not None:
        result["score_at_review"] = float(result["score_at_review"])
    result["tags"] = _loads_payload(result.get("tags"), [])
    return result


def human_reviews(symbol: str, snapshot_id: Optional[str] = None,
                  limit: int = 50) -> list[dict]:
    safe_limit = max(1, min(int(limit), 200))
    params: tuple = (symbol.upper(),)
    where = "symbol = ?"
    if snapshot_id:
        where += " AND snapshot_id = ?"
        params += (snapshot_id,)
    params += (safe_limit,)
    with _conn() as c:
        rows = c.execute(_sql(
            f"SELECT * FROM human_reviews WHERE {where} "
            "ORDER BY created_at DESC, id DESC LIMIT ?"
        ), params).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        if item.get("score_at_review") is not None:
            item["score_at_review"] = float(item["score_at_review"])
        item["tags"] = _loads_payload(item.get("tags"), [])
        output.append(item)
    return output


def human_review_stats() -> dict:
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT assessment, COUNT(*) AS count FROM human_reviews "
            "GROUP BY assessment ORDER BY assessment"
        )).fetchall()
        tag_rows = c.execute(_sql("SELECT tags FROM human_reviews")).fetchall()
    by_assessment = {row["assessment"]: int(row["count"] or 0) for row in rows}
    by_tag: dict[str, int] = {}
    for row in tag_rows:
        for tag in _loads_payload(row["tags"], []):
            by_tag[tag] = by_tag.get(tag, 0) + 1
    return {"total": sum(by_assessment.values()), "by_assessment": by_assessment,
            "by_tag": dict(sorted(by_tag.items()))}


def human_reviews_with_resolved_outcomes() -> list[dict]:
    """Return review/outcome pairs for measurement, never for model training."""
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT reviews.*, outcomes.status AS outcome_status, outcomes.pnl_r, "
            "outcomes.mfe_r, outcomes.mae_r, outcomes.entry_price, outcomes.stop_price, "
            "outcomes.global_rank, outcomes.tracking_role, outcomes.outcome_date "
            "FROM human_reviews reviews JOIN recommendation_outcomes outcomes "
            "ON outcomes.snapshot_id = reviews.snapshot_id "
            "AND outcomes.symbol = reviews.symbol "
            "WHERE outcomes.status IN "
            "('WIN_T1','WIN_T2','STOPPED_OUT','TIME_STOP') "
            "ORDER BY reviews.created_at DESC, reviews.id DESC"
        )).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        for field in ("score_at_review", "pnl_r", "mfe_r", "mae_r",
                      "entry_price", "stop_price"):
            if item.get(field) is not None:
                item[field] = float(item[field])
        item["tags"] = _loads_payload(item.get("tags"), [])
        output.append(item)
    return output


_NUMERIC_OUTCOME_FIELDS = (
    "score", "entry_low", "entry_high", "entry_price", "stop_price",
    "target_t1", "target_t2", "pnl_r", "activated_at", "mfe_r", "mae_r",
    "exit_price", "opened_at", "closed_at", "signal_adjustment_factor",
    "level_adjustment_factor", "market_cap_cr",
)


def _row_to_recommendation_outcome(row) -> dict:
    result = dict(row)
    for field in _NUMERIC_OUTCOME_FIELDS:
        if result.get(field) is not None:
            result[field] = float(result[field])
    return result


def recommendation_outcomes_open(limit: int = 2000) -> list[dict]:
    safe_limit = max(1, min(int(limit), 5000))
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT * FROM recommendation_outcomes "
            "WHERE status IN ('ARMED','ACTIVE') ORDER BY id LIMIT ?"
        ), (safe_limit,)).fetchall()
    return [_row_to_recommendation_outcome(row) for row in rows]


def recommendation_outcomes_recent(limit: int = 100) -> list[dict]:
    safe_limit = max(1, min(int(limit), 500))
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT * FROM recommendation_outcomes ORDER BY id DESC LIMIT ?"
        ), (safe_limit,)).fetchall()
    return [_row_to_recommendation_outcome(row) for row in rows]


def recommendation_outcomes_resolved(model_version: Optional[str] = None,
                                     include_observational: bool = False) -> list[dict]:
    params: tuple = ()
    role_clause = "" if include_observational else " AND tracking_role = 'actionable'"
    model_clause = ""
    if model_version:
        model_clause = " AND model_version = ?"
        params = (model_version,)
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT * FROM recommendation_outcomes WHERE status IN "
            "('WIN_T1','WIN_T2','STOPPED_OUT','TIME_STOP')" + role_clause + model_clause
            + " ORDER BY outcome_date, id"
        ), params).fetchall()
    return [_row_to_recommendation_outcome(row) for row in rows]


def recommendation_outcomes_for_calibration(
    model_version: Optional[str] = None,
) -> list[dict]:
    params: tuple = ()
    model_clause = ""
    if model_version:
        model_clause = " AND outcomes.model_version = ?"
        params = (model_version,)
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT outcomes.*, candidates.payload AS candidate_payload "
            "FROM recommendation_outcomes outcomes "
            "JOIN candidate_analyses candidates "
            "ON candidates.snapshot_id = outcomes.snapshot_id "
            "AND candidates.symbol = outcomes.symbol "
            "WHERE outcomes.status IN "
            "('WIN_T1','WIN_T2','STOPPED_OUT','TIME_STOP')" + model_clause
            + " ORDER BY outcomes.outcome_date, outcomes.id"
        ), params).fetchall()
    output = []
    for row in rows:
        item = _row_to_recommendation_outcome(row)
        item["candidate"] = _loads_payload(item.pop("candidate_payload", None), {})
        output.append(item)
    return output


def recommendation_outcome_patch(outcome_id: int, **changes) -> Optional[dict]:
    allowed = {
        "status", "outcome", "pnl_r", "armed_sessions", "active_sessions",
        "activated_at", "closed_at", "last_evaluated_date", "entry_price",
        "mfe_r", "mae_r", "exit_price", "outcome_date",
        "level_adjustment_factor",
    }
    values = [(key, value) for key, value in changes.items() if key in allowed]
    if values:
        assignments = ", ".join(f"{key} = ?" for key, _value in values)
        with _conn() as c:
            row = c.execute(_sql(
                f"UPDATE recommendation_outcomes SET {assignments} "
                "WHERE id = ? RETURNING *"
            ), tuple(value for _key, value in values) + (outcome_id,)).fetchone()
    else:
        with _conn() as c:
            row = c.execute(_sql(
                "SELECT * FROM recommendation_outcomes WHERE id = ?"
            ), (outcome_id,)).fetchone()
    return _row_to_recommendation_outcome(row) if row else None


def recommendation_outcome_stats() -> dict:
    with _conn() as c:
        row = c.execute(_sql(
            "SELECT SUM(CASE WHEN tracking_role = 'actionable' THEN 1 ELSE 0 END) AS total, "
            "SUM(CASE WHEN tracking_role = 'observational' THEN 1 ELSE 0 END) AS observational, "
            "SUM(CASE WHEN tracking_role = 'actionable' AND status = 'ARMED' THEN 1 ELSE 0 END) AS armed, "
            "SUM(CASE WHEN tracking_role = 'actionable' AND status = 'ACTIVE' THEN 1 ELSE 0 END) AS active, "
            "SUM(CASE WHEN status IN ('WIN_T1','WIN_T2','STOPPED_OUT','TIME_STOP') "
            "AND tracking_role = 'actionable' THEN 1 ELSE 0 END) AS resolved, "
            "SUM(CASE WHEN tracking_role = 'observational' AND status IN "
            "('WIN_T1','WIN_T2','STOPPED_OUT','TIME_STOP') THEN 1 ELSE 0 END) AS observational_resolved, "
            "SUM(CASE WHEN tracking_role = 'actionable' AND status NOT IN ('ARMED','ACTIVE','WIN_T1','WIN_T2',"
            "'STOPPED_OUT','TIME_STOP') THEN 1 ELSE 0 END) AS excluded, "
            "SUM(CASE WHEN tracking_role = 'actionable' AND (status IN ('WIN_T1','WIN_T2') OR "
            "(status = 'TIME_STOP' AND pnl_r > 0)) THEN 1 ELSE 0 END) AS wins, "
            "COALESCE(SUM(CASE WHEN tracking_role = 'actionable' THEN pnl_r ELSE 0 END), 0) AS net_r, "
            "COALESCE(AVG(CASE WHEN tracking_role = 'actionable' AND status IN ('WIN_T1','WIN_T2','STOPPED_OUT',"
            "'TIME_STOP') THEN mfe_r END), 0) AS avg_mfe_r, "
            "COALESCE(AVG(CASE WHEN tracking_role = 'actionable' AND status IN ('WIN_T1','WIN_T2','STOPPED_OUT',"
            "'TIME_STOP') THEN mae_r END), 0) AS avg_mae_r "
            "FROM recommendation_outcomes"
        )).fetchone()
    resolved = int(row["resolved"] or 0)
    wins = int(row["wins"] or 0)
    net_r = float(row["net_r"] or 0)
    return {
        "total": int(row["total"] or 0),
        "observational": int(row["observational"] or 0),
        "observational_resolved": int(row["observational_resolved"] or 0),
        "armed": int(row["armed"] or 0),
        "active": int(row["active"] or 0),
        "resolved": resolved,
        "excluded": int(row["excluded"] or 0),
        "wins": wins,
        "win_rate_pct": round(wins / resolved * 100, 1) if resolved else 0.0,
        "net_r": round(net_r, 2),
        "expectancy_r": round(net_r / resolved, 2) if resolved else 0.0,
        "avg_mfe_r": round(float(row["avg_mfe_r"] or 0), 2),
        "avg_mae_r": round(float(row["avg_mae_r"] or 0), 2),
    }


def backtest_run_add(model_version: str, status: str, payload: dict) -> dict:
    run_id = uuid.uuid4().hex
    now = time.time()
    with _conn() as c:
        c.execute(_sql(
            "INSERT INTO backtest_runs(id, model_version, status, payload, created_at) "
            "VALUES (?,?,?,?,?)"
        ), (run_id, model_version, status,
            json.dumps(_json_nan_safe(payload)), now))
    return {"id": run_id, "model_version": model_version, "status": status,
            "created_at": now, **payload}


def _row_to_backtest_run(row) -> Optional[dict]:
    if not row:
        return None
    payload = _loads_payload(row["payload"], {})
    return {"id": row["id"], "model_version": row["model_version"],
            "status": row["status"], "created_at": float(row["created_at"]),
            **payload}


def latest_backtest_run(model_version: Optional[str] = None) -> Optional[dict]:
    params: tuple = ()
    where = ""
    if model_version:
        where = "WHERE model_version = ? "
        params = (model_version,)
    with _conn() as c:
        row = c.execute(_sql(
            f"SELECT * FROM backtest_runs {where}ORDER BY created_at DESC LIMIT 1"
        ), params).fetchone()
    return _row_to_backtest_run(row)


def backtest_runs(limit: int = 20) -> list[dict]:
    safe_limit = max(1, min(int(limit), 100))
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?"
        ), (safe_limit,)).fetchall()
    return [_row_to_backtest_run(row) for row in rows]


_ENRICHMENT_SEED_PATH = os.path.join(os.path.dirname(__file__), "seed", "bull_ai_enrichment.json")


def upsert_candidate_enrichment(symbol: str, provider: str, payload: dict, *,
                                version: str = "1", as_of: Optional[str] = None) -> None:
    """Store source-labelled external research without changing model scores."""
    now = time.time()
    with _conn() as c:
        c.execute(_sql(
            "INSERT INTO candidate_enrichments(symbol, provider, version, as_of, payload, refreshed_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(symbol, provider) DO UPDATE SET "
            "version=excluded.version, as_of=excluded.as_of, payload=excluded.payload, "
            "refreshed_at=excluded.refreshed_at"
        ), (symbol.upper(), provider, version, as_of,
            json.dumps(_json_nan_safe(payload)), now))


def candidate_enrichments(symbol: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT provider, version, as_of, payload, refreshed_at "
            "FROM candidate_enrichments WHERE symbol = ? ORDER BY provider"
        ), (symbol.upper(),)).fetchall()
    output = []
    for row in rows:
        payload = _loads_payload(row["payload"], {})
        payload.update({"provider": row["provider"], "version": row["version"],
                        "as_of": row["as_of"], "refreshed_at": row["refreshed_at"]})
        output.append(payload)
    return output


def enrichment_coverage(provider: str = "Bull AI") -> dict:
    with _conn() as c:
        row = c.execute(_sql(
            "SELECT COUNT(*) AS total, MAX(refreshed_at) AS latest "
            "FROM candidate_enrichments WHERE provider = ?"
        ), (provider,)).fetchone()
    return {"provider": provider, "covered": int(row["total"] or 0),
            "latest_refresh": row["latest"]}


def _seed_candidate_enrichments() -> None:
    """Install the bounded, source-backed pilot evidence once per database."""
    if not os.path.exists(_ENRICHMENT_SEED_PATH):
        return
    try:
        with open(_ENRICHMENT_SEED_PATH, encoding="utf-8") as handle:
            items = json.load(handle)
        with _conn() as c:
            for item in items:
                c.execute(_sql(
                    "INSERT INTO candidate_enrichments(symbol, provider, version, as_of, payload, refreshed_at) "
                    "VALUES (?,?,?,?,?,?) ON CONFLICT(symbol, provider) DO NOTHING"
                ), (item["symbol"].upper(), item.get("provider", "Bull AI"),
                    item.get("version", "1"), item.get("as_of"),
                    json.dumps(_json_nan_safe(item["payload"])), time.time()))
    except (OSError, ValueError, KeyError) as exc:
        print(f"[db] Bull AI enrichment seed skipped: {exc}")


def sector_snapshot(sector: str, snapshot_id: Optional[str] = None) -> Optional[dict]:
    if not snapshot_id:
        latest = latest_analysis_snapshot()
        snapshot_id = latest.get("snapshot_id") if latest else None
    if not snapshot_id:
        return None
    with _conn() as c:
        row = c.execute(
            _sql("SELECT payload FROM sector_snapshots WHERE snapshot_id = ? "
                 "AND lower(sector) = lower(?)"),
            (snapshot_id, sector),
        ).fetchone()
    return _loads_payload(row["payload"], {}) if row else None


DEFAULT_PORTFOLIO_SETTINGS = {
    "risk_per_trade_pct": 0.75,
    "max_portfolio_heat_pct": 6.0,
    "max_open_positions": 8,
    "max_positions_per_sector": 2,
    "max_sector_exposure_pct": 25.0,
    "minimum_reward_risk": 1.5,
    "t1_r": 1.5,
    "t2_r": 2.5,
    "time_stop_sessions": 40,
}


def portfolio_settings() -> dict:
    value = get_setting("portfolio_settings_v1", {})
    stored = value if isinstance(value, dict) else {}
    # Return only active policy fields; legacy account-value sizing settings
    # are intentionally ignored after position sizing was removed.
    return {key: stored.get(key, default) for key, default in DEFAULT_PORTFOLIO_SETTINGS.items()}


def set_portfolio_settings(value: dict) -> dict:
    merged = {**portfolio_settings(), **value}
    set_setting("portfolio_settings_v1", merged)
    return merged


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


# ── immutable research archive ───────────────────────────────────────────────

def _stable_payload(value: Any) -> tuple[str, str]:
    encoded = json.dumps(
        _json_nan_safe(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    )
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _security_id(symbol: str, isin: Optional[str] = None) -> str:
    clean_isin = str(isin or "").strip().upper()
    return f"IN:{clean_isin}" if clean_isin else f"NSE:{str(symbol).strip().upper()}"


def _executemany(connection, query: str, values: list[tuple]) -> None:
    if not values:
        return
    cursor = connection.cursor()
    try:
        cursor.executemany(_sql(query), values)
    finally:
        cursor.close()


def archive_security_master(rows: list[dict], observed_at: Optional[float] = None) -> dict:
    """Upsert current identity while retaining a stable ISIN-based key."""
    now = float(observed_at or time.time())
    values = []
    for row in rows:
        symbol = str(row.get("symbol") or row.get("nse_symbol") or "").strip().upper()
        name = str(row.get("name") or row.get("company_name") or symbol).strip()
        if not symbol or not name:
            continue
        isin = str(row.get("isin") or "").strip().upper() or None
        values.append((
            _security_id(symbol, isin), symbol, row.get("bse_code"), isin, name,
            row.get("sector"), row.get("industry"),
            _as_finite_float(row.get("market_cap_cr")), row.get("listing_date"),
            1 if row.get("fno_flag") else 0, 1, now, now,
        ))
    query = (
        "INSERT INTO securities(security_id,nse_symbol,bse_code,isin,company_name,"
        "sector,industry,market_cap_cr,listing_date,fno_flag,active_flag,first_seen_at,last_seen_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(security_id) DO UPDATE SET "
        "nse_symbol=excluded.nse_symbol, bse_code=COALESCE(excluded.bse_code,securities.bse_code), "
        "company_name=excluded.company_name, sector=COALESCE(excluded.sector,securities.sector), "
        "industry=COALESCE(excluded.industry,securities.industry), "
        "market_cap_cr=COALESCE(excluded.market_cap_cr,securities.market_cap_cr), "
        "listing_date=COALESCE(excluded.listing_date,securities.listing_date), "
        "fno_flag=excluded.fno_flag, active_flag=1, last_seen_at=excluded.last_seen_at"
    )
    with _conn() as connection:
        _executemany(connection, query, values)
    return {"attempted": len(values), "observed_at": now}


def enrich_security_master(candidates: list[dict]) -> int:
    values = [(
        candidate.get("sector"), candidate.get("industry"),
        _as_finite_float(candidate.get("market_cap_cr")),
        str(candidate.get("symbol") or "").upper(),
    ) for candidate in candidates if candidate.get("symbol")]
    with _conn() as connection:
        _executemany(
            connection,
            "UPDATE securities SET sector=COALESCE(?,sector), industry=COALESCE(?,industry), "
            "market_cap_cr=COALESCE(?,market_cap_cr) WHERE nse_symbol=?",
            values,
        )
    return len(values)


def archive_raw_market_day(universe: list[dict], bars: dict[str, dict], *,
                           trading_date: str, source_url: Optional[str] = None,
                           observed_at: Optional[float] = None) -> dict:
    now = float(observed_at or time.time())
    identity = {str(row.get("symbol") or "").upper(): row for row in universe}
    values = []
    for symbol, bar in bars.items():
        security = identity.get(str(symbol).upper())
        if not security:
            continue
        payload = {
            key: bar.get(key) for key in (
                "open", "high", "low", "close", "volume",
                "delivery_volume", "turnover",
            )
        }
        _encoded, revision = _stable_payload(payload)
        values.append((
            _security_id(symbol, security.get("isin")), str(trading_date)[:10],
            "NSE bhavcopy", revision, _as_finite_float(bar.get("open")),
            _as_finite_float(bar.get("high")), _as_finite_float(bar.get("low")),
            _as_finite_float(bar.get("close")), _as_finite_float(bar.get("volume")),
            _as_finite_float(bar.get("delivery_volume")),
            _as_finite_float(bar.get("turnover")), source_url, now,
        ))
    with _conn() as connection:
        _executemany(
            connection,
            "INSERT INTO market_prices_raw(security_id,trading_date,provider,revision_hash,"
            "open_price,high_price,low_price,close_price,volume,delivery_volume,turnover,"
            "source_url,observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            values,
        )
    return {"attempted": len(values), "trading_date": str(trading_date)[:10]}


def archive_adjusted_histories(histories: dict[str, list[dict]], *,
                               observed_at: Optional[float] = None,
                               isin_by_symbol: Optional[dict[str, str]] = None) -> dict:
    """Append new Yahoo revisions; unchanged candles are deduplicated by hash."""
    now = float(observed_at or time.time())
    isin_by_symbol = isin_by_symbol or {}
    price_values: list[tuple] = []
    action_values: list[tuple] = []
    for raw_symbol, candles in histories.items():
        symbol = str(raw_symbol).replace("NSE:", "").replace(".NS", "").upper()
        security_id = _security_id(symbol, isin_by_symbol.get(symbol))
        yahoo_rows = [row for row in candles if row.get("source") != "NSE bhavcopy"]
        yahoo_rows.sort(key=lambda row: str(row.get("date") or ""))
        previous_factor = None
        for bar in yahoo_rows:
            trading_date = str(bar.get("date") or "")[:10]
            if not trading_date:
                continue
            payload = {key: bar.get(key) for key in (
                "open", "high", "low", "close", "raw_close",
                "adjustment_factor", "volume",
            )}
            _encoded, revision = _stable_payload(payload)
            factor = _as_finite_float(bar.get("adjustment_factor"))
            price_values.append((
                security_id, trading_date, "Yahoo adjusted daily", revision,
                _as_finite_float(bar.get("open")), _as_finite_float(bar.get("high")),
                _as_finite_float(bar.get("low")), _as_finite_float(bar.get("close")),
                _as_finite_float(bar.get("raw_close")), factor,
                _as_finite_float(bar.get("volume")), now,
            ))
            if (previous_factor and factor and previous_factor > 0
                    and abs(factor / previous_factor - 1) > 1e-7):
                evidence = {
                    "previous_factor": previous_factor, "factor": factor,
                    "effective_date": trading_date,
                }
                _action_json, evidence_hash = _stable_payload(evidence)
                action_values.append((
                    hashlib.sha256(f"{security_id}|{trading_date}|{evidence_hash}".encode()).hexdigest(),
                    security_id, trading_date, "adjustment_factor_change",
                    factor / previous_factor, "Yahoo adjusted daily", evidence_hash, now,
                ))
            if factor and factor > 0:
                previous_factor = factor
    with _conn() as connection:
        _executemany(
            connection,
            "INSERT INTO market_prices_adjusted(security_id,trading_date,provider,revision_hash,"
            "open_price,high_price,low_price,adjusted_close,raw_close,adjustment_factor,volume,observed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            price_values,
        )
        _executemany(
            connection,
            "INSERT INTO corporate_actions(id,security_id,effective_date,action_type,"
            "adjustment_ratio,source,evidence_hash,detected_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT DO NOTHING",
            action_values,
        )
    return {"price_rows_attempted": len(price_values),
            "actions_detected": len(action_values)}


def archive_feature_snapshots(items: list[dict], *, feature_date: str,
                              feature_version: str, feature_scope: str,
                              observed_at: Optional[float] = None,
                              isin_by_symbol: Optional[dict[str, str]] = None) -> int:
    now = float(observed_at or time.time())
    isin_by_symbol = isin_by_symbol or {}
    values = []
    for item in items:
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        encoded, revision = _stable_payload(item)
        values.append((
            _security_id(symbol, isin_by_symbol.get(symbol)), str(feature_date)[:10],
            feature_version, feature_scope, revision, encoded, now,
        ))
    with _conn() as connection:
        _executemany(
            connection,
            "INSERT INTO stock_feature_snapshots(security_id,feature_date,feature_version,"
            "feature_scope,revision_hash,payload,observed_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT DO NOTHING",
            values,
        )
    return len(values)


def archive_financial_payloads(items: list[dict]) -> dict:
    """Normalize observed financial statements/events without inventing filing dates."""
    report_values: list[tuple] = []
    event_values: list[tuple] = []
    statement_keys = {
        "quarterly_results": "quarterly_income",
        "annual_pl": "annual_income",
        "annual_bs": "annual_balance_sheet",
        "annual_cf": "annual_cash_flow",
    }
    ratio_keys = (
        "roe", "roce", "debt_to_equity", "interest_coverage", "market_cap",
        "promoter_pledge",
    )
    for item in items:
        symbol = str(item.get("symbol") or "").upper()
        payload = item.get("payload") or {}
        if not symbol or not payload:
            continue
        security_id = _security_id(symbol, item.get("isin"))
        observed_at = float(item.get("observed_at") or time.time())
        origin = item.get("origin") or payload.get("fundamentals_source")
        for key, statement_type in statement_keys.items():
            for index, period in enumerate(payload.get(key) or []):
                if not isinstance(period, dict):
                    continue
                period_label = str(
                    period.get("quarter") or period.get("year")
                    or period.get("period") or f"row-{index}"
                )
                encoded, payload_hash = _stable_payload(period)
                filing_date = period.get("filing_date") or period.get("published_at")
                source_document = period.get("source_document") or period.get("source_url")
                report_id = hashlib.sha256(
                    f"{security_id}|{statement_type}|{period_label}|{payload_hash}".encode()
                ).hexdigest()
                report_values.append((
                    report_id, security_id, symbol, statement_type, period_label,
                    str(filing_date) if filing_date else None, observed_at, origin,
                    str(source_document) if source_document else None, payload_hash, encoded,
                ))
        ratios = {key: payload.get(key) for key in ratio_keys if payload.get(key) is not None}
        if ratios:
            encoded, payload_hash = _stable_payload(ratios)
            report_values.append((
                hashlib.sha256(f"{security_id}|ratios|{payload_hash}".encode()).hexdigest(),
                security_id, symbol, "ratios", "current_as_observed", None,
                observed_at, origin, None, payload_hash, encoded,
            ))
        source_events = payload.get("events") or []
        events = [source_events] if isinstance(source_events, dict) else list(source_events)
        if payload.get("earnings_date"):
            events.append({
                "event_type": "earnings", "event_date": payload["earnings_date"],
                "severity": "scheduled", "description": "Scheduled financial results",
                "source": origin,
            })
        for event in events:
            if not isinstance(event, dict):
                continue
            normalized = {
                "event_type": event.get("event_type") or event.get("type") or "company_event",
                "event_date": event.get("event_date") or event.get("date"),
                "filing_date": event.get("filing_date"),
                "severity": event.get("severity"),
                "description": event.get("description") or event.get("summary"),
                "source": event.get("source") or origin,
                "source_url": event.get("source_url") or event.get("url"),
            }
            _event_json, evidence_hash = _stable_payload(normalized)
            event_values.append((
                hashlib.sha256(f"{security_id}|{evidence_hash}".encode()).hexdigest(),
                security_id, symbol, normalized["event_type"], normalized["event_date"],
                normalized["filing_date"], normalized["severity"],
                normalized["description"], normalized["source"], normalized["source_url"],
                evidence_hash, observed_at,
            ))
    with _conn() as connection:
        _executemany(
            connection,
            "INSERT INTO financial_reports(id,security_id,symbol,statement_type,period_label,"
            "filing_date,observed_at,source,source_document,payload_hash,payload) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            report_values,
        )
        _executemany(
            connection,
            "INSERT INTO company_events(id,security_id,symbol,event_type,event_date,filing_date,"
            "severity,description,source,source_url,evidence_hash,observed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            event_values,
        )
    return {"reports_attempted": len(report_values), "events_attempted": len(event_values)}


def data_archive_status() -> dict:
    tables = (
        "securities", "market_prices_raw", "market_prices_adjusted",
        "corporate_actions", "financial_reports", "company_events",
        "stock_feature_snapshots",
    )
    with _conn() as connection:
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
            for table in tables
        }
        latest_raw = connection.execute(
            "SELECT MAX(trading_date) AS value FROM market_prices_raw"
        ).fetchone()["value"]
        latest_features = connection.execute(
            "SELECT MAX(feature_date) AS value FROM stock_feature_snapshots"
        ).fetchone()["value"]
    return {"counts": counts, "latest_raw_date": latest_raw,
            "latest_feature_date": latest_features, "immutable_revisions": True}


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

_NUMERIC_TRADE_FIELDS = ("entry_price", "entry_low", "entry_high", "stop_loss",
                          "target_t1", "target_t2", "score", "pnl_r",
                          "activated_at", "closed_at", "mfe_r", "mae_r",
                          "exit_price")


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
                        setup_type: Optional[str] = None, *, status: str = "ACTIVE",
                        entry_low: Optional[float] = None,
                        entry_high: Optional[float] = None,
                        signal_date: Optional[str] = None,
                        snapshot_id: Optional[str] = None,
                        model_version: Optional[str] = None,
                        action_at_add: Optional[str] = None,
                        invalidation: Optional[str] = None,
                        note: Optional[str] = None) -> dict:
    """Log a new forward-test trade; returns the created record (with id)."""
    with _conn() as c:
        r = c.execute(
            _sql("INSERT INTO paper_trades"
                 "(symbol, entry_price, stop_loss, target_t1, target_t2, score, setup_type, "
                 "status, entry_low, entry_high, signal_date, snapshot_id, model_version, "
                 "action_at_add, invalidation, note) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING *"),
            (symbol.upper(), entry_price, stop_loss, target_t1, target_t2,
             score, setup_type, status, entry_low, entry_high, signal_date,
             snapshot_id, model_version, action_at_add, invalidation, note),
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


def paper_trades_open() -> list:
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT * FROM paper_trades WHERE status IN ('ARMED','ACTIVE') ORDER BY id"
        )).fetchall()
    return [_row_to_trade(r) for r in rows]


def paper_trade_get(trade_id: int) -> Optional[dict]:
    with _conn() as c:
        row = c.execute(_sql("SELECT * FROM paper_trades WHERE id = ?"), (trade_id,)).fetchone()
    return _row_to_trade(row) if row else None


def paper_trade_open_for_symbol(symbol: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute(_sql(
            "SELECT * FROM paper_trades WHERE symbol = ? AND status IN ('ARMED','ACTIVE') "
            "ORDER BY id DESC LIMIT 1"
        ), (symbol.upper(),)).fetchone()
    return _row_to_trade(row) if row else None


def paper_trade_patch(trade_id: int, **changes) -> Optional[dict]:
    allowed = {"status", "pnl_r", "note", "armed_sessions", "active_sessions",
               "activated_at", "closed_at", "last_evaluated_date", "entry_price",
               "mfe_r", "mae_r", "exit_price", "outcome_date"}
    values = [(key, value) for key, value in changes.items() if key in allowed]
    if not values:
        return paper_trade_get(trade_id)
    assignments = ", ".join(f"{key} = ?" for key, _value in values)
    with _conn() as c:
        c.execute(_sql(f"UPDATE paper_trades SET {assignments} WHERE id = ?"),
                  tuple(value for _key, value in values) + (trade_id,))
    return paper_trade_get(trade_id)


def paper_trade_update_status(trade_id: int, status: str, pnl_r: float) -> bool:
    with _conn() as c:
        cur = c.execute(
            _sql("UPDATE paper_trades SET status = ?, pnl_r = ?, closed_at = ? WHERE id = ?"),
            (status, pnl_r, time.time(), trade_id),
        )
        return cur.rowcount > 0


_PAPER_STATS_SQL = (
    "SELECT COUNT(*) AS total_trades, "
    "SUM(CASE WHEN status IN ('WIN_T1','WIN_T2') OR "
    " (status = 'TIME_STOP' AND pnl_r > 0) THEN 1 ELSE 0 END) AS wins, "
    "SUM(CASE WHEN status = 'STOPPED_OUT' OR "
    " (status = 'TIME_STOP' AND pnl_r < 0) THEN 1 ELSE 0 END) AS losses, "
    "SUM(CASE WHEN status = 'TIME_STOP' AND pnl_r = 0 THEN 1 ELSE 0 END) AS breakeven, "
    "SUM(CASE WHEN status IN ('WIN_T1','WIN_T2','STOPPED_OUT','TIME_STOP') "
    " THEN 1 ELSE 0 END) AS resolved_count, "
    "SUM(CASE WHEN status NOT IN ('ARMED','ACTIVE') THEN 1 ELSE 0 END) AS terminal_count, "
    "SUM(CASE WHEN status = 'EXPIRED' THEN 1 ELSE 0 END) AS expired_count, "
    "SUM(CASE WHEN status = 'AMBIGUOUS' THEN 1 ELSE 0 END) AS ambiguous_count, "
    "SUM(CASE WHEN status = 'INVALIDATED' THEN 1 ELSE 0 END) AS invalidated_count, "
    "SUM(CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END) AS active_count, "
    "SUM(CASE WHEN status = 'ARMED' THEN 1 ELSE 0 END) AS armed_count, "
    "COALESCE(SUM(pnl_r), 0) AS net_pnl_r, "
    "COALESCE(SUM(CASE WHEN pnl_r > 0 THEN pnl_r ELSE 0 END), 0) AS gross_profit_r, "
    "COALESCE(SUM(CASE WHEN pnl_r < 0 THEN -pnl_r ELSE 0 END), 0) AS gross_loss_r "
    "FROM paper_trades"
)


def _paper_stats(row) -> dict:
    wins = int(row["wins"] or 0)
    losses = int(row["losses"] or 0)
    breakeven = int(row["breakeven"] or 0)
    resolved = int(row["resolved_count"] or 0)
    net_r = float(row["net_pnl_r"] or 0.0)
    gross_profit = float(row["gross_profit_r"] or 0.0)
    gross_loss = float(row["gross_loss_r"] or 0.0)
    terminal = int(row["terminal_count"] or 0)
    return {
        "total_trades": int(row["total_trades"] or 0),
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "resolved_count": resolved,
        "terminal_count": terminal,
        "excluded_count": max(0, terminal - resolved),
        "expired_count": int(row["expired_count"] or 0),
        "ambiguous_count": int(row["ambiguous_count"] or 0),
        "invalidated_count": int(row["invalidated_count"] or 0),
        "win_rate_pct": round(wins / resolved * 100, 1) if resolved else 0.0,
        "net_pnl_r": round(net_r, 2),
        "expectancy_r": round(net_r / resolved, 2) if resolved else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else None,
        "active_count": int(row["active_count"] or 0),
        "armed_count": int(row["armed_count"] or 0),
    }


def paper_trades_stats() -> dict:
    """Aggregate every outcome class without treating exclusions as losses."""
    with _conn() as c:
        row = c.execute(_sql(_PAPER_STATS_SQL)).fetchone()
    return _paper_stats(row)


def paper_trades_snapshot(limit: int = 100) -> dict:
    """Return scorecard and recent log using one pooled connection checkout."""
    safe_limit = max(1, min(int(limit), 500))
    with _conn() as c:
        rows = c.execute(_sql(
            "SELECT * FROM paper_trades ORDER BY id DESC LIMIT ?"
        ), (safe_limit,)).fetchall()
        aggregate = c.execute(_sql(_PAPER_STATS_SQL)).fetchone()
    return {"stats": _paper_stats(aggregate), "trades": [_row_to_trade(r) for r in rows]}


# Schema is created on import so any entry point gets a working DB.
_initialize_with_fallback()
