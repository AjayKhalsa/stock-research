"""
screener_scraper.py — Screener.in scraping/parsing + Google News RSS.
All the fragile HTML-shaped code lives here, away from routes and math.
"""

from __future__ import annotations

from typing import Optional

import feedparser
import httpx
from bs4 import BeautifulSoup

from config import SCRAPE_HEADERS

SCREENER_SEARCH_URL = "https://www.screener.in/api/company/search/"

RED_FLAG_WORDS = ["fraud", "raid", "investigation", "scam", "default", "bankrupt", "arrest", "sebi notice"]
NEGATIVE_WORDS = ["loss", "resign", "penalty", "fine", "lawsuit", "probe", "downgrade", "fall", "slump"]
POSITIVE_WORDS = ["profit", "growth", "buy", "upgrade", "record", "dividend", "expansion", "acquisition",
                  "strong", "beat", "outperform", "rally", "surge", "gain", "record high"]


def safe_float(val, default=None):
    try:
        if val in (None, "", "N/A", "-"):
            return default
        return float(str(val).replace(",", "").replace("%", "").strip())
    except Exception:
        return default


def analyze_sentiment(text: str):
    t = text.lower()
    red_flag = any(w in t for w in RED_FLAG_WORDS)
    neg = sum(1 for w in NEGATIVE_WORDS if w in t)
    pos = sum(1 for w in POSITIVE_WORDS if w in t)
    if red_flag or neg > pos:
        sentiment = "Negative"
    elif pos > neg:
        sentiment = "Positive"
    else:
        sentiment = "Neutral"
    return sentiment, red_flag


async def fetch_screener(symbol: str) -> dict:
    for url in [
        f"https://www.screener.in/company/{symbol}/consolidated/",
        f"https://www.screener.in/company/{symbol}/",
    ]:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                r = await c.get(url, headers=SCRAPE_HEADERS)
                if r.status_code == 200:
                    return parse_screener(r.text)
                # 429 = rate-limited, 403 = blocked — say so explicitly
                print(f"[screener] HTTP {r.status_code} from {url}"
                      + (" — RATE LIMITED" if r.status_code == 429 else ""))
        except Exception as e:
            print(f"[screener] {type(e).__name__}: {e} ({url})")
    return {}


