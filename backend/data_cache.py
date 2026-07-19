"""
data_cache.py — per-symbol TTL cache for the merged fundamentals payload
(Screener.in scrape + yfinance reported-statement overlay).

Read path for every consumer (/stock, /plan, /alpha, screen-stream):

    fundamentals, meta = await get_fundamentals(symbol)

  1. Cache hit under TTL (default 4h)  → served instantly from SQLite.
  2. Stale/missing                     → live fetch, parsed, cache updated.
  3. Live fetch FAILS but a stale copy exists → serve the stale copy,
     flagged — a broken scraper or rate limit degrades to last-known-good
     numbers instead of empty scores.

`meta` is the structured freshness record the frontend renders:
    {source, origin, fetched_at, age_minutes, ttl_hours, stale}
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional, Tuple

import db
import price_service as price
from screener_scraper import fetch_screener_full

import re

# Fields where yfinance's *reported* statement value is more trustworthy than
# Screener's scraped/proxied one. Overlaid onto the matching year's entry.
_YF_BS_OVERLAY = ["total_assets", "current_assets", "current_liabilities",
                  "borrowings", "reserves", "equity_capital", "fixed_assets",
                  "total_equity"]
_YF_PL_OVERLAY = ["revenue", "net_profit", "ebitda", "ebit", "profit_before_tax",
                  "interest", "depreciation"]
_YF_CF_OVERLAY = ["cfo", "cfi", "cff"]


def _year_of(label) -> Optional[int]:
    """Extract a 4-digit year from a Screener period label like 'Mar 2024'."""
    if not label:
        return None
    m = re.search(r"(19|20)\d{2}", str(label))
    return int(m.group(0)) if m else None


def _overlay_years(entries: list, by_year: dict, keys: list) -> int:
    """
    Overlay reported yfinance values onto Screener annual entries, matching on
    calendar year. yfinance wins for the listed keys when it has a value.
    Returns the number of entries that received at least one overlaid field.
    """
    touched = 0
    for entry in entries:
        yr = _year_of(entry.get("year"))
        if yr is None:
            continue
        yf_row = by_year.get(yr)
        if not yf_row:
            continue
        hit = False
        for k in keys:
            v = yf_row.get(k)
            if v is not None:
                entry[k] = v
                hit = True
        if hit:
            touched += 1
    return touched


def enrich_with_yf_fundamentals(screener_data: dict, yf_funds: dict) -> dict:
    """
    Overlay yfinance's reported financial statements onto the Screener annual
    data in-place. This replaces Screener's 'Other Assets'/'Other Liabilities'
    proxies with true current assets/liabilities and adds a reported EBIT and
    total book equity — the inputs Altman/Piotroski/Beneish/DuPont depend on.
    Screener remains the fallback for any year/field yfinance doesn't cover.
    """
    if not screener_data or not yf_funds:
        return screener_data

    # Sector/industry classification rides along with the statements
    for k in ("sector", "industry"):
        if yf_funds.get(k):
            screener_data[k] = yf_funds[k]

    bs_by = yf_funds.get("bs_by_year") or {}
    pl_by = yf_funds.get("pl_by_year") or {}
    cf_by = yf_funds.get("cf_by_year") or {}
    if not (bs_by or pl_by or cf_by):
        return screener_data

    pl = screener_data.get("annual_pl") or []
    bs = screener_data.get("annual_bs") or []
    cf = screener_data.get("annual_cf") or []

    # If Screener had no annual tables at all, seed lists from yfinance years.
    if not bs and bs_by:
        bs = [{"year": str(y)} for y in sorted(bs_by)]
        screener_data["annual_bs"] = bs
    if not pl and pl_by:
        pl = [{"year": str(y)} for y in sorted(pl_by)]
        screener_data["annual_pl"] = pl
    if not cf and cf_by:
        cf = [{"year": str(y)} for y in sorted(cf_by)]
        screener_data["annual_cf"] = cf

    n = 0
    n += _overlay_years(bs, bs_by, _YF_BS_OVERLAY)
    n += _overlay_years(pl, pl_by, _YF_PL_OVERLAY)
    n += _overlay_years(cf, cf_by, _YF_CF_OVERLAY)

    screener_data["fundamentals_source"] = (
        "yfinance+screener" if n else "screener"
    )
    return screener_data


TTL_HOURS_DEFAULT = 4.0

# Single-flight: if three concurrent requests miss on the same symbol,
# only one hits the network; the rest await the same fetch.
_inflight: dict = {}


def _meta(source: str, origin: Optional[str], fetched_at: float,
          ttl_hours: float, stale: bool) -> dict:
    return {
        "source": source,                      # cache | live | stale_cache
        "origin": origin or "unavailable",     # yfinance+screener | screener
        "fetched_at": fetched_at,
        "age_minutes": round(max(0.0, time.time() - fetched_at) / 60, 1),
        "ttl_hours": ttl_hours,
        "stale": stale,
    }


async def _fetch_live(symbol: str, exchange: str) -> Tuple[dict, str]:
    """Scrape + yfinance statements, merged. Returns (payload, origin)."""
    instrument = f"{exchange}:{symbol}"
    screener_data, yf_funds = await asyncio.gather(
        fetch_screener_full(symbol),
        price.get_fundamentals(instrument),
    )
    merged = enrich_with_yf_fundamentals(screener_data, yf_funds)
    origin = (merged or {}).get("fundamentals_source", "screener")
    return merged or {}, origin


async def get_fundamentals(symbol: str, exchange: str = "NSE",
                           ttl_hours: Optional[float] = None) -> Tuple[dict, dict]:
    """
    Cached fundamentals for one symbol. Returns (payload, meta).
    payload may be {} when nothing was ever fetchable — callers already
    degrade gracefully on empty fundamentals.
    """
    symbol = symbol.upper().strip()
    ttl = ttl_hours if ttl_hours is not None else \
        float(db.get_setting("fundamentals_ttl_hours", TTL_HOURS_DEFAULT))

    cached = db.cache_get(symbol)
    if cached and cached["payload"] and cached["age_seconds"] < ttl * 3600:
        return cached["payload"], _meta("cache", cached["origin"],
                                        cached["fetched_at"], ttl, stale=False)

    # Single-flight the live fetch per symbol
    if symbol in _inflight:
        await _inflight[symbol].wait()
        fresh = db.cache_get(symbol)
        if fresh and fresh["payload"]:
            stale = fresh["age_seconds"] >= ttl * 3600
            return fresh["payload"], _meta("stale_cache" if stale else "cache",
                                           fresh["origin"], fresh["fetched_at"],
                                           ttl, stale=stale)
        return {}, _meta("live", None, time.time(), ttl, stale=False)

    event = asyncio.Event()
    _inflight[symbol] = event
    try:
        payload, origin = await _fetch_live(symbol, exchange)
        if payload:
            db.cache_put(symbol, exchange, payload, origin)
            return payload, _meta("live", origin, time.time(), ttl, stale=False)
        # Live fetch returned nothing (scraper broken / rate-limited):
        # fall back to the stale copy if one exists.
        if cached and cached["payload"]:
            return cached["payload"], _meta("stale_cache", cached["origin"],
                                            cached["fetched_at"], ttl, stale=True)
        return {}, _meta("live", None, time.time(), ttl, stale=False)
    finally:
        event.set()
        _inflight.pop(symbol, None)
