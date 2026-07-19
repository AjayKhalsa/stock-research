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
import math
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}
_REVERSE_SUFFIX = {".NS": "NSE", ".BO": "BSE"}


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


async def get_historical(instrument: str, days: int = 300) -> list:
    sym = _yf_symbol(instrument)
    def _fetch():
        try:
            end   = datetime.now()
            start = end - timedelta(days=days + 15)   # pad for weekends/holidays
            # Yahoo's raw daily series is already split/bonus-adjusted;
            # auto_adjust=True additionally folds dividends in (total-return
            # series) so ex-dividend price gaps don't distort MAs/RSI/ATR or
            # falsely trigger stops in the base-rate backtest. The latest
            # candle always equals the actual traded price.
            df    = yf.Ticker(sym).history(start=start, end=end, interval="1d", auto_adjust=True)
            return _df_to_candles(df)
        except Exception as e:
            print(f"[price_service] historical error {sym}: {e}")
            return []
    return await asyncio.to_thread(_fetch)


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
            sector = industry = None
            try:
                info = t.get_info()
                sector = info.get("sector")
                industry = info.get("industry")
            except Exception:
                pass
            return {
                "bs_by_year": _extract_by_year(bs,  _BS_LABELS, bs_scale),
                "pl_by_year": _extract_by_year(inc, _PL_LABELS, pl_scale),
                "cf_by_year": _extract_by_year(cf,  _CF_LABELS, cf_scale),
                "sector": sector,
                "industry": industry,
                "source": "yfinance",
            }
        except Exception as e:
            print(f"[price_service] fundamentals error {sym}: {e}")
            return {"bs_by_year": {}, "pl_by_year": {}, "cf_by_year": {}, "source": "yfinance"}

    return await asyncio.to_thread(_fetch)
