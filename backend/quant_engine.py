"""
quant_engine.py
Pure-Python quantitative scoring engine.
Includes: Piotroski F-Score, Altman Z-Score, DuPont, Beneish M-Score, Magic Formula.

Inputs:  enriched Screener data dict (from parse_screener_full in main.py).
         Expects keys: annual_pl, annual_bs, annual_cf plus the standard
         top-ratio fields (pe_ratio, roe, roce, debt_to_equity, market_cap …).

Outputs: Piotroski F-Score, Altman Z-Score, DuPont decomposition.
         All functions return dicts with 'data_quality' so the caller can
         decide how much to trust a result when annual data is partial.
"""

from __future__ import annotations
from typing import Optional
try:
    import pandas as pd
    _PANDAS_AVAILABLE = True
except ImportError:
    _PANDAS_AVAILABLE = False


# ── small helpers ─────────────────────────────────────────────────────────────

def _sf(val, default: Optional[float] = None) -> Optional[float]:
    """Safe coerce to float; strips commas and %."""
    try:
        if val in (None, "", "N/A", "-", "—"):
            return default
        return float(str(val).replace(",", "").replace("%", "").strip())
    except Exception:
        return default


def _div(a, b, default: Optional[float] = None) -> Optional[float]:
    """Safe division."""
    try:
        if b is None or b == 0:
            return default
        return a / b
    except Exception:
        return default


def _latest(lst: list) -> dict:
    return lst[-1] if lst else {}


def _prior(lst: list) -> dict:
    return lst[-2] if len(lst) >= 2 else {}


def _parse_mc_cr(mc_str) -> Optional[float]:
    """'4,73,518 Cr'  →  473518.0  (crores as float)."""
    if not mc_str:
        return None
    try:
        return float(str(mc_str).replace(",", "").replace("Cr", "").strip())
    except Exception:
        return None

def _ebit(pl: dict) -> Optional[float]:
    """
    True EBIT (Earnings Before Interest & Tax) from a Screener P&L row.
      Preferred : reported 'ebit' field (from yfinance overlay)
      Then      : PBT + Interest        (exact accounting definition)
      Fallback  : Operating Profit − Depreciation   (EBITDA − D&A)
      Last resort: Operating Profit (EBITDA)         (overstates by D&A)
    Previously the code used EBITDA directly as EBIT, inflating Altman X3.
    """
    reported = _sf(pl.get("ebit"))
    if reported is not None:
        return reported
    pbt   = _sf(pl.get("profit_before_tax"))
    intr  = _sf(pl.get("interest"))
    if pbt is not None and intr is not None:
        return pbt + intr
    ebitda = _sf(pl.get("ebitda"))
    dep    = _sf(pl.get("depreciation"))
    if ebitda is not None and dep is not None:
        return ebitda - dep
    return ebitda


def _book_equity(bs: dict) -> Optional[float]:
    """
    Book value of shareholders' equity.
      Preferred : reported 'total_equity' (from yfinance overlay)
      Fallback  : Equity Capital + Reserves (Screener)
    """
    te = _sf(bs.get("total_equity"))
    if te is not None:
        return te
    eq_c = _sf(bs.get("equity_capital"))
    res  = _sf(bs.get("reserves"))
    if eq_c is None and res is None:
        return None
    return (eq_c or 0) + (res or 0)

# ── Piotroski F-Score (0–9) ───────────────────────────────────────────────────

