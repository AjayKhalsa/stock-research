"""
qualitative_engine.py
Two responsibilities:
  1. Scrape latest corporate announcements from BSE India's public API.
  2. Score any headline / text corpus with a finance-domain rule-based
     sentiment engine (returns a float in [-1.0, +1.0]).

No heavy NLP libraries required — pure Python + httpx.
"""

from __future__ import annotations
import asyncio
import httpx
from typing import Optional

# ── HTTP headers that satisfy BSE's CORS/UA checks ───────────────────────────

_BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin":          "https://www.bseindia.com",
    "Referer":         "https://www.bseindia.com/",
}

# ── Finance-domain sentiment lexicon ─────────────────────────────────────────
# Words are matched case-insensitively as substrings.
# Weights: STRONG_POS=+2, POS=+1, NEG=-1, STRONG_NEG=-2.5
# Red-flag phrases trigger an additional floor on the score.

_STRONG_POS = [
    "record profit", "record revenue", "record high", "all-time high",
    "strong results", "beat estimates", "above expectations",
    "dividend declared", "interim dividend", "special dividend",
    "buyback", "share repurchase", "capacity expansion",
    "major contract", "large order", "strategic partnership",
    "debt free", "zero debt", "debt reduction", "credit upgrade",
    "rating upgrade", "robust growth", "stellar performance",
]

_POS = [
    "profit", "growth", "revenue increase", "expansion", "acquisition",
    "award", "approval", "new order", "investment", "fund raise",
    "merger", "collaboration", "improvement", "recovery", "turnaround",
    "positive", "increase", "rises", "gain", "upgrade", "outperform",
    "buy", "strong", "beat", "better than", "progress", "launches",
    "wins", "secures", "ramps up", "quarterly profit", "net income",
]

_NEG = [
    "loss", "decline", "fall", "drop", "miss", "below expectations",
    "concern", "weak", "slowdown", "pressure", "headwind", "challenge",
    "lower", "decrease", "reduce", "cut", "warning", "caution",
    "downgrade", "underperform", "sell", "uncertain", "volatility",
    "disappoints", "disappointing", "shortfall", "contraction",
    "margin compression", "cost pressures",
]

_STRONG_NEG = [
    "fraud", "scam", "money laundering", "financial irregularity",
    "default", "defaults on", "insolvency", "bankruptcy", "goes bankrupt",
    "sebi order", "sebi notice", "sebi action", "sebi penalty",
    "nse query", "bse query", "stock exchange query",
    "regulatory action", "show cause notice",
    "arrest", "arrested", "cbi probe", "ed raid", "income tax raid",
    "it raid", "enforcement directorate",
    "insider trading", "forensic audit", "qualified opinion",
    "going concern", "material weakness", "qualified accounts",
    "promoter pledge", "promoters pledge", "pledge invoked",
    "promoter selling", "promoters selling stake",
]

# Anything matching these pushes score ≤ -0.3 regardless of positive hits
_RED_FLAG_TRIGGERS = [
    "fraud", "raid", "investigation", "sebi", "cbi",
    "enforcement directorate", "money laundering",
    "default", "bankrupt", "arrest", "probe", "scam",
    "pledge invoked", "forensic", "going concern",
]


# ── Sentiment scorer ──────────────────────────────────────────────────────────

def score_text(text: str) -> dict:
    """
    Score a single headline / sentence.

    Returns:
        score          float  -1.0 … +1.0
        label          "Positive" | "Negative" | "Neutral"
        red_flag       bool
        matched_signals list[str]  top matched phrases (debugging aid)
    """
    t = text.lower()
    raw = 0.0
    matched: list[str] = []

    for phrase in _STRONG_POS:
        if phrase in t:
            raw += 2.0
            matched.append(f"+2: {phrase}")

    for phrase in _POS:
        if phrase in t:
            raw += 1.0
            matched.append(f"+1: {phrase}")

    for phrase in _NEG:
        if phrase in t:
            raw -= 1.0
            matched.append(f"-1: {phrase}")

    for phrase in _STRONG_NEG:
        if phrase in t:
            raw -= 2.5
            matched.append(f"-2.5: {phrase}")

    red_flag = any(trigger in t for trigger in _RED_FLAG_TRIGGERS)

    # Normalise: clamp raw score to [-1, +1] by comparing against
    # a fixed scale rather than item count (prevents gaming with long text).
    scale = max(abs(raw), 5.0)
    score = max(-1.0, min(1.0, raw / scale))

    if red_flag:
        score = min(score, -0.3)   # always net-negative when red-flag triggers

    if   score >  0.15: label = "Positive"
    elif score < -0.15: label = "Negative"
    else:               label = "Neutral"

    return {
        "score":           round(score, 3),
        "label":           label,
        "red_flag":        red_flag,
        "matched_signals": matched[:6],   # keep top 6 for readability
    }


