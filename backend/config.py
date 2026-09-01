"""
config.py
Central environment/configuration loading for the StockLens backend.

Import this module FIRST (main.py does) — it loads .env files before any
other module reads environment variables. Never hardcode secrets; put them
in the repo-root .env (gitignored, template in .env.example).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# backend/ directory and repo root
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BACKEND_DIR)

# Load .env from the repo root first, then backend/ (later loads do NOT
# override already-set variables, so real environment vars win).
load_dotenv(os.path.join(REPO_ROOT, ".env"))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

# ── Secrets / API keys ────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Shared secret gating POST /api/auto-screen (the all-NSE daily market scan).
# Unset by default -> the endpoint refuses every request until an operator
# configures a real secret (an empty secret must never be "valid").
CRON_SECRET_KEY: str = os.environ.get("CRON_SECRET_KEY", "")
GITHUB_OIDC_AUDIENCE: str = os.environ.get("GITHUB_OIDC_AUDIENCE", "stocklens-daily")
GITHUB_OIDC_REPOSITORY: str = os.environ.get(
    "GITHUB_OIDC_REPOSITORY", "AjayKhalsa/stock-research"
)
CFO_WORKSPACE_V1: bool = os.environ.get("CFO_WORKSPACE_V1", "true").strip().lower() in {
    "1", "true", "yes", "on",
}
DEFAULT_CHARTINK_URL: str = os.environ.get(
    "CHARTINK_SCREENER_URL",
    "https://chartink.com/screener/copy-general-scanner-simply-above-mas-3",
)

# ── Paths ─────────────────────────────────────────────────────────────────────
# Where durable state lives (SQLite DB: watchlist, saved screens, alerts,
# fundamentals cache). Overridable via STOCKLENS_DATA_DIR so a deploy can point
# it at a persistent disk mount — on ephemeral hosts (e.g. Render's free plan)
# the default backend/data path is wiped on every restart, taking the
# watchlist and saved screens with it. Defaults to backend/data for local dev.
DATA_DIR = os.path.abspath(os.path.expanduser(
    os.environ.get("STOCKLENS_DATA_DIR", os.path.join(BACKEND_DIR, "data"))
))
os.makedirs(DATA_DIR, exist_ok=True)
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")

# ── Scraping ──────────────────────────────────────────────────────────────────
SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
