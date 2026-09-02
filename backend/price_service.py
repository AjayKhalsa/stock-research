"""
price_service.py
Free market-data provider using Yahoo Finance (yfinance) for NSE/BSE symbols.

No API key, no login, no daily token refresh — replaces the old Kite Connect
integration. Quotes are end-of-day / a few minutes delayed, which is fine for
research and swing-trade screening (this is NOT suitable for order execution
or latency-sensitive intraday trading).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import yfinance as yf

import config

# yfinance otherwise writes cookie/timezone SQLite files under a user profile
# path that may be read-only on local runners and hosted workers. Keep provider
# cache state beside the rest of StockLens' writable data instead.
_YF_CACHE_DIR = os.path.join(config.DATA_DIR, "yfinance")
os.makedirs(_YF_CACHE_DIR, exist_ok=True)
try:
    yf.cache.set_cache_location(_YF_CACHE_DIR)
except Exception as exc:
    print(f"[price_service] yfinance cache setup warning: {exc}")

_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}
_REVERSE_SUFFIX = {".NS": "NSE", ".BO": "BSE"}
YAHOO_CHART_CONCURRENCY = 6


def _chart_payload_to_candles(payload: dict) -> list[dict]:
    """Convert Yahoo's compact chart JSON into adjusted daily OHLCV bars."""
    try:
        result = payload["chart"]["result"][0]
        timestamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        adjusted = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
    except (KeyError, IndexError, TypeError, AttributeError):
        return []

    closes = quote.get("close") or []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    volumes = quote.get("volume") or []
    candles: list[dict] = []
    for index, timestamp in enumerate(timestamps):
        try:
            raw_close = float(closes[index])
            adj_close = float(adjusted[index]) if index < len(adjusted) and adjusted[index] is not None else raw_close
            if not math.isfinite(raw_close) or not math.isfinite(adj_close) or raw_close <= 0:
                continue
            ratio = adj_close / raw_close

            def adjusted_price(values: list) -> float:
                value = values[index] if index < len(values) else raw_close
                value = raw_close if value is None else float(value)
                return round(value * ratio, 2) if math.isfinite(value) else round(adj_close, 2)

            volume = volumes[index] if index < len(volumes) else 0
            candles.append({
                "date": datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date().isoformat(),
                "open": adjusted_price(opens), "high": adjusted_price(highs),
                "low": adjusted_price(lows), "close": round(adj_close, 2),
                "volume": int(volume or 0),
            })
        except (TypeError, ValueError, IndexError, OverflowError):
            continue
    return candles


async def _fetch_chart_history(client: httpx.AsyncClient, semaphore: asyncio.Semaphore,
                               raw: str, yf_symbol: str, days: int) -> tuple[str, list]:
    period2 = int(datetime.now(tz=timezone.utc).timestamp()) + 86_400
    period1 = period2 - (days + 15) * 86_400
    params = {"period1": period1, "period2": period2, "interval": "1d",
              "events": "div,splits", "includeAdjustedClose": "true"}
    for attempt, host in enumerate(("query1.finance.yahoo.com", "query2.finance.yahoo.com")):
        try:
            async with semaphore:
                response = await client.get(
                    f"https://{host}/v8/finance/chart/{yf_symbol}", params=params,
                )
            if response.status_code == 429:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            response.raise_for_status()
            candles = _chart_payload_to_candles(response.json())
            if candles:
                return raw, candles
        except (httpx.HTTPError, ValueError, TypeError):
            if attempt == 0:
                await asyncio.sleep(0.2)
    return raw, []


def _yf_symbol(instrument: str) -> str:
    """'NSE:INFY' -> 'INFY.NS'  ;  'INFY' -> 'INFY.NS' (defaults to NSE)."""
    if ":" in instrument:
        exch, sym = instrument.split(":", 1)
    else:
        exch, sym = "NSE", instrument
    return f"{sym.upper()}{_SUFFIX.get(exch.upper(), '.NS')}"


def _fi(fast_info, key: str) -> Optional[float]:
    """FastInfo only supports bracket access — .get() silently returns None."""
    try:
        return fast_info[key]
    except Exception:
        return None


def _df_to_candles(df) -> list:
    if df is None or df.empty:
        return []
    out = []
    for idx, row in df.iterrows():
        try:
            close = float(row["Close"])
            if math.isnan(close) or math.isinf(close):
                continue   # yfinance emits NaN rows (holidays, demergers) — drop them
            def _px(key):
                try:
                    v = float(row[key])
                    return round(v, 2) if not (math.isnan(v) or math.isinf(v)) else round(close, 2)
                except Exception:
                    return round(close, 2)
            vol = row.get("Volume", 0)
            out.append({
                "date":   idx.strftime("%Y-%m-%d"),
                "open":   _px("Open"),
                "high":   _px("High"),
                "low":    _px("Low"),
                "close":  round(close, 2),
                "volume": int(vol) if vol is not None and not math.isnan(vol) else 0,
            })
        except Exception:
            continue
    return out