def compute_piotroski(data: dict) -> dict:
    """
    Nine binary signals grouped into:
      Profitability (F1–F4), Leverage/Liquidity (F5–F7), Efficiency (F8–F9).

    Returns:
      score          int 0-9 (or None if data insufficient)
      max_score      9
      signals        dict of each signal → {score, value, unit, description}
      interpretation str
      data_quality   "high" | "partial" | "low"
    """
    annual_pl = data.get("annual_pl", [])
    annual_bs = data.get("annual_bs", [])
    annual_cf = data.get("annual_cf", [])

    if not annual_pl or not annual_bs:
        return {
            "score": None, "max_score": 9, "signals": {},
            "interpretation": "Insufficient annual data for Piotroski calculation.",
            "data_quality": "low",
        }

    pl_l, pl_p = _latest(annual_pl), _prior(annual_pl)
    bs_l, bs_p = _latest(annual_bs), _prior(annual_bs)
    cf_l       = _latest(annual_cf)

    ta_l  = _sf(bs_l.get("total_assets"))
    ta_p  = _sf(bs_p.get("total_assets"))
    ni_l  = _sf(pl_l.get("net_profit"))
    ni_p  = _sf(pl_p.get("net_profit"))
    rev_l = _sf(pl_l.get("revenue"))
    rev_p = _sf(pl_p.get("revenue"))
    eb_l  = _sf(pl_l.get("ebitda"))
    eb_p  = _sf(pl_p.get("ebitda"))
    cfo_l = _sf(cf_l.get("cfo"))
    br_l  = _sf(bs_l.get("borrowings"))
    br_p  = _sf(bs_p.get("borrowings"))
    ca_l  = _sf(bs_l.get("current_assets"))
    ca_p  = _sf(bs_p.get("current_assets"))
    cl_l  = _sf(bs_l.get("current_liabilities"))
    cl_p  = _sf(bs_p.get("current_liabilities"))
    eq_l  = _sf(bs_l.get("equity_capital"))
    eq_p  = _sf(bs_p.get("equity_capital"))

    sigs = {}

    # ── PROFITABILITY ─────────────────────────────────────────────────────────
    # F1 : ROA > 0
    roa_l = _div(ni_l, ta_l)
    f1 = 1 if (roa_l is not None and roa_l > 0) else 0
    sigs["F1_positive_roa"] = {
        "score": f1,
        "value": round(roa_l * 100, 2) if roa_l is not None else None,
        "unit": "%",
        "description": "Net Income / Total Assets > 0 — company is asset-profitable",
    }

    # F2 : CFO > 0
    f2 = 1 if (cfo_l is not None and cfo_l > 0) else 0
    sigs["F2_positive_cfo"] = {
        "score": f2,
        "value": cfo_l,
        "unit": "Cr",
        "description": "Operating cash flow is positive — real cash being generated",
    }

    # F3 : ΔROA > 0
    roa_p = _div(ni_p, ta_p)
    if roa_l is not None and roa_p is not None:
        f3 = 1 if roa_l > roa_p else 0
        delta_roa = round((roa_l - roa_p) * 100, 2)
    else:
        f3, delta_roa = 0, None
    sigs["F3_increasing_roa"] = {
        "score": f3,
        "value": delta_roa,
        "unit": "% pts YoY",
        "description": "ROA improved year-over-year",
    }

    # F4 : Quality of earnings — CFO/Assets > ROA (cash > accrual income)
    cfo_ratio = _div(cfo_l, ta_l)
    if cfo_ratio is not None and roa_l is not None:
        f4 = 1 if cfo_ratio > roa_l else 0
    else:
        f4 = 0
    sigs["F4_quality_earnings"] = {
        "score": f4,
        "value": round(cfo_ratio * 100, 2) if cfo_ratio is not None else None,
        "unit": "% (CFO/Assets vs ROA)",
        "description": "CFO/Assets > ROA — earnings are cash-backed, not accounting inflated",
    }

    # ── LEVERAGE / LIQUIDITY ──────────────────────────────────────────────────
    # F5 : Δ long-term debt ratio < 0
    dr_l = _div(br_l, ta_l)
    dr_p = _div(br_p, ta_p)
    if dr_l is not None and dr_p is not None:
        f5 = 1 if dr_l < dr_p else 0
        lev_val = round(dr_l * 100, 2)
    else:
        # Fall back to scraped D/E ratio
        de = _sf(data.get("debt_to_equity"))
        f5 = 1 if (de is not None and de < 0.5) else 0
        lev_val = de
    sigs["F5_decreasing_leverage"] = {
        "score": f5,
        "value": lev_val,
        "unit": "Debt/Assets %" if dr_l is not None else "D/E ratio",
        "description": "Long-term debt burden has not increased YoY",
    }

    # F6 : Δ current ratio > 0 (improving liquidity)
    cr_l = _div(ca_l, cl_l)
    cr_p = _div(ca_p, cl_p)
    if cr_l is not None and cr_p is not None:
        f6 = 1 if cr_l > cr_p else 0
    else:
        f6 = 0
    sigs["F6_improving_liquidity"] = {
        "score": f6,
        "value": round(cr_l, 2) if cr_l is not None else None,
        "unit": "Current ratio",
        "description": "Current ratio improved — better short-term liquidity cover",
    }

    # F7 : No share dilution (equity capital not grown meaningfully)
    if eq_l is not None and eq_p is not None and eq_p > 0:
        f7 = 1 if eq_l <= eq_p * 1.02 else 0   # 2 % tolerance
    else:
        f7 = 0
    sigs["F7_no_dilution"] = {
        "score": f7,
        "value": eq_l,
        "unit": "Equity capital Cr",
        "description": "No significant new share issuance detected",
    }

    # ── OPERATING EFFICIENCY ──────────────────────────────────────────────────
    # F8 : Δ EBITDA margin > 0  (gross margin proxy)
    gm_l = _div(eb_l, rev_l)
    gm_p = _div(eb_p, rev_p)
    if gm_l is not None and gm_p is not None:
        f8 = 1 if gm_l > gm_p else 0
    else:
        f8 = 0
    sigs["F8_improving_margin"] = {
        "score": f8,
        "value": round(gm_l * 100, 2) if gm_l is not None else None,
        "unit": "% EBITDA margin",
        "description": "EBITDA margin expanded YoY — pricing power or cost efficiency",
    }

    # F9 : Δ asset turnover > 0
    at_l = _div(rev_l, ta_l)
    at_p = _div(rev_p, ta_p)
    if at_l is not None and at_p is not None:
        f9 = 1 if at_l > at_p else 0
    else:
        f9 = 0
    sigs["F9_asset_turnover"] = {
        "score": f9,
        "value": round(at_l, 3) if at_l is not None else None,
        "unit": "x (Revenue / Assets)",
        "description": "Asset utilization improved — more revenue squeezed per rupee of assets",
    }

    total = f1 + f2 + f3 + f4 + f5 + f6 + f7 + f8 + f9

    if   total >= 8: interp = "Strong — high-quality business with improving fundamentals"
    elif total >= 6: interp = "Good — fundamentally sound with minor concerns"
    elif total >= 4: interp = "Average — mixed signals; monitor carefully"
    elif total >= 2: interp = "Weak — multiple red flags in fundamentals"
    else:            interp = "Distressed — severely deteriorating fundamentals"

    dq = "high" if (ta_l and ni_l and cfo_l and br_l) else \
         "partial" if (ta_l and ni_l) else "low"

    return {
        "score": total,
        "max_score": 9,
        "signals": sigs,
        "interpretation": interp,
        "data_quality": dq,
    }


