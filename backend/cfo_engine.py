"""Deterministic CFO-quality + swing-ranking model for the daily workspace.

This module is intentionally pure: no network, database, or AI calls.  Every
recommendation can therefore be reproduced, unit tested, and audited from the
snapshot evidence saved beside it.  AI is allowed to explain or downgrade the
result later; it never edits these calculations or bypasses a gate.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Any, Optional

import decision_engine
import price_action
import quant_engine
import swing_engine

MODEL_VERSION = "cfo-v1.0.0"
MIN_SESSIONS = 252
MIN_PRICE = 20.0
MIN_MEDIAN_TRADED_VALUE = 5_00_00_000.0  # ₹5 crore

FINANCIAL_SECTOR_TERMS = (
    "bank", "banking", "financial services", "finance", "nbfc",
    "insurance", "life insurance", "general insurance",
)

SCORE_WEIGHTS = {
    "setup": 0.25,
    "relative_strength": 0.20,
    "trend_volume": 0.15,
    "cfo_health": 0.15,
    "sector_regime": 0.10,
    "liquidity": 0.10,
    "valuation": 0.05,
}

ACTIONS = {"BUY_NOW", "WAIT_FOR_ENTRY", "WATCH", "AVOID", "DATA_INSUFFICIENT"}


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


def preliminary_analysis(symbol: str, name: str, candles: list[dict],
                         nifty_candles: Optional[list[dict]] = None) -> dict:
    eligible = eligibility(candles)
    if not eligible["eligible"]:
        return {"symbol": symbol, "name": name, "eligibility": eligible, "eligible": False}
    factors = swing_engine.compute_price_factors(candles)
    nifty_factors = swing_engine.compute_price_factors(nifty_candles or [])
    rs_3m = None
    if factors.get("ret_3m") is not None and nifty_factors.get("ret_3m") is not None:
        rs_3m = (factors["ret_3m"] - nifty_factors["ret_3m"]) * 100
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
    rs_points = _clamp(50 + (rs_3m or 0) * 2)
    liquidity_points = _clamp(35 + math.log10(max(eligible["median_traded_value"], 1) / MIN_MEDIAN_TRADED_VALUE) * 35)
    preliminary = 0.55 * _clamp(setup_points) + 0.30 * rs_points + 0.15 * liquidity_points
    return {
        "symbol": symbol, "name": name, "eligible": True, "eligibility": eligible,
        "factors": factors, "rs_3m_pct": round(rs_3m, 2) if rs_3m is not None else None,
        "components": {"setup": round(_clamp(setup_points), 1),
                       "relative_strength": round(rs_points, 1),
                       "liquidity": round(liquidity_points, 1)},
        "preliminary_score": round(preliminary, 2), "candles": candles,
    }


def _setup_component(setup: dict, factors: dict) -> float:
    base = {"breakout": 90, "pullback": 82, "trend_continuation": 78, "none": 30}.get(setup.get("setup"), 30)
    if (factors.get("rsi") or 0) > 75:
        base -= 25
    return _clamp(base)


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


def analyze_candidate(preliminary: dict, fundamentals: dict, fund_meta: dict,
                      official_close: Optional[float] = None,
                      official_date: Optional[str] = None,
                      sector_regime_score: float = 50.0,
                      results_within_two_sessions: bool = False) -> dict:
    candles = preliminary["candles"]
    factors = preliminary["factors"]
    quant = quant_engine.compute_all(fundamentals) if fundamentals else {}
    cfo = assess_cfo_health(fundamentals, quant)
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
    components = {
        "setup": _setup_component(setup, factors),
        "relative_strength": preliminary["components"]["relative_strength"],
        "trend_volume": _trend_volume_component(factors, pa),
        "cfo_health": cfo["score"],
        "sector_regime": _clamp(sector_regime_score),
        "liquidity": preliminary["components"]["liquidity"],
        "valuation": _valuation_component(fundamentals),
    }
    score = sum(components[key] * weight for key, weight in SCORE_WEIGHTS.items())

    hard_blocks = list(cfo["hard_blocks"])
    if reconciliation["status"] == "conflict":
        hard_blocks.append(reconciliation["detail"])
    if results_within_two_sessions:
        hard_blocks.append("Scheduled results within two trading sessions")

    swing = plans.get("swing") or {}
    entry, stop, targets = swing.get("entry") or {}, swing.get("stop") or {}, swing.get("targets") or []
    rr = swing.get("risk_reward")
    actionable_data = cfo["completeness"] == "full" and reconciliation["status"] == "matched"
    if hard_blocks:
        action = "AVOID"
    elif not actionable_data:
        action = "DATA_INSUFFICIENT"
    elif score >= 76 and swing.get("verdict") == "Buy" and (rr or 0) >= 1.5:
        action = "BUY_NOW"
    elif score >= 68 and swing.get("verdict") in {"Buy", "Buy on Dip", "Wait"}:
        action = "WAIT_FOR_ENTRY"
    elif score >= 52:
        action = "WATCH"
    else:
        action = "AVOID"

    coverage = sum(v is not None for v in cfo["metrics"].values()) / max(1, len(cfo["metrics"]))
    confidence = _clamp(38 + coverage * 35 + min(len(candles), 500) / 500 * 17)
    if fund_meta.get("stale"):
        confidence -= 12
    if reconciliation["status"] != "matched":
        confidence = min(confidence, 49)

    expected_r = round((score - 50) / 25, 2)
    expected_r = max(-0.5, min(1.75, expected_r))
    current = factors.get("price")
    entry_distance = None
    if current and entry.get("low") is not None and entry.get("high") is not None:
        mid = (entry["low"] + entry["high"]) / 2
        entry_distance = (current / mid - 1) * 100 if mid else None

    evidence = {
        "price": {"source": "Yahoo adjusted EOD + NSE bhavcopy",
                  "as_of": candles[-1].get("date"), **reconciliation},
        "fundamentals": {**fund_meta, "completeness": cfo["completeness"]},
        "model": {"version": MODEL_VERSION, "weights": SCORE_WEIGHTS,
                  "historical_comparables": 0, "expected_r_method": "deterministic_fallback",
                  "confidence_label": "early"},
        "ai_committee": {"status": "not_run", "authority": "downgrade_only"},
    }
    return {
        "symbol": preliminary["symbol"], "company": preliminary["name"],
        "sector": fundamentals.get("sector") or "Unclassified",
        "industry": fundamentals.get("industry"), "action": action,
        "score": round(score, 1), "expected_r": expected_r,
        "rank_value": round(expected_r * confidence / 100, 3),
        "confidence": round(_clamp(confidence), 1), "setup_type": setup.get("setup"),
        "setup_label": setup.get("label"), "entry_distance_pct": round(entry_distance, 2) if entry_distance is not None else None,
        "price": current, "components": {k: round(v, 1) for k, v in components.items()},
        "cfo": cfo, "technicals": factors, "price_action": pa,
        "trade_plan": {"entry": entry, "stop": stop, "targets": targets,
                       "risk_reward": rr, "invalidation": swing.get("invalidation"),
                       "time_stop_sessions": 40},
        "results_risk": "blocked" if results_within_two_sessions else "clear_or_unknown",
        "hard_blocks": hard_blocks, "evidence": evidence,
        "freshness": fund_meta, "data_completeness": cfo["completeness"],
    }
