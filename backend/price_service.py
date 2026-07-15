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
            df = yf.Ticker(symbol).history(start=start, end=end, interval="1d", auto_adjust=False)
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


async def get_historical(instrument: str, days: int = 300) -> list:
    sym = _yf_symbol(instrument)
    def _fetch():
        try:
            end   = datetime.now()
            start = end - timedelta(days=days + 15)   # pad for weekends/holidays
            df    = yf.Ticker(sym).history(start=start, end=end, interval="1d", auto_adjust=False)
            return _df_to_candles(df)
        except Exception as e:
            print(f"[price_service] historical error {sym}: {e}")
            return []
    return await asyncio.to_thread(_fetch)
