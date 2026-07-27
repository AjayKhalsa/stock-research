"""
chartink_scraper.py — Chartink screener scraping for the daily auto-fetcher.

Chartink screener pages are single-page-app shells: the actual scan is run
server-side by POSTing the screen's "scan_clause" to /screener/process, using
a CSRF token issued on the page load and the session cookie from that same
load. Neither is exposed as a documented API — both are scraped out of the
screener page's HTML, so this module is inherently as fragile as
screener_scraper.py is to Screener.in's markup, and for the same reason:
there is no official, stable API to depend on instead.

Any failure (network, markup drift, no clause found, non-200 response) is
logged and swallowed — this module never raises. The auto-screen endpoint
that calls it treats an empty list as "nothing to do", not an error.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from config import SCRAPE_HEADERS

PROCESS_URL = "https://chartink.com/screener/process"

# Fallback regex for scan_clause when it isn't in a plain hidden input/textarea
# (Chartink has, at times, inlined it into a <script> block instead).
_SCAN_CLAUSE_JS_RE = re.compile(r"scan_clause\s*[:=]\s*[\"'](.+?)[\"']", re.DOTALL)


def _extract_csrf_token(soup: BeautifulSoup) -> str | None:
    meta = soup.find("meta", attrs={"name": "csrf-token"})
    if meta and meta.get("content"):
        return meta["content"]
    return None


def _extract_scan_clause(html: str, soup: BeautifulSoup) -> str | None:
    # Most screener pages carry it as a hidden input or a backing textarea.
    for attrs in ({"id": "scan_clause"}, {"name": "scan_clause"}):
        el = soup.find(["input", "textarea"], attrs=attrs)
        if el is not None:
            val = el.get("value") or el.text
            if val and val.strip():
                return val.strip()
    # Fallback: some pages only expose it inline in a <script> block.
    m = _SCAN_CLAUSE_JS_RE.search(html)
    if m:
        return m.group(1).strip()
    return None


async def fetch_screener_tickers(screener_url: str) -> list[str]:
    """
    Load a Chartink screener page, run its scan via /screener/process, and
    return the deduped, upper-cased NSE symbols it matched today. Returns []
    on any failure — see module docstring.
    """
    if not screener_url:
        return []

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            page = await client.get(screener_url, headers=SCRAPE_HEADERS)
            if page.status_code != 200:
                print(f"[chartink] HTTP {page.status_code} loading {screener_url}")
                return []

            soup = BeautifulSoup(page.text, "lxml")
            csrf_token = _extract_csrf_token(soup)
            scan_clause = _extract_scan_clause(page.text, soup)

            if not csrf_token or not scan_clause:
                print(f"[chartink] could not find "
                      f"{'csrf token' if not csrf_token else 'scan clause'} "
                      f"on {screener_url} — page markup may have changed")
                return []

            # Diagnostic only: confirms what we're about to submit without
            # dumping a potentially long clause in full.
            print(f"[chartink] submitting scan_clause "
                  f"({len(scan_clause)} chars): {scan_clause[:200]!r}"
                  f"{'...' if len(scan_clause) > 200 else ''}")

            resp = await client.post(
                PROCESS_URL,
                data={"scan_clause": scan_clause},
                headers={
                    **SCRAPE_HEADERS,
                    "x-csrf-token": csrf_token,
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": screener_url,
                },
            )
            if resp.status_code != 200:
                print(f"[chartink] HTTP {resp.status_code} from /screener/process"
                      + (" — RATE LIMITED" if resp.status_code == 429 else ""))
                return []

            try:
                payload = resp.json()
            except Exception as e:
                print(f"[chartink] non-JSON response from /screener/process: {e}")
                return []

            rows = payload.get("data") or []
            symbols, seen = [], set()
            for row in rows:
                sym = str(row.get("nsecode") or "").strip().upper()
                if sym and sym not in seen:
                    seen.add(sym)
                    symbols.append(sym)

            if not symbols:
                # Every prior step succeeded (200s, valid JSON) but the scan
                # matched nothing, or matched rows didn't carry "nsecode".
                # This was previously a SILENT empty return — the one gap in
                # this module's error logging — so log exactly what came back.
                extra = {k: v for k, v in payload.items() if k != "data"}
                print(f"[chartink] scan ran but returned {len(rows)} raw row(s), "
                      f"0 usable symbols. Sample row: {rows[0] if rows else None!r}. "
                      f"Other response keys: {extra!r}")
            return symbols

    except Exception as e:                                    # noqa: BLE001
        print(f"[chartink] {type(e).__name__}: {e} ({screener_url})")
        return []