# ── Altman Z-Score ────────────────────────────────────────────────────────────

def compute_altman_z(data: dict) -> dict:
    """
    Altman Z''-Score — the emerging-market / non-manufacturing model (Altman 1995,
    2005), the correct variant for Indian equities across sectors.

        Z'' = 3.25 + 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4

        X1 = Working Capital / Total Assets
        X2 = Retained Earnings / Total Assets
        X3 = EBIT / Total Assets                 (true EBIT, not EBITDA)
        X4 = Book Value of Equity / Total Liabilities

    It drops X5 (Sales/Assets), which was calibrated only on US manufacturers,
    so it is industry-neutral.

        Safe zone : Z'' > 2.6
        Grey zone : 1.1 < Z'' ≤ 2.6
        Distress  : Z'' ≤ 1.1

    The classic 1968 Z (market-value X4 + X5) is still returned as `z_classic`
    for reference. Both are unreliable for banks/NBFCs (no working-capital cycle).
    """
    annual_pl = data.get("annual_pl", [])
    annual_bs = data.get("annual_bs", [])

    pl = _latest(annual_pl)
    bs = _latest(annual_bs)

    ta    = _sf(bs.get("total_assets"))
    ca    = _sf(bs.get("current_assets"))
    cl    = _sf(bs.get("current_liabilities"))
    borr  = _sf(bs.get("borrowings"))
    res   = _sf(bs.get("reserves"))
    eq_c  = _sf(bs.get("equity_capital"))
    rev   = _sf(pl.get("revenue"))
    ebit  = _ebit(pl)                 # true EBIT (PBT+Interest, or EBITDA−Dep)
    mc_cr = _parse_mc_cr(data.get("market_cap"))

    if not ta or ta == 0:
        return {
            "z_score": None, "z_prime": None, "z_classic": None,
            "zone": "Unknown", "zone_color": "grey",
            "interpretation": "Insufficient balance sheet data — cannot compute Z-Score.",
            "components": {}, "data_quality": "low",
        }

    equity_book = _book_equity(bs) or 0
    wc          = (ca or 0) - (cl or 0)
    re_earnings = res or 0                                    # retained earnings ≈ reserves
    total_liab  = ta - equity_book if equity_book else ta     # book liabilities

    # X4 uses BOOK equity / book liabilities. Guard a degenerate denominator
    # (no/negative liabilities → very safe) by capping instead of exploding.
    if total_liab <= 0:
        X4 = 8.0
    else:
        X4 = min(_div(equity_book, total_liab, 0), 8.0)

    X1 = _div(wc, ta, 0)                     # Working capital / Assets
    X2 = _div(re_earnings, ta, 0)            # Retained earnings / Assets
    X3 = _div(ebit or 0, ta, 0)              # EBIT / Assets
    X5 = _div(rev or 0, ta, 0)               # Revenue / Assets (classic model only)

    # Primary model: Z'' emerging-market / non-manufacturing
    z = 3.25 + 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4

    # Reference: classic 1968 Z with market-value X4 (falls back to book equity)
    mve      = mc_cr if mc_cr else equity_book
    X4_mkt   = min(_div(mve, total_liab, 0) if total_liab > 0 else 8.0, 12.0)
    z_classic = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4_mkt + 1.0*X5

    if   z > 2.6: zone, color = "Safe",      "green"
    elif z > 1.1: zone, color = "Grey Zone", "yellow"
    else:         zone, color = "Distress",  "red"

    interp_map = {
        "Safe":      "Low probability of financial distress in the next 2 years.",
        "Grey Zone": "Moderate financial stress — monitor debt levels and cash flow closely.",
        "Distress":  "High probability of financial distress — deep due diligence required.",
    }

    dq = "high" if (ta and ca and cl and ebit is not None and equity_book) else \
         "partial" if ta else "low"

    return {
        "z_score": round(z, 2),
        "z_prime": round(z, 2),          # back-compat alias (primary model)
        "z_classic": round(z_classic, 2),
        "zone": zone,
        "zone_color": color,
        "model": "Z''-score (emerging markets)",
        "interpretation": interp_map[zone],
        "components": {
            "X1_working_capital_ratio": round(X1, 4),
            "X2_retained_earnings_ratio": round(X2, 4),
            "X3_ebit_to_assets": round(X3, 4),
            "X4_equity_vs_liabilities": round(X4, 4),
            "X5_asset_turnover": round(X5, 4),
        },
        "thresholds": {"safe_above": 2.6, "grey_above": 1.1},
        "data_quality": dq,
    }


