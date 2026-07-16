"""
stock_service.py — business logic for the stock endpoints. Routes call these
builders; no HTTP concerns in here, no business logic in the routers.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

import price_service as price
import quant_engine
import qualitative_engine
import ai_engine
import swing_engine
import decision_engine
import conviction_engine
from indicators import rsi as calc_rsi, sma as _sma
from screener_scraper import (
    fetch_news,
    fetch_screener,
    fetch_screener_full,
)


def calc_ma(prices: list, period: int) -> Optional[float]:
    v = _sma(prices, period)
    return round(v, 2) if v is not None else None


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


async def build_stock_payload(symbol: str, exchange: str = "NSE"):
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


async def build_plan_payload(symbol: str, exchange: str = "NSE"):
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


async def build_alpha_payload(symbol: str, exchange: str = "NSE"):
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
