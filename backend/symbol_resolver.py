"""
symbol_resolver.py
Resolve free-text company names ("Aegis Logistics Ltd") to NSE symbols.

Primary source: NSE's official equity master list (EQUITY_L.csv, ~2400 rows),
cached locally in data/nse_equity.json and refreshed weekly. Name matching is
token-based (suffixes like Ltd/Limited stripped, "&" == "and"), so pasted
names from brokers/news resolve without exact spelling.

Fallback for names not in the cached list (fresh IPOs, renames):
screener.in's company-search API, whose result URL slug is the NSE symbol.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from typing import Optional

import httpx

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
CACHE_FILE = os.path.join(DATA_DIR, "nse_equity.json")
CACHE_MAX_AGE = 7 * 24 * 3600   # refresh weekly

NSE_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
SCREENER_SEARCH_URL = "https://www.screener.in/api/company/search/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
}

# Corporate suffixes that carry no matching signal
_DROP_TOKENS = {"ltd", "limited"}

_directory: Optional[list] = None   # [{"symbol", "name", "tokens": set}]


def _normalize_tokens(name: str) -> set:
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return {t for t in s.split() if t and t not in _DROP_TOKENS}


# ── NSE directory cache ───────────────────────────────────────────────────────

async def _download_nse_list() -> list:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(NSE_EQUITY_URL, headers=HEADERS)
        r.raise_for_status()
    rows = []
    reader = csv.DictReader(io.StringIO(r.text))
    for row in reader:
        sym = (row.get("SYMBOL") or "").strip()
        name = (row.get("NAME OF COMPANY") or "").strip()
        if sym and name:
            rows.append({"symbol": sym, "name": name})
    return rows


async def _load_directory() -> list:
    """Cached NSE symbol/name directory with precomputed match tokens."""
    global _directory
    if _directory is not None:
        return _directory

    rows = None
    if os.path.exists(CACHE_FILE):
        try:
            cached = json.load(open(CACHE_FILE, encoding="utf-8"))
            if time.time() - cached.get("fetched_at", 0) < CACHE_MAX_AGE:
                rows = cached["rows"]
        except Exception:
            pass

    if rows is None:
        try:
            rows = await _download_nse_list()
            json.dump({"fetched_at": time.time(), "rows": rows},
                      open(CACHE_FILE, "w", encoding="utf-8"))
        except Exception as e:
            print(f"[resolver] NSE list download failed: {e}")
            # Fall back to a stale cache rather than nothing
            if os.path.exists(CACHE_FILE):
                try:
                    rows = json.load(open(CACHE_FILE, encoding="utf-8"))["rows"]
                except Exception:
                    rows = []
            else:
                rows = []

    _directory = [{**r, "tokens": _normalize_tokens(r["name"])} for r in rows]
    return _directory


# ── matching ──────────────────────────────────────────────────────────────────

def _best_match(query: str, directory: list) -> Optional[dict]:
    """Token-overlap match. Returns {"symbol", "name", "score"} or None."""
    qt = _normalize_tokens(query)
    if not qt:
        return None
    best, best_score = None, 0.0
    for row in directory:
        nt = row["tokens"]
        inter = qt & nt
        if not inter:
            continue
        recall = len(inter) / len(qt)        # query tokens found in name
        precision = len(inter) / len(nt)     # extra name tokens penalized
        score = 100 * (0.7 * recall + 0.3 * precision)
        # All query tokens present is a strong signal even with extra words
        if recall == 1.0:
            score = max(score, 85.0)
        if score > best_score:
            best, best_score = row, score
    if best and best_score >= 75:
        return {"symbol": best["symbol"], "name": best["name"],
                "score": round(best_score, 1)}
    return None


async def _screener_fallback(query: str) -> Optional[dict]:
    """screener.in company search; the URL slug is the NSE symbol."""
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(SCREENER_SEARCH_URL, params={"q": query}, headers=HEADERS)
            r.raise_for_status()
            results = r.json()
        for item in results:
            m = re.match(r"^/company/([A-Z0-9&-]+)/", item.get("url", ""))
            # Numeric slugs are BSE scrip codes, not NSE symbols — skip those
            if m and not m.group(1).isdigit():
                return {"symbol": m.group(1), "name": item.get("name", query),
                        "score": None}
    except Exception as e:
        print(f"[resolver] screener fallback failed for {query!r}: {e}")
    return None


# ── public API ────────────────────────────────────────────────────────────────

def _looks_like_symbol(q: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9.&-]{1,20}", q.strip()))


async def resolve_one(query: str) -> dict:
    """
    Resolve one free-text query (symbol or company name) to an NSE symbol.
    Returns {"query", "symbol"|None, "name", "exchange", "method"}.
    """
    q = query.strip()
    out = {"query": q, "symbol": None, "name": None, "exchange": "NSE", "method": None}
    if not q:
        return out

    directory = await _load_directory()
    by_symbol = {r["symbol"].upper(): r for r in directory}

    # 1. Exact symbol
    if _looks_like_symbol(q) and q.upper() in by_symbol:
        r = by_symbol[q.upper()]
        return {**out, "symbol": r["symbol"], "name": r["name"], "method": "symbol"}

    # 2. Name match against the NSE directory
    m = _best_match(q, directory)
    if m:
        return {**out, "symbol": m["symbol"], "name": m["name"], "method": "name_match"}

    # 3. screener.in fallback (fresh IPOs / renames not yet matched)
    m = await _screener_fallback(q)
    if m:
        return {**out, "symbol": m["symbol"], "name": m["name"], "method": "screener"}

    # 4. Symbol-shaped input passes through unvalidated (e.g. BSE-only tickers)
    if _looks_like_symbol(q):
        return {**out, "symbol": q.upper(), "name": q.upper(), "method": "passthrough"}

    return out


async def resolve_many(queries: list) -> list:
    return [await resolve_one(q) for q in queries]


async def search_local(q: str, limit: int = 8) -> list:
    """
    Fast name/symbol search over the cached NSE directory, for autocomplete.
    Returns [{"symbol", "name", "exchange"}] ranked by match quality.
    """
    directory = await _load_directory()
    qn = q.strip().lower()
    if not qn:
        return []
    qt = _normalize_tokens(q)
    scored = []
    for row in directory:
        sym_l = row["symbol"].lower()
        name_l = row["name"].lower()
        if sym_l.startswith(qn):
            scored.append((0, len(sym_l), row))          # symbol prefix: best
        elif name_l.startswith(qn):
            scored.append((1, len(name_l), row))         # name prefix
        elif qt and qt <= row["tokens"]:
            scored.append((2, len(row["tokens"]), row))  # all tokens present
        elif qn in name_l:
            scored.append((3, len(name_l), row))         # substring
    scored.sort(key=lambda t: (t[0], t[1]))
    return [{"symbol": r["symbol"], "name": r["name"], "exchange": "NSE"}
            for _, _, r in scored[:limit]]
