"""Best-effort adapter for NSE's official cash-market bhavcopy archives."""

from __future__ import annotations

import asyncio
import csv
import io
import zipfile
from datetime import date, timedelta
from typing import Optional

import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "text/csv,application/zip,*/*",
    "Referer": "https://www.nseindia.com/",
}


def _urls(day: date) -> list[str]:
    ymd, dmy = day.strftime("%Y%m%d"), day.strftime("%d%m%Y")
    return [
        f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
        f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{dmy}.csv",
        f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{dmy}.csv",
    ]


def _pick(row: dict, *names: str):
    normalized = {str(k).strip().upper(): v for k, v in row.items()}
    for name in names:
        value = normalized.get(name.upper())
        if value not in (None, ""):
            return value
    return None


def _number(value) -> Optional[float]:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_market(content: bytes, content_type: str = "") -> dict:
    raw = content
    if content[:2] == b"PK" or "zip" in content_type.lower():
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if not names:
                return {}
            raw = archive.read(names[0])
    text = raw.decode("utf-8-sig", errors="replace")
    closes: dict[str, float] = {}
    bars: dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(text)):
        symbol = str(_pick(row, "SYMBOL", "TckrSymb") or "").strip().upper()
        series = str(_pick(row, "SERIES", "SctySrs") or "EQ").strip().upper()
        close = _number(_pick(row, "CLOSE_PRICE", "CLOSE", "ClsPric"))
        if not symbol or series != "EQ":
            continue
        if close is None or close <= 0:
            continue
        closes[symbol] = round(close, 2)
        open_price = _number(_pick(row, "OPEN_PRICE", "OPEN", "OpnPric"))
        high = _number(_pick(row, "HIGH_PRICE", "HIGH", "HghPric"))
        low = _number(_pick(row, "LOW_PRICE", "LOW", "LwPric"))
        volume = _number(_pick(row, "TTL_TRD_QNTY", "TOTTRDQTY", "TtlTradgVol"))
        if (None not in (open_price, high, low, volume)
                and min(open_price, high, low) > 0 and volume >= 0):
            bars[symbol] = {
                "open": round(open_price, 2), "high": round(high, 2),
                "low": round(low, 2), "close": round(close, 2),
                "raw_close": round(close, 2), "adjustment_factor": 1.0,
                "volume": int(volume),
            }
    return {"closes": closes, "bars": bars}


def _parse(content: bytes, content_type: str = "") -> dict[str, float]:
    """Backward-compatible close-map parser used by older callers/tests."""
    return _parse_market(content, content_type)["closes"]


async def fetch_latest_bhavcopy(as_of: Optional[date] = None, lookback_days: int = 8) -> dict:
    """Return the newest available official EQ close map, skipping holidays."""
    target = as_of or date.today()
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=HEADERS) as client:
        for offset in range(max(1, lookback_days)):
            day = target - timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            for url in _urls(day):
                try:
                    response = await client.get(url)
                    if response.status_code != 200 or len(response.content) < 100:
                        continue
                    market = await asyncio.to_thread(
                        _parse_market, response.content, response.headers.get("content-type", "")
                    )
                    closes = market["closes"]
                    if closes:
                        return {"as_of": day.isoformat(), "closes": closes,
                                "bars": market["bars"],
                                "source": "NSE bhavcopy", "url": url, "error": None}
                except Exception as exc:  # provider fallback is expected
                    errors.append(f"{type(exc).__name__}: {exc}")
    return {"as_of": None, "closes": {}, "bars": {}, "source": "NSE bhavcopy",
            "url": None, "error": errors[-1] if errors else "No recent bhavcopy available"}