# ── search ───────────────────────────────────────────────────────────────────

async def search_instruments(q: str, limit: int = 15) -> list:
    """Yahoo Finance autocomplete search, filtered to NSE/BSE listings."""
    def _search():
        try:
            res = yf.Search(q, max_results=max(limit * 3, 15))
            out, seen = [], set()
            for item in res.quotes:
                sym = item.get("symbol", "")
                if sym.endswith(".NS"):
                    exch = "NSE"
                elif sym.endswith(".BO"):
                    exch = "BSE"
                else:
                    continue
                clean = sym[:-3]
                if clean in seen:
                    continue
                seen.add(clean)
                out.append({
                    "symbol": clean,
                    "name": item.get("shortname") or item.get("longname") or clean,
                    "exchange": exch,
                })
                if len(out) >= limit:
                    break
            return out
        except Exception as e:
            print(f"[price_service] search error: {e}")
            return []
    return await asyncio.to_thread(_search)


# ── quotes ───────────────────────────────────────────────────────────────────

async def get_ltp(instrument: str) -> dict:
    sym = _yf_symbol(instrument)
    def _fetch():
        try:
            fi   = yf.Ticker(sym).fast_info
            last = _fi(fi, "last_price")
            if last is None:
                return {}
            return {"last_price": round(last, 2), "instrument_token": None}
        except Exception as e:
            print(f"[price_service] ltp error {sym}: {e}")
            return {}
    return await asyncio.to_thread(_fetch)


async def get_ltp_multiple(instruments: list) -> dict:
    if not instruments:
        return {}
    def _fetch():
        out = {}
        for inst in instruments:
            sym = _yf_symbol(inst)
            try:
                last = _fi(yf.Ticker(sym).fast_info, "last_price")
                if last is not None:
                    out[inst] = round(last, 2)
            except Exception as e:
                print(f"[price_service] ltp_multiple error {inst}: {e}")
        return out
    return await asyncio.to_thread(_fetch)


async def get_ohlc(instrument: str) -> dict:
    sym = _yf_symbol(instrument)
    def _fetch():
        try:
            fi   = yf.Ticker(sym).fast_info
            last = _fi(fi, "last_price")
            prev = _fi(fi, "previous_close")
            if last is None:
                return {}
            day_change     = (last - prev) if prev else 0
            day_change_pct = (day_change / prev * 100) if prev else 0
            open_  = _fi(fi, "open")
            high_  = _fi(fi, "day_high")
            low_   = _fi(fi, "day_low")
            return {
                "last_price": round(last, 2),
                "open":  round(open_, 2) if open_ else None,
                "high":  round(high_, 2) if high_ else None,
                "low":   round(low_, 2)  if low_  else None,
                "close": round(prev, 2)  if prev  else None,
                "day_change":     round(day_change, 2),
                "day_change_pct": round(day_change_pct, 2),
            }
        except Exception as e:
            print(f"[price_service] ohlc error {sym}: {e}")
            return {}
    return await asyncio.to_thread(_fetch)


_INDEX_CACHE: dict = {}   # {symbol: {"at": epoch, "data": [...]}}
_INDEX_TTL = 1800         # 30 min


async def get_index_historical(symbol: str = "^NSEI", days: int = 400) -> list:
    """
    Daily candles for a raw Yahoo index symbol (e.g. ^NSEI for NIFTY 50),
    cached for 30 minutes — the market regime doesn't change per request.
    """
    import time as _time
    cached = _INDEX_CACHE.get(symbol)
    if cached and _time.time() - cached["at"] < _INDEX_TTL and len(cached["data"]) > 0:
        return cached["data"]

    def _fetch():
        try:
            end = datetime.now()
            start = end - timedelta(days=days + 15)
            df = yf.Ticker(symbol).history(start=start, end=end, interval="1d", auto_adjust=True)
            return _df_to_candles(df)
        except Exception as e:
            print(f"[price_service] index historical error {symbol}: {e}")
            return []

    data = await asyncio.to_thread(_fetch)
    if data:
        _INDEX_CACHE[symbol] = {"at": _time.time(), "data": data}
    elif cached:
        return cached["data"]   # stale beats nothing
    return data


async def get_intraday(instrument: str, interval: str = "1h",
                       days: int = 60) -> list:
    """
    Intraday candles for structural stop refinement. yfinance limits:
    1h data reaches ~730 days back, 15m data ~60 days. Returns the same
    candle dict shape as get_historical (dates carry the bar timestamp).
    """
    sym = _yf_symbol(instrument)

    def _fetch():
        try:
            end = datetime.now()
            start = end - timedelta(days=days)
            df = yf.Ticker(sym).history(start=start, end=end,
                                        interval=interval, auto_adjust=True)
            return _df_to_candles(df)
        except Exception as e:
            print(f"[price_service] intraday error {sym} {interval}: {e}")
            return []

    return await asyncio.to_thread(_fetch)