# ── DuPont Analysis ───────────────────────────────────────────────────────────

def compute_dupont(data: dict) -> dict:
    """
    3-factor DuPont decomposition:
        ROE = Net Profit Margin  ×  Asset Turnover  ×  Equity Multiplier

    Also returns a 5-year trend table and identifies the primary ROE driver.
    """
    annual_pl = data.get("annual_pl", [])
    annual_bs = data.get("annual_bs", [])

    pl = _latest(annual_pl)
    bs = _latest(annual_bs)

    rev  = _sf(pl.get("revenue"))
    ni   = _sf(pl.get("net_profit"))
    ta   = _sf(bs.get("total_assets"))

    equity = _book_equity(bs)
    if equity is not None and equity <= 0:
        equity = None

    npm = _div(ni, rev)       # Net Profit Margin
    at  = _div(rev, ta)       # Asset Turnover
    em  = _div(ta, equity)    # Equity Multiplier (financial leverage)

    roe_dupont = (npm * at * em) if (npm and at and em) else None

    # 5-year trend
    trend = []
    for p, b in zip(annual_pl, annual_bs):
        r = _sf(p.get("revenue"));  n  = _sf(p.get("net_profit"))
        t = _sf(b.get("total_assets"))
        eq = _book_equity(b) or None
        _npm = _div(n, r, 0);  _at = _div(r, t, 0);  _em = _div(t, eq, 0)
        trend.append({
            "year":             p.get("year") or b.get("year", ""),
            "npm_pct":          round(_npm * 100, 2) if _npm else None,
            "asset_turnover":   round(_at, 3)        if _at  else None,
            "equity_multiplier":round(_em, 2)        if _em  else None,
            "roe_computed_pct": round(_npm * _at * _em * 100, 2)
                                if (_npm and _at and _em) else None,
        })

    # Primary driver diagnosis
    driver = "N/A"
    if npm is not None and at is not None and em is not None:
        npm_norm = abs(npm)              # already a ratio ~0–0.3
        at_norm  = abs(at) * 0.25       # turnover ~0.5–3x scaled to comparable range
        lev_norm = max((em or 1) - 1, 0) * 0.3
        mx = max(npm_norm, at_norm, lev_norm)
        if   mx == npm_norm: driver = "Margin-driven (strong pricing power / cost control)"
        elif mx == at_norm:  driver = "Efficiency-driven (high asset utilisation)"
        else:                driver = "Leverage-driven (financial engineering — watch debt levels)"

    dq = "high" if (npm and at and em) else "partial" if (npm or at) else "low"

    return {
        "net_profit_margin_pct": round(npm * 100, 2) if npm is not None else None,
        "asset_turnover":        round(at, 3)        if at  is not None else None,
        "equity_multiplier":     round(em, 2)        if em  is not None else None,
        "roe_dupont_pct":        round(roe_dupont * 100, 2) if roe_dupont else None,
        "roe_reported_pct":      _sf(data.get("roe")),
        "primary_roe_driver":    driver,
        "trend":                 trend,
        "data_quality":          dq,
    }


