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


def _parse(content: bytes, content_type: str = "") -> dict[str, float]:
    raw = content
    if content[:2] == b"PK" or "zip" in content_type.lower():
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if not names:
                return {}
            raw = archive.read(names[0])
    text = raw.decode("utf-8-sig", errors="replace")
    out: dict[str, float] = {}
    for row in csv.DictReader(io.StringIO(text)):
        symbol = str(_pick(row, "SYMBOL", "TckrSymb") or "").strip().upper()
        series = str(_pick(row, "SERIES", "SctySrs") or "EQ").strip().upper()
        close = _pick(row, "CLOSE_PRICE", "CLOSE", "ClsPric")
        if not symbol or series != "EQ":
            continue
        try:
            out[symbol] = round(float(str(close).replace(",", "").strip()), 2)
        except (TypeError, ValueError):
            continue
    return out


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
                    closes = await asyncio.to_thread(
                        _parse, response.content, response.headers.get("content-type", "")
                    )
                    if closes:
                        return {"as_of": day.isoformat(), "closes": closes,
                                "source": "NSE bhavcopy", "url": url, "error": None}
                except Exception as exc:  # provider fallback is expected
                    errors.append(f"{type(exc).__name__}: {exc}")
    return {"as_of": None, "closes": {}, "source": "NSE bhavcopy",
            "url": None, "error": errors[-1] if errors else "No recent bhavcopy available"}