def parse_screener(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    d = {}

    h1 = soup.find("h1", class_="h2")
    if h1:
        d["company_name"] = h1.get_text(strip=True)

    # Top ratios
    ratios = soup.find("ul", id="top-ratios")
    if ratios:
        for li in ratios.find_all("li"):
            n = li.find("span", class_="name")
            v = li.find("span", class_="number") or li.find("span", class_=None)
            if not (n and v):
                continue
            key = n.get_text(strip=True).lower()
            val = v.get_text(strip=True)
            if "market cap" in key:
                d["market_cap"] = val
            elif "current price" in key:
                d["screener_price"] = safe_float(val)
            elif "high / low" in key:
                parts = val.split("/")
                if len(parts) == 2:
                    d["week_high_52"] = safe_float(parts[0])
                    d["week_low_52"] = safe_float(parts[1])
            elif "stock p/e" in key:
                d["pe_ratio"] = safe_float(val)
            elif "book value" in key:
                d["book_value"] = safe_float(val)
            elif "dividend yield" in key:
                d["dividend_yield"] = safe_float(val)
            elif "roce" in key:
                d["roce"] = safe_float(val)
            elif "roe" in key:
                d["roe"] = safe_float(val)

    if d.get("book_value") and d.get("screener_price") and d["book_value"] > 0:
        d["pb_ratio"] = round(d["screener_price"] / d["book_value"], 2)

    # Quarterly results
    d["quarterly_results"] = []
    qs = soup.find("section", id="quarters")
    if qs:
        table = qs.find("table")
        if table:
            thead = table.find("thead")
            hdrs = [th.get_text(strip=True) for th in thead.find_all("th")] if thead else []
            tbody = table.find("tbody")
            row_map = {}
            if tbody:
                for row in tbody.find_all("tr"):
                    cells = row.find_all("td")
                    if cells:
                        rn = cells[0].get_text(strip=True).lower()
                        row_map[rn] = [cells[i].get_text(strip=True) for i in range(1, len(cells))]
            q_hdrs = hdrs[1:] if hdrs else []   # all available quarters
            for i, qh in enumerate(q_hdrs):
                q = {"quarter": qh}
                for rn, vals in row_map.items():
                    if i >= len(vals):
                        continue
                    if "sales" in rn or "revenue" in rn:
                        q["revenue"] = safe_float(vals[i])
                    elif "net profit" in rn or "profit after" in rn:
                        q["net_profit"] = safe_float(vals[i])
                    elif "opm" in rn:
                        q["opm"] = safe_float(vals[i])
                    elif "operating profit" in rn or "ebitda" in rn:
                        q["ebitda"] = safe_float(vals[i])
                # Screener publishes an "OPM %" row; when absent, derive it
                if q.get("opm") is None and q.get("ebitda") is not None \
                        and q.get("revenue"):
                    q["opm"] = round(q["ebitda"] / q["revenue"] * 100, 1)
                d["quarterly_results"].append(q)

    # Shareholding
    sh = {}
    sh_sec = soup.find("section", id="shareholding")
    if sh_sec:
        table = sh_sec.find("table")
        if table:
            thead = table.find("thead")
            hdrs = [th.get_text(strip=True) for th in thead.find_all("th")] if thead else []
            tbody = table.find("tbody")
            if tbody:
                for row in tbody.find_all("tr"):
                    cells = row.find_all("td")
                    if not cells:
                        continue
                    holder = cells[0].get_text(strip=True).lower()
                    # Columns run oldest -> newest, so the latest quarter is the LAST cell
                    latest = safe_float(cells[-1].get_text(strip=True)) if len(cells) > 1 else None
                    prev = safe_float(cells[-2].get_text(strip=True)) if len(cells) > 2 else None
                    if "promoter" in holder and "pledge" not in holder:
                        sh["promoter"] = latest
                        sh["promoter_prev"] = prev
                    elif "fii" in holder or "foreign" in holder:
                        sh["fii"] = latest
                        sh["fii_prev"] = prev
                    elif "dii" in holder or "domestic" in holder:
                        sh["dii"] = latest
                        sh["dii_prev"] = prev
                    elif "public" in holder or "retail" in holder:
                        sh["retail"] = latest
                        sh["retail_prev"] = prev
                    elif "pledg" in holder:
                        sh["promoter_pledge"] = latest
            if len(hdrs) > 1:
                sh["latest_quarter"] = hdrs[-1]
                sh["prev_quarter"] = hdrs[-2] if len(hdrs) > 2 else None
    d["shareholding"] = sh

    # Debt to equity - scan all tables
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if cells and len(cells) >= 2:
                lbl = cells[0].get_text(strip=True).lower()
                if "debt to equity" in lbl:
                    d["debt_to_equity"] = safe_float(cells[-1].get_text(strip=True))
                    break
        if "debt_to_equity" in d:
            break

    return d


async def fetch_news(symbol: str, company_name: str = "") -> list:
    query = company_name if company_name else symbol
    rss = f"https://news.google.com/rss/search?q={query}+NSE+stock&hl=en-IN&gl=IN&ceid=IN:en"
    articles = []
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(rss, headers=SCRAPE_HEADERS)
        feed = feedparser.parse(r.text)
        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            src = entry.get("source", {})
            source = src.get("title", "Google News") if isinstance(src, dict) else "Google News"
            sentiment, red_flag = analyze_sentiment(title)
            articles.append({
                "title": title,
                "source": source,
                "published": entry.get("published", ""),
                "link": entry.get("link", ""),
                "sentiment": sentiment,
                "red_flag": red_flag,
            })
    except Exception as e:
        print(f"[news] {e}")
    return articles


def parse_screener_annual(html: str) -> dict:
    """
    Parse the annual P&L, balance sheet, and cash flow tables from a
    Screener.in company page HTML.  Returns:
        annual_pl  : list of yearly dicts  {year, revenue, net_profit, ebitda, eps}
        annual_bs  : list of yearly dicts  {year, equity_capital, reserves,
                                            borrowings, total_assets,
                                            current_assets, current_liabilities}
        annual_cf  : list of yearly dicts  {year, cfo, cfi, cff}

    Years run oldest → newest so list[-1] is always the most recent.
    """
    soup = BeautifulSoup(html, "lxml")
    result: dict = {}

    def _parse_section(section_id: str, row_keywords: dict) -> list:
        """
        Generic parser for Screener annual tables.
        row_keywords: { output_key: [substring, ...] }  — first match wins.
        Returns list of dicts keyed by year header, oldest first.
        """
        sec = soup.find("section", id=section_id)
        if not sec:
            return []
        table = sec.find("table")
        if not table:
            return []

        thead = table.find("thead")
        year_headers = (
            [th.get_text(strip=True) for th in thead.find_all("th")][1:]
            if thead else []
        )

        tbody = table.find("tbody")
        if not tbody:
            return []

        # Build row_name → [values per year] map
        row_map: dict = {}
        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue
            label = cells[0].get_text(strip=True).lower()
            # Strip trailing "+" that Screener uses for expandable rows
            label = label.rstrip(" +").strip()
            vals  = [cells[i].get_text(strip=True) for i in range(1, len(cells))]
            row_map[label] = vals

        # Build output list
        output = []
        for i, yr in enumerate(year_headers):   # all available years
            entry = {"year": yr}
            for out_key, keywords in row_keywords.items():
                for kw in keywords:
                    for label, vals in row_map.items():
                        if kw in label and i < len(vals):
                            entry[out_key] = safe_float(vals[i])
                            break
                    if out_key in entry:
                        break
            output.append(entry)

        return output   # oldest first

    # ── Annual P&L  (section id="profit-loss") ───────────────────────────────
    result["annual_pl"] = _parse_section(
        "profit-loss",
        {
            "revenue":    ["sales", "revenue"],
            "net_profit": ["net profit", "profit after tax", "pat"],
            "ebitda":     ["operating profit", "ebitda"],
            "other_income": ["other income"],
            "interest":   ["interest"],
            "depreciation": ["depreciation"],
            "profit_before_tax": ["profit before tax"],
            "eps":        ["eps in rs", "basic eps", "eps"],
        },
    )

    # ── Balance Sheet  (section id="balance-sheet") ──────────────────────────
    # Screener's consolidated BS layout:
    #   Equity Capital | Reserves | Borrowings | Other Liabilities | Total Liabilities
    #   Fixed Assets   | CWIP     | Investments| Other Assets      | Total Assets
    # "Other Assets" is a reasonable current-assets proxy;
    # "Other Liabilities" is a reasonable current-liabilities proxy.
    result["annual_bs"] = _parse_section(
        "balance-sheet",
        {
            "equity_capital":       ["equity capital"],
            "reserves":             ["reserves"],
            "borrowings":           ["borrowings"],
            "current_liabilities":  ["other liabilities"],  # Screener proxy
            "fixed_assets":         ["fixed assets"],
            "total_assets":         ["total assets"],
            "current_assets":       ["other assets"],       # Screener proxy
        },
    )

    # ── Cash Flow  (section id="cash-flow") ──────────────────────────────────
    result["annual_cf"] = _parse_section(
        "cash-flow",
        {
            "cfo": ["cash from operating", "operating activity"],
            "cfi": ["cash from investing", "investing activity"],
            "cff": ["cash from financing", "financing activity"],
        },
    )

    return result


async def resolve_screener_slug(symbol: str) -> Optional[str]:
    """
    Screener's company-search API resolves a raw ticker to its canonical page
    slug even when the slug differs from the NSE symbol (renames, dual pages).
    Returns the slug or None. Numeric slugs are BSE scrip codes and are skipped.
    """
    import re
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(SCREENER_SEARCH_URL, params={"q": symbol},
                            headers=SCRAPE_HEADERS)
            if r.status_code != 200:
                return None
            results = r.json()
    except Exception as e:
        print(f"[screener] slug resolution failed for {symbol}: {e}")
        return None
    up = symbol.upper()
    best = None
    for item in results:
        m = re.match(r"^/company/([A-Za-z0-9&._-]+)/", item.get("url", ""))
        if not m or m.group(1).isdigit():
            continue
        slug = m.group(1)
        if slug.upper() == up:          # exact ticker match wins immediately
            return slug
        if best is None:                # else keep the first non-numeric hit
            best = slug
    return best


async def _fetch_screener_html(symbol: str) -> Optional[str]:
    """
    Resilient HTML fetch: try the direct consolidated/standalone slugs, retry
    once on a transient failure (429 / connection drop), and finally resolve
    the canonical slug through the search API. Returns HTML or None.
    """
    urls = [
        f"https://www.screener.in/company/{symbol}/consolidated/",
        f"https://www.screener.in/company/{symbol}/",
    ]
    rate_limited = False
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=22, follow_redirects=True) as c:
                r = await c.get(url, headers=SCRAPE_HEADERS)
            if r.status_code == 200:
                return r.text
            if r.status_code == 429:
                rate_limited = True
            print(f"[screener_full] HTTP {r.status_code} from {url}"
                  + (" — RATE LIMITED" if r.status_code == 429 else ""))
        except Exception as e:
            print(f"[screener_full] {type(e).__name__}: {e} ({url})")

    # Slug fallback: the raw ticker did not resolve directly — ask the search
    # API for the canonical slug and retry (fixes symbol/slug mismatches).
    slug = await resolve_screener_slug(symbol)
    if slug and slug.upper() != symbol.upper():
        for url in [
            f"https://www.screener.in/company/{slug}/consolidated/",
            f"https://www.screener.in/company/{slug}/",
        ]:
            try:
                async with httpx.AsyncClient(timeout=22, follow_redirects=True) as c:
                    r = await c.get(url, headers=SCRAPE_HEADERS)
                if r.status_code == 200:
                    print(f"[screener_full] resolved {symbol} -> slug {slug}")
                    return r.text
            except Exception as e:
                print(f"[screener_full] slug retry {type(e).__name__}: {e} ({url})")

    if rate_limited:
        print(f"[screener_full] {symbol}: rate-limited, no data this pass")
    return None


async def fetch_screener_full(symbol: str) -> dict:
    """
    Fetch Screener's company page (with slug-resolution fallback) and return
    the merged top-ratio + annual P&L / balance sheet / cash flow dict.
    Returns {} only when every attempt failed.
    """
    html = await _fetch_screener_html(symbol)
    if html is None:
        return {}
    base   = parse_screener(html)
    annual = parse_screener_annual(html)
    return {**base, **annual}