def score_corpus(items: list[dict]) -> dict:
    """
    Score a list of news / announcement dicts.
    Each item must have at least a "title" or "headline" key.

    Returns aggregate sentiment metrics plus individual scored items.
    """
    if not items:
        return {
            "composite_score": 0.0,
            "composite_label": "Neutral",
            "positive": 0, "negative": 0, "neutral": 0, "red_flags": 0,
            "items": [],
        }

    scored: list[dict] = []
    for item in items:
        text = item.get("title") or item.get("headline") or ""
        s = score_text(text)
        scored.append({**item, **s})

    n   = len(scored)
    tot = sum(i["score"] for i in scored)
    composite = round(tot / n, 3)

    if   composite >  0.10: comp_label = "Positive"
    elif composite < -0.10: comp_label = "Negative"
    else:                   comp_label = "Neutral"

    return {
        "composite_score": composite,
        "composite_label": comp_label,
        "positive":  sum(1 for i in scored if i["label"] == "Positive"),
        "negative":  sum(1 for i in scored if i["label"] == "Negative"),
        "neutral":   sum(1 for i in scored if i["label"] == "Neutral"),
        "red_flags": sum(1 for i in scored if i["red_flag"]),
        "items":     scored,
    }


# ── BSE corporate announcement scraper ───────────────────────────────────────

async def _get_bse_code(symbol: str) -> Optional[str]:
    """
    Resolve NSE trading symbol → BSE scrip code via BSE autocomplete API.
    Returns None on any failure.
    """
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(
                "https://api.bseindia.com/BseIndiaAPI/api/AutoCompletion/w",
                params={"Type": "S", "Value": symbol},
                headers=_BSE_HEADERS,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            if not isinstance(data, list) or not data:
                return None
            # Prefer exact NSE symbol match, else take first result
            for item in data:
                if item.get("ShortName", "").upper() == symbol.upper():
                    return str(item["Scrip_Cd"])
            return str(data[0]["Scrip_Cd"])
    except Exception as e:
        print(f"[bse_code] {e}")
        return None


async def get_bse_announcements(symbol: str, limit: int = 10) -> list[dict]:
    """
    Fetch latest corporate announcements from BSE for a given NSE symbol.

    Each returned dict contains:
        headline  str
        date      str
        category  str
        source    "BSE"
        link      str (direct PDF link when available)
        bse_code  str

    Returns empty list gracefully on any BSE API failure.
    """
    bse_code = await _get_bse_code(symbol)
    if not bse_code:
        print(f"[bse] Could not resolve BSE code for {symbol}")
        return []

    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as c:
            r = await c.get(
                "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
                params={
                    "pageno":     "1",
                    "Category":   "-1",
                    "subcategory":"-1",
                    "scrip_cd":   bse_code,
                    "strdate":    "",
                    "enddate":    "",
                    "type":       "C",
                    "offset":     "0",
                },
                headers=_BSE_HEADERS,
            )

        if r.status_code != 200:
            print(f"[bse_ann] HTTP {r.status_code} for {symbol} (code {bse_code})")
            return []

        payload = r.json()
        # BSE returns either {"Table": [...]} or {"data": [...]}
        rows = (
            payload.get("Table")
            or payload.get("Table1")
            or payload.get("data")
            or []
        )

        results: list[dict] = []
        for row in rows[:limit]:
            headline = (
                row.get("HEADLINE")
                or row.get("headline")
                or row.get("NEWSSUB")
                or row.get("subject")
                or ""
            ).strip()
            date = (
                row.get("NEWS_DT")
                or row.get("DT_TM")
                or row.get("date")
                or ""
            )
            category = (
                row.get("CATEGORYNAME")
                or row.get("category")
                or row.get("SUBCATNAME")
                or ""
            )
            attachment = row.get("ATTACHMENTNAME") or row.get("filename") or ""
            link = (
                f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attachment}"
                if attachment else ""
            )

            results.append({
                "headline": headline,
                "date":     date,
                "category": category,
                "source":   "BSE",
                "link":     link,
                "bse_code": bse_code,
            })

        return results

    except Exception as e:
        print(f"[bse_ann] {e}")
        return []