# ── Beneish M-Score ───────────────────────────────────────────────────────────

def compute_beneish_m(data: dict) -> dict:
    """
    Beneish (1999) 8-variable earnings manipulation detection model.

    M > -1.78  →  probable manipulator  (screen OUT)
    M > -2.22  →  grey zone
    M ≤ -2.22  →  likely non-manipulator

    Variables are approximated from Screener.in balance-sheet / P&L data
    because receivables and SG&A are not broken out separately.
    DEPI and SGAI default to 1.0 (neutral) when data is unavailable.
    """
    annual_pl = data.get("annual_pl", [])
    annual_bs = data.get("annual_bs", [])
    annual_cf = data.get("annual_cf", [])

    if len(annual_pl) < 2 or len(annual_bs) < 2:
        return {
            "m_score": None, "is_manipulator": None,
            "interpretation": "Insufficient annual data for Beneish M-Score.",
            "components": {}, "threshold": -1.78, "data_quality": "low",
        }

    pl_t, pl_p = _latest(annual_pl), _prior(annual_pl)
    bs_t, bs_p = _latest(annual_bs), _prior(annual_bs)
    cf_t       = _latest(annual_cf)

    rev_t  = _sf(pl_t.get("revenue"))
    rev_p  = _sf(pl_p.get("revenue"))
    op_t   = _sf(pl_t.get("ebitda"))
    op_p   = _sf(pl_p.get("ebitda"))
    ni_t   = _sf(pl_t.get("net_profit"))
    ta_t   = _sf(bs_t.get("total_assets"))
    ta_p   = _sf(bs_p.get("total_assets"))
    ca_t   = _sf(bs_t.get("current_assets"))
    ca_p   = _sf(bs_p.get("current_assets"))
    fa_t   = _sf(bs_t.get("fixed_assets"))
    fa_p   = _sf(bs_p.get("fixed_assets"))
    br_t   = _sf(bs_t.get("borrowings"))
    br_p   = _sf(bs_p.get("borrowings"))
    cl_t   = _sf(bs_t.get("current_liabilities"))
    cl_p   = _sf(bs_p.get("current_liabilities"))
    dep_t  = _sf(pl_t.get("depreciation"))
    dep_p  = _sf(pl_p.get("depreciation"))
    cfo_t  = _sf(cf_t.get("cfo")) if cf_t else None

    # DSRI — Days Sales Receivables Index (current assets / rev as proxy)
    dsri_t = _div(ca_t, rev_t, None)
    dsri_p = _div(ca_p, rev_p, None)
    DSRI   = _div(dsri_t, dsri_p, 1.0) or 1.0

    # GMI — Gross Margin Index (prior / current; >1 = deteriorating)
    gm_t = _div(op_t, rev_t, None)
    gm_p = _div(op_p, rev_p, None)
    GMI  = _div(gm_p, gm_t, 1.0) or 1.0

    # AQI — Asset Quality Index
    aq_t = 1 - (_div((ca_t or 0) + (fa_t or 0), ta_t, 0) or 0)
    aq_p = 1 - (_div((ca_p or 0) + (fa_p or 0), ta_p, 0) or 0)
    AQI  = _div(aq_t, aq_p, 1.0) or 1.0

    # SGI — Sales Growth Index
    SGI  = _div(rev_t, rev_p, 1.0) or 1.0

    # DEPI — Depreciation Index. Real value when depreciation + net PPE exist:
    #   rate = Dep / (Dep + Net Fixed Assets);  DEPI = rate_prior / rate_current.
    #   >1 → depreciation rate slowed (possible capitalising/earnings inflation).
    depi_ok = None not in (dep_t, dep_p, fa_t, fa_p)
    if depi_ok:
        rate_t = _div(dep_t, (dep_t or 0) + (fa_t or 0), None)
        rate_p = _div(dep_p, (dep_p or 0) + (fa_p or 0), None)
        DEPI   = _div(rate_p, rate_t, 1.0) or 1.0
    else:
        DEPI = 1.0

    # SGAI — SG&A not broken out by Screener; use neutral
    SGAI = 1.0

    # TATA — Total Accruals to Total Assets
    if ni_t is not None and cfo_t is not None and ta_t:
        TATA = (ni_t - cfo_t) / ta_t
    else:
        TATA = 0.0

    # LVGI — Leverage Growth Index
    lev_t = _div((br_t or 0) + (cl_t or 0), ta_t, None)
    lev_p = _div((br_p or 0) + (cl_p or 0), ta_p, None)
    LVGI  = _div(lev_t, lev_p, 1.0) or 1.0

    m = (-4.840
         + 0.920 * DSRI
         + 0.528 * GMI
         + 0.404 * AQI
         + 0.892 * SGI
         + 0.115 * DEPI
         - 0.172 * SGAI
         + 4.679 * TATA
         - 0.327 * LVGI)

    if   m > -1.78: interp = "Probable earnings manipulator — exercise caution"
    elif m > -2.22: interp = "Grey zone — inconclusive, scrutinise closely"
    else:           interp = "Non-manipulator — no strong manipulation signals"

    # DSRI/AQI are balance-sheet proxies and SGAI is neutralised (no SG&A line).
    dq = "partial" if depi_ok else "low"

    return {
        "m_score":      round(m, 3),
        "is_manipulator": m > -1.78,
        "interpretation": interp,
        "components": {
            "DSRI": round(DSRI, 4), "GMI":  round(GMI, 4),
            "AQI":  round(AQI, 4),  "SGI":  round(SGI, 4),
            "DEPI": round(DEPI, 4), "SGAI": round(SGAI, 4),
            "TATA": round(TATA, 4), "LVGI": round(LVGI, 4),
        },
        "threshold": -1.78,
        "data_quality": dq,
    }


