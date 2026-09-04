"""Deterministic CFO-quality + swing-ranking model for the daily workspace.

This module is intentionally pure: no network, database, or AI calls.  Every
recommendation can therefore be reproduced, unit tested, and audited from the
snapshot evidence saved beside it.  AI is allowed to explain or downgrade the
result later; it never edits these calculations or bypasses a gate.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Optional

import decision_engine
import price_action
import quant_engine
import swing_engine
import swing_features

MODEL_VERSION = "swing-v1.5.0"
MIN_SESSIONS = 252
MIN_PRICE = 20.0
MIN_MEDIAN_TRADED_VALUE = 5_00_00_000.0  # ₹5 crore

FINANCIAL_SECTOR_TERMS = (
    "bank", "banking", "financial services", "finance", "nbfc",
    "insurance", "life insurance", "general insurance",
)

SCORE_WEIGHTS = {
    "setup": 0.20,
    "relative_strength": 0.10,
    "volume": 0.10,
    "business_quality": 0.07,
    "earnings_momentum": 0.15,
    "overhead_supply": 0.10,
    "tradeability": 0.10,
    "move_potential": 0.08,
    "sector_regime": 0.05,
    "market_regime": 0.05,
}

ACTIONS = {"BUY_NOW", "WAIT_FOR_ENTRY", "WATCH", "AVOID", "DATA_INSUFFICIENT"}


def market_cap_bucket(market_cap_cr: Optional[float]) -> str:
    """Stable size proxy retained at signal time for later validation.

    SEBI's official labels are rank-based and require a complete point-in-time
    market-cap universe. Until that archive exists, explicit fixed crore bands
    are more reproducible than applying today's ranks to an old signal.
    """
    if market_cap_cr is None or not math.isfinite(market_cap_cr) or market_cap_cr <= 0:
        return "unknown"
    if market_cap_cr >= 20_000:
        return "large_proxy"
    if market_cap_cr >= 5_000:
        return "mid_proxy"
    return "small_proxy"


def _number(value: Any) -> Optional[float]:
    try:
        if value in (None, "", "-", "—", "N/A"):
            return None
        number = float(str(value).replace(",", "").replace("%", "").replace("Cr", "").strip())
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _latest(rows: list[dict]) -> dict:
    return rows[-1] if rows else {}


def _previous(rows: list[dict]) -> dict:
    return rows[-2] if len(rows) > 1 else {}


def is_financial_company(fundamentals: dict) -> bool:
    text = f"{fundamentals.get('sector', '')} {fundamentals.get('industry', '')}".lower()
    return any(term in text for term in FINANCIAL_SECTOR_TERMS)


def eligibility(candles: list[dict]) -> dict:
    """Apply the investable-universe rules to an adjusted daily series."""
    usable = [c for c in candles if _number(c.get("close")) is not None]
    reasons: list[str] = []
    if len(usable) < MIN_SESSIONS:
        reasons.append(f"Only {len(usable)} usable sessions; {MIN_SESSIONS} required")
    price = _number(usable[-1].get("close")) if usable else None
    if price is None or price <= MIN_PRICE:
        reasons.append(f"Latest price must be above ₹{MIN_PRICE:.0f}")
    traded = []
    for candle in usable[-20:]:
        close, volume = _number(candle.get("close")), _number(candle.get("volume"))
        if close is not None and volume is not None and volume > 0:
            traded.append(close * volume)
    median_value = median(traded) if len(traded) >= 10 else None
    if median_value is None or median_value < MIN_MEDIAN_TRADED_VALUE:
        reasons.append("Median 20-session traded value is below ₹5 crore or unavailable")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "sessions": len(usable),
        "price": round(price, 2) if price is not None else None,
        "median_traded_value": round(median_value, 0) if median_value is not None else None,
    }


def price_reconciliation(yahoo_close: Optional[float], official_close: Optional[float],
                         yahoo_date: Optional[str] = None,
                         official_date: Optional[str] = None) -> dict:
    if yahoo_close is None or official_close is None:
        return {
            "status": "official_pending",
            "difference_pct": None,
            "recommendations_allowed": False,
            "detail": "Official NSE close unavailable; analysis remains research-only",
        }
    if yahoo_date and official_date and str(yahoo_date)[:10] != str(official_date)[:10]:
        return {
            "status": "session_mismatch",
            "difference_pct": None,
            "recommendations_allowed": False,
            "detail": f"Price sources refer to different sessions ({yahoo_date} vs {official_date})",
        }
    difference = abs(yahoo_close / official_close - 1.0) * 100 if official_close else 999.0
    conflict = difference > 1.0
    return {
        "status": "conflict" if conflict else "matched",
        "difference_pct": round(difference, 3),
        "recommendations_allowed": not conflict,
        "detail": "Price sources differ by more than 1%" if conflict else "Yahoo and NSE closes reconciled",
    }


def _cash_conversion(fundamentals: dict) -> Optional[float]:
    cfo = _number(_latest(fundamentals.get("annual_cf") or []).get("cfo"))
    pat = _number(_latest(fundamentals.get("annual_pl") or []).get("net_profit"))
    if cfo is None or pat is None or pat == 0:
        return None
    return cfo / abs(pat)


def _growth(latest: Optional[float], prior: Optional[float]) -> Optional[float]:
    if latest is None or prior in (None, 0):
        return None
    return (latest / abs(prior) - 1) * 100


def _average(values: list[Optional[float]]) -> Optional[float]:
    usable = [value for value in values if value is not None]
    return sum(usable) / len(usable) if usable else None


def _growth_score(yoy: Optional[float], qoq: Optional[float]) -> Optional[float]:
    """Normalize reported growth without letting one outlier dominate."""
    parts, weights = [], []
    if yoy is not None:
        parts.append(_clamp(50 + yoy * 1.25))
        weights.append(0.7)
    if qoq is not None:
        parts.append(_clamp(50 + qoq * 1.5))
        weights.append(0.3 if yoy is not None else 1.0)
    if not parts:
        return None
    return sum(value * weight for value, weight in zip(parts, weights)) / sum(weights)


def _margin_label(change_points: Optional[float]) -> str:
    if change_points is None:
        return "unavailable"
    if change_points >= 3:
        return "strong expansion"
    if change_points >= 0.75:
        return "expansion"
    if change_points > -0.75:
        return "stable"
    if change_points > -3:
        return "contraction"
    return "severe contraction"


def assess_earnings_momentum(fundamentals: dict) -> dict:
    """Point-in-time quarterly growth, margin direction, and acceleration.

    Screener quarter rows are stored oldest-to-newest.  YoY comparisons use
    Q0 versus Q-4 and acceleration compares that result with Q-1 versus Q-5.
    Missing observations stay missing; they never receive neutral credit.
    """
    rows = []
    for row in fundamentals.get("quarterly_results") or []:
        normalized = {
            "quarter": row.get("quarter"),
            "revenue": _number(row.get("revenue")),
            "ebitda": _number(row.get("ebitda")),
            "pat": _number(row.get("net_profit")),
            "ebitda_margin": _number(row.get("opm")),
        }
        if normalized["revenue"] is not None:
            if normalized["ebitda_margin"] is None and normalized["ebitda"] is not None \
                    and normalized["revenue"]:
                normalized["ebitda_margin"] = normalized["ebitda"] / normalized["revenue"] * 100
            if normalized["pat"] is not None and normalized["revenue"]:
                normalized["pat_margin"] = normalized["pat"] / normalized["revenue"] * 100
            else:
                normalized["pat_margin"] = None
            rows.append(normalized)

    if not rows:
        return {
            "score": 0.0, "coverage": 0.0, "status": "unavailable",
            "metrics": {}, "margin_direction": "unavailable",
            "sequences": {}, "cautions": ["Quarterly earnings history unavailable"],
        }

    q0 = rows[-1]
    q1 = rows[-2] if len(rows) >= 2 else {}
    q4 = rows[-5] if len(rows) >= 5 else {}
    q5 = rows[-6] if len(rows) >= 6 else {}
    metrics: dict[str, Optional[float]] = {}
    trend_scores = {}
    for metric in ("revenue", "ebitda", "pat"):
        metrics[f"{metric}_growth_yoy"] = _growth(q0.get(metric), q4.get(metric))
        metrics[f"{metric}_growth_qoq"] = _growth(q0.get(metric), q1.get(metric))
        prior_yoy = _growth(q1.get(metric), q5.get(metric))
        current_yoy = metrics[f"{metric}_growth_yoy"]
        metrics[f"{metric}_acceleration"] = (
            current_yoy - prior_yoy
            if current_yoy is not None and prior_yoy is not None else None
        )
        trend_scores[metric] = _growth_score(
            metrics[f"{metric}_growth_yoy"], metrics[f"{metric}_growth_qoq"]
        )

    for margin in ("ebitda_margin", "pat_margin"):
        comparison = q4.get(margin) if q4.get(margin) is not None else q1.get(margin)
        metrics[f"{margin}_change_yoy"] = (
            q0.get(margin) - comparison
            if q0.get(margin) is not None and comparison is not None else None
        )
        metrics[f"current_{margin}"] = q0.get(margin)

    margin_change = _average([
        metrics["ebitda_margin_change_yoy"], metrics["pat_margin_change_yoy"],
    ])
    margin_score = _clamp(50 + margin_change * 8) if margin_change is not None else None
    acceleration = _average([
        metrics["revenue_acceleration"], metrics["ebitda_acceleration"],
        metrics["pat_acceleration"],
    ])
    acceleration_score = _clamp(50 + acceleration * 1.25) if acceleration is not None else None

    cash_conversion = _cash_conversion(fundamentals)
    debt_equity = _number(fundamentals.get("debt_to_equity"))
    quality_parts = []
    if cash_conversion is not None:
        quality_parts.append(_clamp(35 + cash_conversion * 35))
    if debt_equity is not None and not is_financial_company(fundamentals):
        quality_parts.append(_clamp(85 - debt_equity * 30))
    cash_balance_score = _average(quality_parts)

    weighted = [
        (trend_scores["revenue"], 0.20),
        (trend_scores["ebitda"], 0.20),
        (trend_scores["pat"], 0.20),
        (margin_score, 0.20),
        (acceleration_score, 0.10),
        (cash_balance_score, 0.10),
    ]
    available = [(value, weight) for value, weight in weighted if value is not None]
    available_weight = sum(weight for _, weight in available)
    score = (sum(value * weight for value, weight in available) / available_weight
             if available_weight else 0.0)
    cautions = []
    direction = _margin_label(margin_change)
    if len(rows) < 5:
        cautions.append("Fewer than five quarters; YoY momentum is incomplete")
    if direction in {"contraction", "severe contraction"}:
        cautions.append(f"Margins show {direction}")

    rounded_metrics = {
        key: round(value, 2) if value is not None else None
        for key, value in metrics.items()
    }
    sequences = {
        metric: [{"quarter": row.get("quarter"), "value": row.get(metric)} for row in rows[-6:]]
        for metric in ("revenue", "ebitda", "pat", "ebitda_margin", "pat_margin")
    }
    return {
        "score": round(score, 1),
        "coverage": round(available_weight * 100, 1),
        "status": "full" if available_weight >= 0.8 else "partial",
        "metrics": rounded_metrics,
        "margin_direction": direction,
        "sequences": sequences,
        "cautions": cautions,
    }


def assess_cfo_health(fundamentals: dict, quant: Optional[dict] = None) -> dict:
    """Sector-aware financial controls; industrial distress rules never touch financials."""
    quant = quant or (quant_engine.compute_all(fundamentals) if fundamentals else {})
    completeness = fundamentals.get("data_completeness", "missing") if fundamentals else "missing"
    sector_model = "financial" if is_financial_company(fundamentals) else "non_financial"
    reasons, hard_blocks, cautions = [], [], []

    roe = _number(fundamentals.get("roe"))
    roce = _number(fundamentals.get("roce"))
    debt_equity = _number(fundamentals.get("debt_to_equity"))
    pe = _number(fundamentals.get("pe_ratio"))
    shareholding = fundamentals.get("shareholding") or {}
    pledge = _number(fundamentals.get("promoter_pledge") or fundamentals.get("pledged_percentage")
                     or shareholding.get("promoter_pledge"))
    conversion = _cash_conversion(fundamentals)
    pl, cf = fundamentals.get("annual_pl") or [], fundamentals.get("annual_cf") or []
    revenue_growth = _growth(_number(_latest(pl).get("revenue")), _number(_previous(pl).get("revenue")))
    profit_growth = _growth(_number(_latest(pl).get("net_profit")), _number(_previous(pl).get("net_profit")))

    pio = (quant.get("piotroski") or {}).get("score")
    alt = (quant.get("altman") or {}).get("z_score")
    beneish = (quant.get("beneish") or {}).get("m_score")

    if completeness == "missing" or not fundamentals:
        return {
            "score": 0.0, "gate": "data_insufficient", "sector_model": sector_model,
            "hard_blocks": [], "cautions": ["Critical financial evidence is missing"],
            "reasons": [], "completeness": completeness, "metrics": {},
            "diagnostics_applicable": {"piotroski": False, "altman": False, "beneish": False},
        }

    score = 50.0
    if sector_model == "financial":
        # Balance-sheet leverage is the product for lenders, so industrial
        # debt/equity and Altman thresholds are explicitly inapplicable.
        if roe is not None:
            score += _clamp((roe - 8) * 1.5, -15, 22)
            reasons.append(f"ROE {roe:.1f}%")
        else:
            cautions.append("ROE unavailable for financial-sector model")
        if profit_growth is not None:
            score += _clamp(profit_growth * 0.20, -12, 12)
        diagnostics = {"piotroski": False, "altman": False, "beneish": False}
    else:
        diagnostics = {"piotroski": True, "altman": True, "beneish": True}
        if roce is not None:
            score += _clamp((roce - 10) * 1.2, -15, 20)
            reasons.append(f"ROCE {roce:.1f}%")
        if roe is not None:
            score += _clamp((roe - 10) * 0.5, -8, 10)
        if conversion is not None:
            score += 12 if conversion >= 1 else 4 if conversion >= 0.75 else -18
            reasons.append(f"CFO/PAT {conversion:.2f}x")
        else:
            cautions.append("Cash conversion unavailable")
        if debt_equity is not None:
            score += 8 if debt_equity <= 0.5 else 2 if debt_equity <= 1.0 else -12
        if pio is not None:
            score += (pio - 4.5) * 2

        poor_cash = conversion is not None and conversion < 0.55
        if alt is not None and alt <= 1.1 and (poor_cash or (debt_equity or 0) > 1.5):
            hard_blocks.append(f"Confirmed distress: Altman {alt:.2f} with weak cash/leverage")
        if beneish is not None and beneish > -1.78 and poor_cash:
            hard_blocks.append(f"Manipulation warning: Beneish {beneish:.2f} plus poor cash conversion")

    if pledge is not None:
        if pledge >= 50:
            hard_blocks.append(f"Severe promoter pledge {pledge:.1f}%")
        elif pledge >= 20:
            cautions.append(f"Elevated promoter pledge {pledge:.1f}%")
            score -= 12
    if completeness == "partial":
        cautions.append("Partial financial evidence")
        score = min(score, 64)
    if revenue_growth is not None and revenue_growth < -15:
        cautions.append(f"Revenue contracted {abs(revenue_growth):.1f}%")
        score -= 8
    if profit_growth is not None and profit_growth < -20:
        cautions.append(f"Profit contracted {abs(profit_growth):.1f}%")
        score -= 8

    gate = "hard_block" if hard_blocks else "caution" if cautions else "pass"
    return {
        "score": round(_clamp(score), 1), "gate": gate, "sector_model": sector_model,
        "hard_blocks": hard_blocks, "cautions": cautions, "reasons": reasons,
        "completeness": completeness,
        "metrics": {"roe": roe, "roce": roce, "debt_to_equity": debt_equity,
                    "cfo_pat": round(conversion, 2) if conversion is not None else None,
                    "revenue_growth": round(revenue_growth, 1) if revenue_growth is not None else None,
                    "profit_growth": round(profit_growth, 1) if profit_growth is not None else None,
                    "pe": pe, "promoter_pledge": pledge,
                    "piotroski": pio, "altman": alt, "beneish": beneish},
        "diagnostics_applicable": diagnostics,
    }


def assess_data_confidence(candles: list[dict], fundamentals: dict,
                           fund_meta: dict, cfo: dict, earnings: dict,
                           reconciliation: dict) -> dict:
    """Measure source completeness, never the probability of trade success."""
    price_score = {
        "matched": 100.0,
        "official_pending": 55.0,
        "session_mismatch": 30.0,
        "conflict": 20.0,
    }.get(reconciliation.get("status"), 25.0)
    if len(candles) < MIN_SESSIONS:
        price_score = min(price_score, len(candles) / MIN_SESSIONS * 70)

    financial_score = earnings.get("coverage", 0) * 0.55
    financial_score += 15 if fundamentals.get("annual_pl") else 0
    financial_score += 10 if fundamentals.get("annual_cf") else 0
    core = [cfo.get("metrics", {}).get(key) for key in
            ("roe", "roce", "cfo_pat", "debt_to_equity")]
    financial_score += sum(value is not None for value in core) / len(core) * 20
    if cfo.get("completeness") == "full":
        financial_score += 5
    if fund_meta.get("stale"):
        financial_score -= 20
    financial_score = _clamp(financial_score)

    # A known calendar earns confidence.  Unknown event coverage is explicitly
    # incomplete; it is never interpreted as "no event risk".
    event_score = 100.0 if fundamentals.get("earnings_date") else 45.0
    overall = price_score * 0.50 + financial_score * 0.40 + event_score * 0.10
    label = "high" if overall >= 85 else "adequate" if overall >= 70 else "low"
    return {
        "overall": round(overall, 1),
        "label": label,
        "meaning": "Data completeness; not win probability",
        "price_data": round(price_score, 1),
        "financial_data": round(financial_score, 1),
        "event_data": round(event_score, 1),
        "ai_extraction": None,
    }


def _sessions_until(raw_date: Any, as_of: Any) -> Optional[int]:
    try:
        event = date.fromisoformat(str(raw_date)[:10])
        cursor = date.fromisoformat(str(as_of)[:10])
    except (TypeError, ValueError):
        return None
    if event < cursor:
        return None
    sessions = 0
    while cursor < event:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            sessions += 1
    return sessions


def assess_event_risk(fundamentals: dict, as_of: Any) -> dict:
    """Classify only known dated events; unknown coverage stays unknown."""
    events = []
    if fundamentals.get("earnings_date"):
        events.append({"event_type": "earnings", "event_date": fundamentals["earnings_date"],
                       "severity": "high", "source": "reported earnings calendar"})
    events.extend(fundamentals.get("company_events") or [])
    upcoming = []
    for event in events:
        sessions = _sessions_until(event.get("event_date") or event.get("date"), as_of)
        if sessions is not None:
            upcoming.append({**event, "sessions_away": sessions})
    upcoming.sort(key=lambda item: item["sessions_away"])
    if not upcoming:
        return {"level": "unknown", "coverage": "unverified", "next_event": None,
                "events": [], "entry_blocked": False}
    next_event = upcoming[0]
    critical = str(next_event.get("severity", "")).lower() in {"critical", "severe"}
    sessions = next_event["sessions_away"]
    level = "high" if critical or sessions <= 5 else "medium" if sessions <= 15 else "low"
    return {"level": level, "coverage": "verified", "next_event": next_event,
            "events": upcoming[:10], "entry_blocked": critical or sessions <= 2}


def preliminary_analysis(symbol: str, name: str, candles: list[dict],
                         nifty_candles: Optional[list[dict]] = None) -> dict:
    eligible = eligibility(candles)
    if not eligible["eligible"]:
        return {"symbol": symbol, "name": name, "eligibility": eligible, "eligible": False}
    factors = swing_engine.compute_price_factors(candles)
    relative_strength = swing_features.assess_relative_strength(candles, nifty_candles or [])
    rs_3m = relative_strength["horizons_pct_points"].get("60d")
    setup_points = 35
    trend = factors.get("trend_score", 0)
    if trend == 2:
        setup_points += 30
    elif trend == 1:
        setup_points += 15
    if 48 <= (factors.get("rsi") or 0) <= 70:
        setup_points += 15
    if (factors.get("macd_hist") or 0) > 0:
        setup_points += 10
    if (factors.get("vol_ratio") or 0) >= 1.1:
        setup_points += 10
    rs_points = relative_strength["score"]
    liquidity_points = _clamp(35 + math.log10(max(eligible["median_traded_value"], 1) / MIN_MEDIAN_TRADED_VALUE) * 35)
    preliminary = 0.55 * _clamp(setup_points) + 0.30 * rs_points + 0.15 * liquidity_points
    return {
        "symbol": symbol, "name": name, "eligible": True, "eligibility": eligible,
        "factors": factors, "relative_strength": relative_strength,
        "rs_3m_pct": round(rs_3m, 2) if rs_3m is not None else None,
        "components": {"setup": round(_clamp(setup_points), 1),
                       "relative_strength": round(rs_points, 1),
                       "liquidity": round(liquidity_points, 1)},
        "preliminary_score": round(preliminary, 2), "candles": candles,
    }


def _setup_component(setup: dict, factors: dict, relative_strength: dict,
                     volume: dict, supply: dict, contraction: dict) -> float:
    base = {"breakout": 90, "pullback": 82, "trend_continuation": 78, "none": 30}.get(setup.get("setup"), 30)
    if (factors.get("rsi") or 0) > 75:
        base -= 25
    if setup.get("setup") == "none":
        return _clamp(base)
    return _clamp(
        base * 0.45
        + relative_strength.get("score", 0) * 0.15
        + volume.get("score", 0) * 0.15
        + supply.get("score", 0) * 0.15
        + contraction.get("score", 0) * 0.10
    )


def _trend_volume_component(factors: dict, pa: dict) -> float:
    value = 50 + factors.get("trend_score", 0) * 18
    value += _clamp(((factors.get("vol_ratio") or 1) - 1) * 20, -15, 15)
    flow = ((pa.get("signals") or {}).get("obv") or {}).get("state")
    value += 8 if flow in {"confirming", "bullish_divergence"} else -10 if flow == "bearish_divergence" else 0
    return _clamp(value)


def _valuation_component(fundamentals: dict) -> float:
    pe = _number(fundamentals.get("pe_ratio"))
    earnings_yield = _number(fundamentals.get("earnings_yield"))
    if earnings_yield is not None:
        return _clamp(45 + earnings_yield * 4)
    if pe is None or pe <= 0:
        return 45.0
    return _clamp(85 - pe * 1.35, 15, 85)


def _entry_state(current: Optional[float], entry: dict) -> str:
    """Describe whether price is currently inside or near the planned zone."""
    low, high = _number(entry.get("low")), _number(entry.get("high"))
    if current is None or low is None or high is None:
        return "unknown"
    low, high = min(low, high), max(low, high)
    if low <= current <= high:
        return "in_zone"
    distance = (low - current) / current * 100 if current < low else (current - high) / high * 100
    return "near" if distance <= 3 else "far"


def classify_action(*, score: float, setup_name: str, swing: dict,
                    current: Optional[float], actionable_data: bool,
                    hard_blocks: list[str]) -> tuple[str, str]:
    """Turn reproducible setup evidence into a plain decision state.

    Historical validation is reported separately as confidence evidence.  It
    must not erase today's observable setup state; doing that made every valid
    setup look identical and produced the misleading all-WATCH dashboard.
    """
    if hard_blocks:
        return "AVOID", "A required safety check failed"
    if not actionable_data:
        return "DATA_INSUFFICIENT", "Price or financial evidence is incomplete"

    rr = _number(swing.get("risk_reward")) or 0
    state = _entry_state(current, swing.get("entry") or {})
    active_setup = setup_name not in {"", "none", None}
    supported_verdict = swing.get("verdict") in {"Buy", "Buy on Dip", "Wait"}
    if score >= 72 and active_setup and supported_verdict and rr >= 1.5 and state == "in_zone":
        return "BUY_NOW", "Strong setup is inside its entry zone with at least 1.5 reward/risk"
    if score >= 68 and active_setup and supported_verdict and rr >= 1.5 and state in {"in_zone", "near"}:
        return "WAIT_FOR_ENTRY", "Promising setup is near its planned entry zone"
    if score >= 52:
        return "WATCH", "Ranked for research, but the setup is not ready"
    return "AVOID", "Current setup quality is too weak"


def _recommendation_classification(action: str, score: float, components: dict,
                                   entry_extension: dict,
                                   actionable_data: bool) -> str:
    if not actionable_data:
        return "Data insufficient"
    if entry_extension.get("status") in {"extended", "do_not_chase"} \
            and components.get("business_quality", 0) >= 65 \
            and components.get("setup", 0) >= 70:
        return "Good Stock / Bad Entry"
    if components.get("setup", 0) >= 75 \
            and (components.get("business_quality", 0) < 45
                 or components.get("earnings_momentum", 0) < 45):
        return "Good Chart / Weak Fundamentals"
    if action == "BUY_NOW":
        return "A+" if score >= 85 else "A" if score >= 75 else "B"
    if action == "WAIT_FOR_ENTRY":
        return "Developing"
    if action == "WATCH":
        return "Developing" if components.get("setup", 0) >= 60 else "B"
    return "Avoid"


def analyze_candidate(preliminary: dict, fundamentals: dict, fund_meta: dict,
                      official_close: Optional[float] = None,
                      official_date: Optional[str] = None,
                      sector_regime_score: float = 50.0,
                      market_regime_score: float = 50.0,
                      results_within_two_sessions: bool = False) -> dict:
    candles = preliminary["candles"]
    factors = preliminary["factors"]
    quant = quant_engine.compute_all(fundamentals) if fundamentals else {}
    cfo = assess_cfo_health(fundamentals, quant)
    earnings = assess_earnings_momentum(fundamentals)
    plans = decision_engine.build_trade_plans(candles, fundamentals or None, quant or None)
    pa = price_action.analyze(candles)
    setup = decision_engine.detect_setup(
        factors, decision_engine.find_pivots(candles),
        plans.get("key_levels", {}).get("ma50"), plans.get("key_levels", {}).get("ma200"),
        plans.get("key_levels", {}).get("high_52w"), pa=(pa.get("signals") or {}),
    )
    reconciliation = price_reconciliation(
        factors.get("price"), official_close,
        candles[-1].get("date") if candles else None, official_date,
    )
    swing = plans.get("swing") or {}
    entry = swing.get("entry") or {}
    stop = swing.get("stop") or {}
    targets = swing.get("targets") or []
    supply = swing_features.assess_overhead_supply(
        candles, entry.get("high") or factors.get("price"), factors.get("atr"),
    )
    tradeability = swing_features.assess_tradeability(candles)
    move_potential = swing_features.assess_move_potential(candles, factors.get("atr"))
    volume = swing_features.assess_volume(candles)
    contraction = swing_features.assess_volatility_contraction(candles)
    relative_strength = preliminary.get("relative_strength") or \
        swing_features.assess_relative_strength(candles, [])
    setup_engines = swing_features.assess_setup_engines(
        candles, setup.get("setup"), factors, pa, relative_strength, volume,
        supply, tradeability, contraction, market_regime_score,
    )
    components = {
        "setup": setup_engines["selected"]["score"],
        "relative_strength": relative_strength["score"],
        "volume": volume["score"],
        "business_quality": cfo["score"],
        "earnings_momentum": earnings["score"],
        "overhead_supply": supply["score"],
        "tradeability": tradeability["score"],
        "move_potential": move_potential["score"],
        "sector_regime": _clamp(sector_regime_score),
        "market_regime": _clamp(market_regime_score),
    }
    score = sum(components[key] * weight for key, weight in SCORE_WEIGHTS.items())

    penalties = []
    if earnings["margin_direction"] == "severe contraction":
        score *= 0.85
        penalties.append({"factor": "severe_margin_contraction", "multiplier": 0.85})
    elif earnings["margin_direction"] == "contraction":
        score *= 0.93
        penalties.append({"factor": "margin_contraction", "multiplier": 0.93})
    if market_regime_score < 40:
        score *= 0.90
        penalties.append({"factor": "risk_off_market", "multiplier": 0.90})

    hard_blocks = list(cfo["hard_blocks"])
    if reconciliation["status"] == "conflict":
        hard_blocks.append(reconciliation["detail"])
    if results_within_two_sessions:
        hard_blocks.append("Scheduled results within two trading sessions")
    if market_regime_score <= 15:
        hard_blocks.append("Severe risk-off market regime blocks new swing longs")

    rr = swing.get("risk_reward")
    active_setup = setup.get("setup") not in {"", "none", None}
    if active_setup and rr is None:
        hard_blocks.append("No valid structural target is available")
    elif active_setup and rr < 1.5:
        hard_blocks.append(f"Structural reward/risk {rr:.2f} is below the 1.50 minimum")
    stop_risk_pct = _number(stop.get("risk_pct"))
    if stop_risk_pct is not None and stop_risk_pct > 10:
        hard_blocks.append(f"Required stop is impractical at {stop_risk_pct:.1f}%")
    if supply["severity"] == "severe":
        hard_blocks.append("Severe overhead supply leaves less than 1.25 ATR of clear air")
    if tradeability["score"] < 30 and tradeability["label"] != "Unavailable":
        hard_blocks.append("Very poor tradeability: price path is unusually erratic")

    current = factors.get("price")
    trigger = _number(entry.get("trigger_price") or entry.get("high") or entry.get("low"))
    extension_pct = max(0.0, (current / trigger - 1) * 100) if current and trigger else None
    extension_atr = ((current - trigger) / factors["atr"]
                     if current and trigger and factors.get("atr") else None)
    extension_status = (
        "unknown" if extension_atr is None else
        "healthy" if extension_atr < 1 else
        "acceptable" if extension_atr < 1.5 else
        "extended" if extension_atr < 2 else "do_not_chase"
    )
    entry_extension = {
        "distance_pct": round(extension_pct, 2) if extension_pct is not None else None,
        "distance_atr": round(extension_atr, 2) if extension_atr is not None else None,
        "status": extension_status,
    }
    if active_setup and extension_status == "do_not_chase":
        hard_blocks.append("Current price is more than 2 ATR beyond the trigger; do not chase")

    data_confidence = assess_data_confidence(
        candles, fundamentals, fund_meta, cfo, earnings, reconciliation,
    )
    event_risk = assess_event_risk(
        fundamentals, official_date or (candles[-1].get("date") if candles else datetime.now().date()),
    )
    if event_risk["entry_blocked"] and not results_within_two_sessions:
        event_name = (event_risk.get("next_event") or {}).get("event_type", "corporate event")
        hard_blocks.append(f"Entry blocked by imminent {event_name}")
    actionable_data = (
        cfo["completeness"] == "full"
        and earnings["status"] != "unavailable"
        and reconciliation["status"] == "matched"
        and data_confidence["overall"] >= 70
    )
    action, action_reason = classify_action(
        score=score, setup_name=setup.get("setup"), swing=swing,
        current=factors.get("price"), actionable_data=actionable_data,
        hard_blocks=hard_blocks,
    )
    classification = _recommendation_classification(
        action, score, components, entry_extension, actionable_data,
    )

    entry_distance = None
    if current and entry.get("low") is not None and entry.get("high") is not None:
        mid = (entry["low"] + entry["high"]) / 2
        entry_distance = (current / mid - 1) * 100 if mid else None

    positives = []
    revenue_yoy = earnings["metrics"].get("revenue_growth_yoy")
    pat_yoy = earnings["metrics"].get("pat_growth_yoy")
    if revenue_yoy is not None:
        positives.append(f"Revenue growth is {revenue_yoy:+.1f}% YoY")
    if pat_yoy is not None:
        positives.append(f"PAT growth is {pat_yoy:+.1f}% YoY")
    if supply["severity"] in {"clear", "acceptable"}:
        detail = (f"{supply['clear_air_pct']:.1f}% clear air"
                  if supply["clear_air_pct"] is not None else "no mapped resistance overhead")
        positives.append(detail)
    if tradeability["label"] in {"Very clean", "Clean"}:
        positives.append(f"{tradeability['label']} historical price path")
    concerns = list(earnings.get("cautions") or [])
    if supply["severity"] in {"severe", "crowded"}:
        concerns.append(f"{supply['severity'].capitalize()} overhead supply")
    if tradeability["label"] in {"Erratic", "Very erratic"}:
        concerns.append(f"{tradeability['label']} historical price path")
    if extension_status in {"extended", "do_not_chase"}:
        concerns.append(f"Entry is {extension_atr:.1f} ATR beyond the trigger")
    concerns.extend(hard_blocks)

    evidence = {
        "price": {"source": "Yahoo adjusted EOD + NSE bhavcopy",
                  "as_of": candles[-1].get("date"),
                  "adjustment_factor": candles[-1].get("adjustment_factor", 1.0),
                  **reconciliation},
        "fundamentals": {**fund_meta, "completeness": cfo["completeness"]},
        "model": {"version": MODEL_VERSION, "weights": SCORE_WEIGHTS,
                  "historical_comparables": 0, "expected_r_method": "unavailable_until_validated",
                  "confidence_label": "data_completeness_not_probability"},
        "ai_committee": {"status": "not_run", "authority": "downgrade_only"},
    }
    market_cap_cr = quant_engine._parse_mc_cr(fundamentals.get("market_cap"))
    return {
        "symbol": preliminary["symbol"], "company": preliminary["name"],
        "sector": fundamentals.get("sector") or "Unclassified",
        "industry": fundamentals.get("industry"), "action": action,
        "market_cap_cr": market_cap_cr,
        "market_cap_bucket": market_cap_bucket(market_cap_cr),
        "classification": classification,
        "score": round(score, 1), "expected_r": None,
        "rank_value": round(score * data_confidence["overall"] / 100, 3),
        # Compatibility field: this now means data completeness only.
        "confidence": data_confidence["overall"], "data_confidence": data_confidence,
        "setup_type": setup.get("setup"),
        "setup_label": setup.get("label"), "entry_distance_pct": round(entry_distance, 2) if entry_distance is not None else None,
        "price": current, "components": {k: round(v, 1) for k, v in components.items()},
        "cfo": cfo, "earnings_momentum": earnings,
        "overhead_supply": supply, "tradeability": tradeability,
        "move_potential": move_potential, "relative_strength": relative_strength,
        "volume": volume, "volatility_contraction": contraction,
        "setup_engines": setup_engines,
        "entry_extension": entry_extension,
        "technicals": factors, "price_action": pa, "penalties": penalties,
        "trade_plan": {"entry": entry, "stop": stop, "targets": targets,
                       "verdict": swing.get("verdict"), "entry_state": _entry_state(current, entry),
                       "risk_reward": rr, "invalidation": swing.get("invalidation"),
                       "time_stop_sessions": 40},
        "action_reason": action_reason,
        "explanation": {
            "why_it_ranks": positives[:4],
            "what_holds_it_back": concerns[:6],
            "verdict": action_reason,
            "sources": [
                {"kind": "price", "source": "Yahoo adjusted EOD + NSE bhavcopy",
                 "as_of": candles[-1].get("date") if candles else None},
                {"kind": "fundamentals", "source": fund_meta.get("origin") or "unavailable",
                 "fetched_at": fund_meta.get("fetched_at")},
            ],
        },
        "results_risk": "blocked" if results_within_two_sessions else "clear_or_unknown",
        "event_risk": event_risk,
        "hard_blocks": hard_blocks, "evidence": evidence,
        "freshness": fund_meta, "data_completeness": cfo["completeness"],
    }
