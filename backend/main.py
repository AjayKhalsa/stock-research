import os
from dotenv import load_dotenv

# Load .env from the repo root and backend/ BEFORE importing modules that read
# env vars at import time (ai_engine reads GEMINI_API_KEY on import).
_here = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(os.path.dirname(_here), ".env"))
load_dotenv(os.path.join(_here, ".env"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import json, asyncio, re
from typing import Optional
import feedparser, httpx
from bs4 import BeautifulSoup
import price_service as price
import quant_engine
import qualitative_engine
import ai_engine
import swing_engine
import decision_engine
import alert_store
import symbol_resolver
import conviction_engine

app = FastAPI(title="Stock Research API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    # Local dev (any LAN host on :3000) + any *.vercel.app deployment
    allow_origin_regex=r"(http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+):3000|https://.*\.vercel\.app)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")

SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

RED_FLAG_WORDS = ["fraud", "raid", "investigation", "scam", "default", "bankrupt", "arrest", "sebi notice"]
NEGATIVE_WORDS = ["loss", "resign", "penalty", "fine", "lawsuit", "probe", "downgrade", "fall", "slump"]
POSITIVE_WORDS = ["profit", "growth", "buy", "upgrade", "record", "dividend", "expansion", "acquisition",
                  "strong", "beat", "outperform", "rally", "surge", "gain", "record high"]


# ── helpers ──────────────────────────────────────────────────────────────────

def load_json(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            pass
    return default


def save_json(path, data):
    json.dump(data, open(path, "w"), indent=2)


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


def calc_rsi(prices: list, period=14) -> Optional[float]:
    # Wilder's smoothed RSI (matches swing_engine / conviction_engine).
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 2)


def calc_ma(prices: list, period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    return round(sum(prices[-period:]) / period, 2)


# ── screener scraping ─────────────────────────────────────────────────────────

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


def _compute_technicals(hist_data: list) -> dict:
    """Shared helper used by both /api/stock/{symbol} and /alpha."""
    tech = {}
    if not hist_data:
        return tech
    closes = [c["close"] for c in hist_data if "close" in c]
    if not closes:
        return tech
    tech["ma50"]          = calc_ma(closes, 50)
    tech["ma200"]         = calc_ma(closes, 200)
    tech["rsi"]           = calc_rsi(closes)
    tech["current_price"] = closes[-1]
    cur, ma50, ma200      = closes[-1], tech["ma50"], tech["ma200"]
    if ma50 and ma200:
        if cur > ma50 and ma50 > ma200:   tech["trend"] = "Uptrend"
        elif cur < ma50 and ma50 < ma200: tech["trend"] = "Downtrend"
        else:                             tech["trend"] = "Sideways"
    elif ma50:
        tech["trend"] = "Uptrend" if cur > ma50 else "Downtrend"
    else:
        tech["trend"] = "Sideways"
    return tech


def _data_quality(screener_data: dict, ohlc_data: dict, hist_data: list) -> dict:
    """Per-layer freshness and source labels for the UI."""
    screener_ok = bool(
        screener_data.get("quarterly_results")
        or screener_data.get("pe_ratio") is not None
        or screener_data.get("company_name")
    )
    price_ok = bool(
        ohlc_data.get("last_price")
        or (hist_data and hist_data[-1].get("close") is not None)
    )
    bars = len(hist_data) if hist_data else 0
    return {
        "price": {
            "source": "Yahoo Finance",
            "freshness": "~15 min delayed",
            "ok": price_ok,
        },
        "fundamentals": {
            "source": "Screener.in" if screener_ok else "unavailable",
            "ok": screener_ok,
        },
        "history_bars": bars,
        "history_ok": bars >= 60,
    }


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
                    elif "operating profit" in rn or "ebitda" in rn:
                        q["ebitda"] = safe_float(vals[i])
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


# ── news ─────────────────────────────────────────────────────────────────────

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


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/api/search")
async def search(q: str, limit: int = 15):
    """
    Autocomplete: NSE directory matches first (fast, full company names),
    then Yahoo Finance results for anything the local list misses.
    """
    local, yahoo = await asyncio.gather(
        symbol_resolver.search_local(q, limit=8),
        price.search_instruments(q, limit),
    )
    seen = {item["symbol"] for item in local}
    merged = local + [y for y in yahoo if y["symbol"] not in seen]
    return merged[:limit]


@app.post("/api/resolve")
async def resolve_symbols(item: dict):
    """
    Resolve free-text queries (company names or symbols) to NSE symbols.
    Body: {"queries": ["Aegis Logistics Ltd", "DELHIVERY", ...]}
    Returns [{"query", "symbol"|null, "name", "exchange", "method"}].
    """
    queries = item.get("queries")
    if not isinstance(queries, list) or not queries:
        raise HTTPException(status_code=400, detail="queries (non-empty list) required")
    return await symbol_resolver.resolve_many([str(q) for q in queries[:80]])


@app.get("/api/stock/{symbol}")
async def get_stock(symbol: str, exchange: str = "NSE"):
    symbol = symbol.upper().strip()
    instrument = f"{exchange}:{symbol}"

    screener_task = fetch_screener(symbol)
    hist_task = price.get_historical(instrument, days=300)
    ohlc_task = price.get_ohlc(instrument)

    screener_data, hist_data, ohlc_data = await asyncio.gather(
        screener_task, hist_task, ohlc_task
    )

    company_name = screener_data.get("company_name", symbol)
    news = await fetch_news(symbol, company_name)

    tech = _compute_technicals(hist_data)
    live_price = ohlc_data.get("last_price") or tech.get("current_price") or screener_data.get("screener_price")

    price_history = [
        {"date": c.get("date"), "close": c.get("close"), "volume": c.get("volume")}
        for c in hist_data if c.get("close") is not None
    ]

    return {
        "symbol": symbol,
        "exchange": exchange,
        "company_name": company_name,
        "price_history": price_history,
        "live_price": live_price,
        "day_change": ohlc_data.get("day_change"),
        "day_change_pct": ohlc_data.get("day_change_pct"),
        "open": ohlc_data.get("open"),
        "high": ohlc_data.get("high"),
        "low": ohlc_data.get("low"),
        "week_high_52": screener_data.get("week_high_52"),
        "week_low_52": screener_data.get("week_low_52"),
        "market_cap": screener_data.get("market_cap"),
        "pe_ratio": screener_data.get("pe_ratio"),
        "pb_ratio": screener_data.get("pb_ratio"),
        "roe": screener_data.get("roe"),
        "roce": screener_data.get("roce"),
        "dividend_yield": screener_data.get("dividend_yield"),
        "debt_to_equity": screener_data.get("debt_to_equity"),
        "book_value": screener_data.get("book_value"),
        "quarterly_results": screener_data.get("quarterly_results", []),
        "shareholding": screener_data.get("shareholding", {}),
        "technicals": tech,
        "news": news,
        "data_quality": _data_quality(screener_data, ohlc_data, hist_data),
    }


@app.get("/api/stock/{symbol}/plan")
async def get_stock_plan(symbol: str, exchange: str = "NSE"):
    """
    Trade Decision Engine: swing + positional trade plans (verdict, entry zone,
    stop, targets, R:R) anchored to chart structure, plus the conviction
    dossier — historical base rates of the detected setup on this stock's own
    ~5y history, expected value, NIFTY regime, relative strength, trend
    template, and the weighted bull/bear evidence ledger. Degrades gracefully —
    errors return {"error": ...} with HTTP 200.
    """
    symbol = symbol.upper().strip()
    instrument = f"{exchange}:{symbol}"

    screener_data, hist_data, nifty, yf_funds = await asyncio.gather(
        fetch_screener_full(symbol),
        price.get_historical(instrument, days=1250),   # ~5y for base rates
        price.get_index_historical("^NSEI", days=400),
        price.get_fundamentals(instrument),
    )

    screener_data = enrich_with_yf_fundamentals(screener_data, yf_funds)
    quant = quant_engine.compute_all(screener_data) if screener_data else None
    plans = decision_engine.build_trade_plans(hist_data, screener_data, quant)
    if "error" not in plans:
        plans["dossier"] = conviction_engine.build_dossier(
            hist_data, plans, quant, nifty
        )
        plans["synthesis"] = conviction_engine.synthesize_verdicts(plans, quant)
    plans["symbol"] = symbol
    plans["exchange"] = exchange
    plans["company_name"] = (screener_data or {}).get("company_name", symbol)
    return plans


@app.get("/api/market-regime")
async def get_market_regime():
    """NIFTY tape check: Risk-On / Neutral / Risk-Off with guidance (cached 30m)."""
    nifty = await price.get_index_historical("^NSEI", days=400)
    return conviction_engine.market_regime(nifty)


@app.get("/api/ltp/{symbol}")
async def ltp(symbol: str, exchange: str = "NSE"):
    return await price.get_ltp(f"{exchange}:{symbol.upper()}")


@app.get("/api/watchlist")
async def get_watchlist():
    return load_json(WATCHLIST_FILE, [])


@app.post("/api/watchlist")
async def add_watchlist(item: dict):
    wl = load_json(WATCHLIST_FILE, [])
    sym = item.get("symbol", "").upper()
    exc = item.get("exchange", "NSE")
    if sym and not any(w["symbol"] == sym for w in wl):
        wl.append({"symbol": sym, "exchange": exc, "name": item.get("name", sym)})
        save_json(WATCHLIST_FILE, wl)
    return wl


@app.delete("/api/watchlist/{symbol}")
async def remove_watchlist(symbol: str):
    wl = [w for w in load_json(WATCHLIST_FILE, []) if w["symbol"] != symbol.upper()]
    save_json(WATCHLIST_FILE, wl)
    return wl


@app.get("/api/watchlist/prices")
async def watchlist_prices():
    wl = load_json(WATCHLIST_FILE, [])
    if not wl:
        return {}
    instruments = [f"{w['exchange']}:{w['symbol']}" for w in wl]
    return await price.get_ltp_multiple(instruments)


# ── alerts ────────────────────────────────────────────────────────────────────

@app.get("/api/alerts")
async def get_alerts(symbol: Optional[str] = None):
    alerts = alert_store.load_alerts()
    if symbol:
        alerts = [a for a in alerts if a["symbol"] == symbol.upper()]
    return alerts


@app.post("/api/alerts")
async def create_alert(item: dict):
    sym = item.get("symbol", "").upper().strip()
    level = item.get("level")
    direction = item.get("direction")
    if not sym or level is None or direction not in ("above", "below"):
        raise HTTPException(status_code=400,
                            detail="symbol, level and direction ('above'|'below') required")
    return alert_store.create_custom(
        sym, item.get("exchange", "NSE"), level, direction, item.get("label", "")
    )


@app.post("/api/alerts/from-plan")
async def create_alerts_from_plan(item: dict):
    sym = item.get("symbol", "").upper().strip()
    horizon = item.get("horizon")
    plan = item.get("plan")
    if not sym or horizon not in ("swing", "positional") or not isinstance(plan, dict):
        raise HTTPException(status_code=400,
                            detail="symbol, horizon ('swing'|'positional') and plan required")
    return alert_store.create_from_plan(sym, item.get("exchange", "NSE"), horizon, plan)


@app.delete("/api/alerts/{alert_id}")
async def remove_alert(alert_id: str):
    if not alert_store.delete_alert(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}


@app.post("/api/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str):
    if not alert_store.acknowledge(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}


@app.get("/api/watchlist/pulse")
async def watchlist_pulse():
    """
    Watchlist prices + alert check in one call (polled by the sidebar every
    30s). Fetches LTPs for watchlist symbols plus any symbol with an active
    alert, flips crossed alerts, and returns the newly-triggered ones.
    Alerts run on delayed Yahoo Finance data — advisory only.
    """
    wl = load_json(WATCHLIST_FILE, [])
    instruments = {f"{w['exchange']}:{w['symbol']}" for w in wl}
    instruments |= {f"{exc}:{sym}" for sym, exc in alert_store.symbols_with_active_alerts()}

    prices = await price.get_ltp_multiple(sorted(instruments)) if instruments else {}
    newly_triggered = alert_store.check_alerts(prices)

    return {
        "prices": prices,
        "newly_triggered": newly_triggered,
        "alerts_by_symbol": alert_store.summary_by_symbol(),
    }


# ── Annual data scraping (for /alpha endpoint) ────────────────────────────────

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


async def fetch_screener_full(symbol: str) -> dict:
    """
    One HTTP request to Screener → returns both the standard top-ratio dict
    AND the annual P&L / balance sheet / cash flow in a single merged dict.
    """
    for url in [
        f"https://www.screener.in/company/{symbol}/consolidated/",
        f"https://www.screener.in/company/{symbol}/",
    ]:
        try:
            async with httpx.AsyncClient(timeout=22, follow_redirects=True) as c:
                r = await c.get(url, headers=SCRAPE_HEADERS)
            if r.status_code == 200:
                base   = parse_screener(r.text)
                annual = parse_screener_annual(r.text)
                return {**base, **annual}
            print(f"[screener_full] HTTP {r.status_code} from {url}"
                  + (" — RATE LIMITED" if r.status_code == 429 else ""))
        except Exception as e:
            print(f"[screener_full] {type(e).__name__}: {e} ({url})")
    return {}


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


# ── /api/stock/{symbol}/alpha  ────────────────────────────────────────────────

@app.get("/api/stock/{symbol}/alpha")
async def get_stock_alpha(symbol: str, exchange: str = "NSE"):
    """
    Mega endpoint: base stock data + annual financials + Piotroski/Altman/DuPont
    + BSE corporate announcements + finance sentiment + Gemini alpha thesis.

    All layers degrade gracefully — if yfinance has no data, technicals are
    empty; if GEMINI_API_KEY is absent, ai_thesis contains an explanatory
    message; if BSE is down, announcements are [].
    """
    symbol     = symbol.upper().strip()
    instrument = f"{exchange}:{symbol}"

    # ── Parallel I/O (all independent) ───────────────────────────────────────
    (
        screener_data,
        hist_data,
        ohlc_data,
        bse_announcements,
        nifty_data,
        yf_funds,
    ) = await asyncio.gather(
        fetch_screener_full(symbol),
        price.get_historical(instrument, days=1250),
        price.get_ohlc(instrument),
        qualitative_engine.get_bse_announcements(symbol),
        price.get_index_historical("^NSEI", days=400),
        price.get_fundamentals(instrument),
    )

    screener_data = enrich_with_yf_fundamentals(screener_data, yf_funds)
    company_name = screener_data.get("company_name", symbol)

    # ── News ──────────────────────────────────────────────────────────────────
    news = await fetch_news(symbol, company_name)

    # ── Technicals ────────────────────────────────────────────────────────────
    tech = _compute_technicals(hist_data)

    # ── Quant scores ──────────────────────────────────────────────────────────
    quant_scores = quant_engine.compute_all(screener_data)

    # ── Trade decision plans (swing + positional) + conviction dossier ───────
    trade_plans = decision_engine.build_trade_plans(
        hist_data, screener_data, quant_scores
    )
    if "error" not in trade_plans:
        trade_plans["dossier"] = conviction_engine.build_dossier(
            hist_data, trade_plans, quant_scores, nifty_data
        )

    # ── Sentiment: merge news + BSE announcements ─────────────────────────────
    # Normalise BSE announcements so score_corpus can read "title" or "headline"
    ann_as_news = [
        {"title": ann.get("headline", ""), **ann}
        for ann in bse_announcements
    ]
    sentiment_data = qualitative_engine.score_corpus(news + ann_as_news)

    # Also attach per-item sentiment to BSE announcements
    bse_scored = [
        {**ann, **qualitative_engine.score_text(ann.get("headline", ""))}
        for ann in bse_announcements
    ]

    # ── AI thesis (slowest call — done last) ──────────────────────────────────
    ai_thesis = await ai_engine.generate_alpha_thesis(
        ticker         = symbol,
        raw_financials = screener_data,
        quant_scores   = quant_scores,
        sentiment_data = sentiment_data,
        trade_plans    = trade_plans,
    )

    # ── Bottom Line: reconcile trade / business / AI lenses ──────────────────
    if "error" not in trade_plans:
        trade_plans["synthesis"] = conviction_engine.synthesize_verdicts(
            trade_plans, quant_scores, ai_thesis
        )

    live_price = (
        ohlc_data.get("last_price")
        or tech.get("current_price")
        or screener_data.get("screener_price")
    )

    # ── Unified response ──────────────────────────────────────────────────────
    return {
        # ── identity ──────────────────────────────────────────────────────────
        "symbol":        symbol,
        "exchange":      exchange,
        "company_name":  company_name,

        # ── price ─────────────────────────────────────────────────────────────
        "live_price":     live_price,
        "day_change":     ohlc_data.get("day_change"),
        "day_change_pct": ohlc_data.get("day_change_pct"),
        "open":           ohlc_data.get("open"),
        "high":           ohlc_data.get("high"),
        "low":            ohlc_data.get("low"),

        # ── fundamental ratios ────────────────────────────────────────────────
        "week_high_52":   screener_data.get("week_high_52"),
        "week_low_52":    screener_data.get("week_low_52"),
        "market_cap":     screener_data.get("market_cap"),
        "pe_ratio":       screener_data.get("pe_ratio"),
        "pb_ratio":       screener_data.get("pb_ratio"),
        "roe":            screener_data.get("roe"),
        "roce":           screener_data.get("roce"),
        "dividend_yield": screener_data.get("dividend_yield"),
        "debt_to_equity": screener_data.get("debt_to_equity"),
        "book_value":     screener_data.get("book_value"),

        # ── detailed financials ───────────────────────────────────────────────
        "quarterly_results": screener_data.get("quarterly_results", []),
        "shareholding":      screener_data.get("shareholding", {}),
        "annual_pl":         screener_data.get("annual_pl", []),
        "annual_bs":         screener_data.get("annual_bs", []),
        "annual_cf":         screener_data.get("annual_cf", []),

        # ── technicals ────────────────────────────────────────────────────────
        "technicals": tech,

        # ── news ──────────────────────────────────────────────────────────────
        "news": news,

        # ── quantitative scores ───────────────────────────────────────────────
        "quant": quant_scores,
        "fundamentals_source": screener_data.get("fundamentals_source", "screener"),

        # ── trade decision plans ──────────────────────────────────────────────
        "trade_plans": trade_plans,

        # ── qualitative / sentiment ───────────────────────────────────────────
        "bse_announcements": bse_scored,
        "sentiment":         sentiment_data,

        # ── AI alpha thesis ───────────────────────────────────────────────────
        "alpha_thesis": ai_thesis,
    }


# ── Batch swing-trading screener ──────────────────────────────────────────────

def _json_clean(obj):
    """Replace NaN/Inf with None recursively — json.dumps emits bare NaN
    (invalid JSON) and the browser's JSON.parse rejects the whole payload."""
    if isinstance(obj, float):
        return None if (obj != obj or obj in (float("inf"), float("-inf"))) else obj
    if isinstance(obj, dict):
        return {k: _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_clean(v) for v in obj]
    return obj


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(_json_clean(obj))}\n\n"


def _screen_row(symbol: str, sdata: dict, quant: dict, pf: dict) -> dict:
    """Flatten Screener fundamentals + quant scores + price factors into one row."""
    annual_pl = sdata.get("annual_pl", [])
    annual_bs = sdata.get("annual_bs", [])
    pl = annual_pl[-1] if annual_pl else {}
    bs = annual_bs[-1] if annual_bs else {}

    sf   = quant_engine._sf
    mcap = quant_engine._parse_mc_cr(sdata.get("market_cap"))
    ebit = quant_engine._ebit(pl)
    borr = sf(bs.get("borrowings"))

    # Earnings yield = EBIT / EV (EV = market cap + debt)
    ey = None
    if ebit is not None and mcap:
        ev = mcap + (borr or 0)
        if ev > 0:
            ey = ebit / ev

    pio = quant.get("piotroski", {})
    alt = quant.get("altman", {})
    ben = quant.get("beneish", {})

    return {
        "symbol":          symbol,
        "company_name":    sdata.get("company_name", symbol),
        "market_cap_cr":   mcap,
        "pe_ratio":        sf(sdata.get("pe_ratio")),
        "pb_ratio":        sf(sdata.get("pb_ratio")),
        "roe":             sf(sdata.get("roe")),
        "roce":            sf(sdata.get("roce")),
        "debt_to_equity":  sf(sdata.get("debt_to_equity")),
        "dividend_yield":  sf(sdata.get("dividend_yield")),
        "earnings_yield":  ey,
        "piotroski_score": pio.get("score"),
        "altman_z":        alt.get("z_score"),
        "altman_zone":     alt.get("zone"),
        "beneish_m":       ben.get("m_score"),
        "screener_price":  sf(sdata.get("screener_price")),
        **pf,   # price / momentum / technical factors (may be empty)
    }


def _plan_summary(plans: dict) -> dict:
    """Flatten the swing trade plan into screener-row columns."""
    sw = plans.get("swing") if isinstance(plans, dict) else None
    if not sw:
        return {"plan_verdict": None}
    entry = sw.get("entry") or {}
    stop  = sw.get("stop") or {}
    targets = sw.get("targets") or []
    return {
        "plan_verdict":     sw.get("verdict"),
        "plan_setup_label": sw.get("setup_label"),
        "plan_entry_low":   entry.get("low"),
        "plan_entry_high":  entry.get("high"),
        "plan_stop":        stop.get("price"),
        "plan_t1":          targets[0]["price"] if targets else None,
        "plan_rr":          sw.get("risk_reward"),
    }


@app.get("/api/screen-stream")
async def screen_stream(symbols: str):
    """
    SSE batch screener. Pass symbols as comma/space/newline separated list.
    Streams {type:'log'|'result'|'done'|'error'} events; the 'result' event
    carries the full cross-sectionally ranked list.
    """
    syms, seen = [], set()
    for s in symbols.replace("\n", ",").replace(" ", ",").split(","):
        s = s.strip().upper()
        if s and s not in seen:
            seen.add(s)
            syms.append(s)
    syms = syms[:60]

    if not syms:
        raise HTTPException(status_code=400, detail="No symbols provided")

    async def _gen():
        yield _sse({"type": "log", "text": f"Screening {len(syms)} stocks..."})

        sem = asyncio.Semaphore(3)

        async def fetch_one(sym: str):
            async with sem:
                sdata = await fetch_screener_full(sym)
                hist  = await price.get_historical(f"NSE:{sym}", days=450)
                return sym, sdata, hist

        rows, done = [], 0
        for coro in asyncio.as_completed([fetch_one(s) for s in syms]):
            sym, sdata, hist = await coro
            done += 1
            if not sdata:
                yield _sse({"type": "log", "text": f"SKIP {sym} - no Screener data ({done}/{len(syms)})"})
                continue
            try:
                quant = quant_engine.compute_all(sdata)
                pf    = swing_engine.compute_price_factors(hist)
                plans = decision_engine.build_trade_plans(hist, sdata, quant)
                rows.append({**_screen_row(sym, sdata, quant, pf),
                             **_plan_summary(plans)})
                pio = quant["piotroski"].get("score")
                z   = quant["altman"].get("z_score")
                yield _sse({"type": "log",
                            "text": f"OK {sym:<14} Pio={pio}  Z={z}  "
                                    f"{'tech ok' if pf else 'no price data'}  ({done}/{len(syms)})"})
            except Exception as e:
                yield _sse({"type": "log", "text": f"ERR {sym}: {e} ({done}/{len(syms)})"})

        if not rows:
            yield _sse({"type": "error", "text": "No stocks could be fetched - check symbols."})
            return

        yield _sse({"type": "log", "text": f"Ranking {len(rows)} stocks cross-sectionally..."})
        ranked = swing_engine.cross_sectional_rank(rows)
        yield _sse({"type": "result", "data": ranked, "technicals_available": True})
        yield _sse({"type": "done", "text": "Screen complete"})

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