_HIST_CACHE: dict = {}    # {(sym, days): {"at": epoch, "data": [...]}}
_HIST_TTL = 1800          # 30 min - short enough to stay swing-relevant, long
                           # enough that a Refresh List or an overlapping
                           # saved screen minutes later skips the network
                           # entirely instead of re-pulling 450 days per stock.

_HISTORY_DIR = os.path.join(config.DATA_DIR, "price_history")
os.makedirs(_HISTORY_DIR, exist_ok=True)


def _history_path(symbol: str, days: int) -> str:
    safe = re.sub(r"[^A-Z0-9_.-]", "_", symbol.upper())
    return os.path.join(_HISTORY_DIR, f"{safe}-{int(days)}.json")


def _read_persisted_history(symbol: str, days: int) -> tuple[list, float]:
    try:
        with open(_history_path(symbol, days), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload.get("data") or [], float(payload.get("saved_at") or 0)
    except (OSError, TypeError, ValueError):
        return [], 0


def persist_history(instrument: str, days: int, data: list) -> None:
    """Atomically retain EOD history for offline dossiers/provider outages."""
    if not data:
        return
    import time as _time
    symbol = _yf_symbol(instrument)
    path = _history_path(symbol, days)
    temporary = f"{path}.{os.getpid()}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"saved_at": _time.time(), "data": data}, handle, separators=(",", ":"))
        os.replace(temporary, path)
    except OSError as exc:
        print(f"[price_service] history cache write error {symbol}: {exc}")
        try:
            os.remove(temporary)
        except OSError:
            pass


async def get_historical(instrument: str, days: int = 300) -> list:
    # Use the same compact chart JSON adapter as the market-wide scan. This is
    # faster and far less memory-hungry than constructing yfinance/pandas data
    # frames for a single search result, while retaining cache/stale fallback.
    result = await get_historical_multiple([instrument], days=days, cache_results=True)
    return result.get(instrument) or []


async def get_historical_multiple(instruments: list[str], days: int = 300,
                                  cache_results: bool = True) -> dict[str, list]:
    """Fetch candles with bounded async chart requests and optional caching.

    The market-wide pipeline disables result caching so only one 75-symbol
    batch plus its top-candidate heap remains in memory on the free instance.
    """
    import time as _time

    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for instrument in instruments:
        raw = str(instrument).strip()
        if not raw:
            continue
        yf_symbol = _yf_symbol(raw)
        if yf_symbol not in seen:
            seen.add(yf_symbol)
            unique.append((raw, yf_symbol))

    now = _time.time()
    out: dict[str, list] = {}
    stale_fallback: dict[str, list] = {}
    missing: list[tuple[str, str]] = []
    for raw, yf_symbol in unique:
        cached = _HIST_CACHE.get((yf_symbol, days))
        if cached and now - cached["at"] < _HIST_TTL and cached["data"]:
            out[raw] = cached["data"]
        else:
            missing.append((raw, yf_symbol))
            persisted, _persisted_at = _read_persisted_history(yf_symbol, days)
            if persisted:
                stale_fallback[raw] = persisted

    if not missing:
        return out

    timeout = httpx.Timeout(15, connect=8)
    limits = httpx.Limits(max_connections=YAHOO_CHART_CONCURRENCY,
                          max_keepalive_connections=YAHOO_CHART_CONCURRENCY)
    semaphore = asyncio.Semaphore(YAHOO_CHART_CONCURRENCY)
    fresh: dict[str, list] = {}
    async with httpx.AsyncClient(timeout=timeout, limits=limits,
                                 headers=config.SCRAPE_HEADERS) as client:
        tasks = [asyncio.create_task(
            _fetch_chart_history(client, semaphore, raw, yf_symbol, days)
        ) for raw, yf_symbol in missing]
        for task in asyncio.as_completed(tasks):
            raw, candles = await task
            if candles:
                fresh[raw] = candles
    out.update(fresh)
    for raw, candles in stale_fallback.items():
        out.setdefault(raw, candles)
    if cache_results:
        cached_at = _time.time()
        yf_by_raw = dict(missing)
        for raw, candles in fresh.items():
            _HIST_CACHE[(yf_by_raw[raw], days)] = {"at": cached_at, "data": candles}
    return out


# ── fundamentals (reported financial statements) ──────────────────────────────
#
# yfinance exposes the actual reported balance sheet / income statement / cash
# flow. Values are in absolute rupees, so we convert to ₹ crore (÷ 1e7) to match
# Screener's scale. Label matching is alias-based (case-insensitive substring)
# because Yahoo's row names drift across versions and companies.

_CR = 1e7  # 1 crore = 10,000,000

# output_key -> list of candidate Yahoo row labels (first match wins, tolerant)
_BS_LABELS = {
    "total_assets":        ["total assets"],
    "current_assets":      ["current assets"],
    "current_liabilities": ["current liabilities"],
    "total_equity":        ["stockholders equity", "total equity gross minority", "common stock equity"],
    "reserves":            ["retained earnings"],
    "equity_capital":      ["capital stock", "common stock"],
    "borrowings":          ["total debt", "long term debt"],
    "fixed_assets":        ["net ppe", "net property", "gross ppe"],
}
_PL_LABELS = {
    "revenue":            ["total revenue", "operating revenue"],
    "net_profit":         ["net income continuous", "net income"],
    "ebitda":             ["ebitda", "normalized ebitda"],
    "ebit":               ["ebit", "operating income"],
    "profit_before_tax":  ["pretax income", "profit before tax"],
    "interest":           ["interest expense"],
    "depreciation":       ["reconciled depreciation", "depreciation amortization"],
    "eps":                ["diluted eps", "basic eps"],
}
_CF_LABELS = {
    "cfo": ["operating cash flow", "cash flow from continuing operating"],
    "cfi": ["investing cash flow", "cash flow from continuing investing"],
    "cff": ["financing cash flow", "cash flow from continuing financing"],
}


def _pick_row(df, labels: list):
    """First DataFrame row whose (lowercased) index label matches an alias."""
    if df is None or getattr(df, "empty", True):
        return None
    idx_lower = {str(i).lower(): i for i in df.index}
    # exact match first, then substring
    for lab in labels:
        if lab in idx_lower:
            return df.loc[idx_lower[lab]]
    for lab in labels:
        for low, orig in idx_lower.items():
            if lab in low:
                return df.loc[orig]
    return None


def _extract_by_year(df, label_map: dict, scale_keys: set) -> dict:
    """
    Build {year_int: {output_key: value}} from a yfinance statement DataFrame.
    Columns are period-end dates; values in `scale_keys` are converted to crore.
    """
    out: dict = {}
    if df is None or getattr(df, "empty", True):
        return out
    rows = {k: _pick_row(df, labs) for k, labs in label_map.items()}
    for col in df.columns:
        try:
            year = col.year
        except Exception:
            continue
        entry: dict = {}
        for key, row in rows.items():
            if row is None:
                continue
            try:
                val = row[col]
            except Exception:
                continue
            if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
                continue
            val = float(val)
            if key in scale_keys:
                val = round(val / _CR, 2)
            entry[key] = val
        if entry:
            out[year] = entry
    return out


async def get_fundamentals(instrument: str) -> dict:
    """
    Reported annual financial statements from yfinance, keyed by calendar year:
        {"pl_by_year": {...}, "bs_by_year": {...}, "cf_by_year": {...},
         "source": "yfinance"}
    Returns empty dicts on any failure so the caller can fall back to Screener.
    All monetary values are in ₹ crore (EPS is left per-share).
    """
    sym = _yf_symbol(instrument)

    def _fetch():
        try:
            t = yf.Ticker(sym)
            bs  = t.balance_sheet
            inc = t.income_stmt
            cf  = t.cashflow
            bs_scale = set(_BS_LABELS) - set()               # all BS values are ₹ → crore
            pl_scale = set(_PL_LABELS) - {"eps"}             # everything except EPS
            cf_scale = set(_CF_LABELS)                       # all cash flows → crore
            # Sector/industry classification (cached with the 4h fundamentals TTL)
            sector = industry = earnings_date = None
            try:
                info = t.get_info()
                sector = info.get("sector")
                industry = info.get("industry")
                earnings_ts = info.get("earningsTimestampStart") or info.get("earningsTimestamp")
                if earnings_ts:
                    earnings_date = datetime.fromtimestamp(float(earnings_ts)).date().isoformat()
            except Exception:
                pass
            return {
                "bs_by_year": _extract_by_year(bs,  _BS_LABELS, bs_scale),
                "pl_by_year": _extract_by_year(inc, _PL_LABELS, pl_scale),
                "cf_by_year": _extract_by_year(cf,  _CF_LABELS, cf_scale),
                "sector": sector,
                "industry": industry,
                "earnings_date": earnings_date,
                "source": "yfinance",
            }
        except Exception as e:
            print(f"[price_service] fundamentals error {sym}: {e}")
            return {"bs_by_year": {}, "pl_by_year": {}, "cf_by_year": {}, "source": "yfinance"}

    return await asyncio.to_thread(_fetch)
