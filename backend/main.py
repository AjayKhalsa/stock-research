from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import json, os, asyncio
from typing import Optional
import feedparser, httpx
from bs4 import BeautifulSoup
import price_service as price
import quant_engine
import qualitative_engine
import ai_engine
import swing_engine

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
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    ag = sum(gains) / period
    al = sum(losses) / period
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
        except Exception as e:
            print(f"[screener] {e}")
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
    return await price.search_instruments(q, limit)


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
    }


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
        except Exception as e:
            print(f"[screener_full] {e}")
    return {}


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
    ) = await asyncio.gather(
        fetch_screener_full(symbol),
        price.get_historical(instrument, days=300),
        price.get_ohlc(instrument),
        qualitative_engine.get_bse_announcements(symbol),
    )

    company_name = screener_data.get("company_name", symbol)

    # ── News ──────────────────────────────────────────────────────────────────
    news = await fetch_news(symbol, company_name)

    # ── Technicals ────────────────────────────────────────────────────────────
    tech = _compute_technicals(hist_data)

    # ── Quant scores ──────────────────────────────────────────────────────────
    quant_scores = quant_engine.compute_all(screener_data)

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

        # ── qualitative / sentiment ───────────────────────────────────────────
        "bse_announcements": bse_scored,
        "sentiment":         sentiment_data,

        # ── AI alpha thesis ───────────────────────────────────────────────────
        "alpha_thesis": ai_thesis,
    }


# ── Batch swing-trading screener ──────────────────────────────────────────────

def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _screen_row(symbol: str, sdata: dict, quant: dict, pf: dict) -> dict:
    """Flatten Screener fundamentals + quant scores + price factors into one row."""
    annual_pl = sdata.get("annual_pl", [])
    annual_bs = sdata.get("annual_bs", [])
    pl = annual_pl[-1] if annual_pl else {}
    bs = annual_bs[-1] if annual_bs else {}

    sf   = quant_engine._sf
    mcap = quant_engine._parse_mc_cr(sdata.get("market_cap"))
    ebit = sf(pl.get("ebitda"))
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
                rows.append(_screen_row(sym, sdata, quant, pf))
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