# ── Magic Formula (Greenblatt) ────────────────────────────────────────────────

def compute_magic_formula(df: "pd.DataFrame") -> "pd.DataFrame":
    """
    Joel Greenblatt's Magic Formula screener (Little Book That Beats the Market).

    Required DataFrame columns:
        ebit   — Earnings Before Interest & Tax (Cr)
        ev     — Enterprise Value = Market Cap + Debt − Cash (Cr)
        nwc    — Net Working Capital = Current Assets − Current Liabilities (Cr)
        nfa    — Net Fixed Assets (Cr)

    Returns df sorted by combined rank (mf_rank=1 is the best pick).
    """
    if not _PANDAS_AVAILABLE:
        raise ImportError("pandas is required for compute_magic_formula")

    df = df.copy()

    # Earnings Yield = EBIT / EV  (higher = cheaper)
    df["earnings_yield"] = df.apply(
        lambda r: r["ebit"] / r["ev"]
        if (pd.notna(r.get("ebit")) and pd.notna(r.get("ev")) and r.get("ev", 0) > 0)
        else None,
        axis=1,
    )

    # Return on Capital = EBIT / (NWC + NFA)  (higher = more efficient)
    df["roc"] = df.apply(
        lambda r: r["ebit"] / (r["nwc"] + r["nfa"])
        if (pd.notna(r.get("ebit")) and pd.notna(r.get("nwc"))
            and pd.notna(r.get("nfa")) and (r.get("nwc", 0) + r.get("nfa", 0)) > 0)
        else None,
        axis=1,
    )

    # Rank: lower number = better rank
    df["ey_rank"]  = df["earnings_yield"].rank(ascending=False, na_option="bottom").astype(int)
    df["roc_rank"] = df["roc"].rank(ascending=False, na_option="bottom").astype(int)
    df["mf_rank"]  = df["ey_rank"] + df["roc_rank"]

    return df.sort_values("mf_rank").reset_index(drop=True)


# ── Master entry point ────────────────────────────────────────────────────────

def compute_all(data: dict) -> dict:
    """Run all quant models and attach a simple composite quality score."""
    piotroski = compute_piotroski(data)
    altman    = compute_altman_z(data)
    dupont    = compute_dupont(data)
    beneish   = compute_beneish_m(data)

    # Composite 0-100 quality score (rough heuristic)
    pts = 0
    if piotroski["score"] is not None:
        pts += int(piotroski["score"] / 9 * 40)   # 40 pts
    if altman["z_score"] is not None:
        # Z''-score scale: distress ≤1.1, safe >2.6, healthy ~6+.
        z_norm = min(max((altman["z_score"] - 1.1) / (6.0 - 1.1), 0.0), 1.0)
        pts += int(z_norm * 30)                    # 30 pts
    roe = _sf(data.get("roe"))
    if roe:
        pts += int(min(roe / 30.0, 1.0) * 30)     # 30 pts

    return {
        "piotroski":               piotroski,
        "altman":                  altman,
        "dupont":                  dupont,
        "beneish":                 beneish,
        "composite_quality_score": min(pts, 100),
    }
