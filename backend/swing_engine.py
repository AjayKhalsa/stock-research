"""
swing_engine.py
Advanced quantitative ranking engine for swing trading.

Per-stock price factors (from daily candles):
    - Multi-horizon momentum: 1M / 3M / 6M returns, 12-1 momentum
    - 52-week-high proximity (George & Hwang momentum anchor)
    - RSI(14), MACD(12,26,9), moving-average trend alignment
    - ATR(14) volatility, annualized daily volatility
    - Risk-adjusted momentum (6M return / annualized vol)
    - Volume surge ratio (20d avg vs 60d avg)
    - ATR-based entry / stop / target levels

Cross-sectional ranking (across the uploaded list):
    - Winsorize each factor at the 5th/95th percentile
    - Z-score normalization per factor
    - Composite group scores: Momentum, Quality, Value, Low-Risk
    - Swing-trading weighted composite -> percentile score 0-100
    - Hard-flag detection and verdict assignment
"""

from __future__ import annotations

import math
from typing import Optional

# Trading-day horizon constants
D_1M, D_3M, D_6M, D_12M = 21, 63, 126, 252


# ── low-level indicator math ──────────────────────────────────────────────────

def _ema(values: list, period: int) -> Optional[list]:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _rsi(closes: list, period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    # Wilder smoothing
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 2)


def _atr(highs: list, lows: list, closes: list, period: int = 14) -> Optional[float]:
    n = len(closes)
    if n < period + 1:
        return None
    trs = []
    for i in range(1, n):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _macd_hist(closes: list) -> Optional[float]:
    """Latest MACD histogram value (MACD line - signal line)."""
    if len(closes) < 26 + 9:
        return None
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    # Align: ema26 starts 14 elements later than ema12
    macd_line = [a - b for a, b in zip(ema12[14:], ema26)]
    signal = _ema(macd_line, 9)
    if not signal:
        return None
    return macd_line[-1] - signal[-1]


def _ret(closes: list, lookback: int) -> Optional[float]:
    if len(closes) <= lookback or closes[-1 - lookback] == 0:
        return None
    return closes[-1] / closes[-1 - lookback] - 1.0


def _ann_vol(closes: list, window: int = D_6M) -> Optional[float]:
    """Annualized std-dev of daily log returns over the trailing window."""
    seg = closes[-(window + 1):]
    if len(seg) < 30:
        return None
    rets = [math.log(seg[i] / seg[i - 1]) for i in range(1, len(seg)) if seg[i - 1] > 0]
    if len(rets) < 20:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


# ── per-stock price factors ───────────────────────────────────────────────────

def compute_price_factors(candles: list) -> dict:
    """
    candles: [{date, open, high, low, close, volume}, ...] oldest first.
    Returns {} when there isn't enough history (~30 candles minimum).
    """
    if not candles or len(candles) < 30:
        return {}

    closes = [c["close"] for c in candles if c.get("close")]
    highs  = [c.get("high", c["close"]) for c in candles if c.get("close")]
    lows   = [c.get("low",  c["close"]) for c in candles if c.get("close")]
    vols   = [c.get("volume", 0) for c in candles if c.get("close")]
    if len(closes) < 30:
        return {}

    price = closes[-1]

    # Momentum horizons
    ret_1m = _ret(closes, D_1M)
    ret_3m = _ret(closes, D_3M)
    ret_6m = _ret(closes, D_6M)
    # Classic 12-1 momentum: 12-month return excluding the most recent month
    mom_12_1 = None
    if len(closes) > D_12M and closes[-1 - D_12M] > 0:
        mom_12_1 = closes[-1 - D_1M] / closes[-1 - D_12M] - 1.0

    # 52-week-high proximity (1.0 = at the high)
    hi_window = highs[-D_12M:] if len(highs) >= D_12M else highs
    high_52w  = max(hi_window)
    prox_52w  = price / high_52w if high_52w > 0 else None

    # Indicators
    rsi     = _rsi(closes)
    macd_h  = _macd_hist(closes)
    atr     = _atr(highs, lows, closes)
    atr_pct = (atr / price * 100) if (atr and price > 0) else None
    vol_ann = _ann_vol(closes)

    # Risk-adjusted momentum (Sharpe-flavoured)
    risk_adj_mom = None
    if ret_6m is not None and vol_ann and vol_ann > 0:
        risk_adj_mom = ret_6m / vol_ann

    # Moving-average trend alignment: +2 strong up ... -2 strong down
    ma50  = sum(closes[-50:])  / 50  if len(closes) >= 50  else None
    ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
    trend_score = 0
    if ma50 and ma200:
        if price > ma50 > ma200:   trend_score = 2
        elif price > ma200:        trend_score = 1
        elif price < ma50 < ma200: trend_score = -2
        elif price < ma200:        trend_score = -1
    elif ma50:
        trend_score = 1 if price > ma50 else -1

    # Volume surge: recent 20d avg vs 60d avg
    vol_ratio = None
    if len(vols) >= 60:
        v20 = sum(vols[-20:]) / 20
        v60 = sum(vols[-60:]) / 60
        if v60 > 0:
            vol_ratio = v20 / v60

    # ATR-based swing levels (2R stop, 3R target)
    stop   = round(price - 2 * atr, 2) if atr else None
    target = round(price + 3 * atr, 2) if atr else None

    return {
        "price":        round(price, 2),
        "ret_1m":       ret_1m,
        "ret_3m":       ret_3m,
        "ret_6m":       ret_6m,
        "mom_12_1":     mom_12_1,
        "prox_52w":     prox_52w,
        "rsi":          rsi,
        "macd_hist":    macd_h,
        "atr":          round(atr, 2) if atr else None,
        "atr_pct":      round(atr_pct, 2) if atr_pct else None,
        "vol_ann":      vol_ann,
        "risk_adj_mom": risk_adj_mom,
        "trend_score":  trend_score,
        "vol_ratio":    round(vol_ratio, 2) if vol_ratio else None,
        "stop":         stop,
        "target":       target,
    }


# ── cross-sectional statistics ────────────────────────────────────────────────

def _winsorize(vals: list) -> list:
    """Clip at 5th/95th percentile; None entries pass through unchanged."""
    clean = sorted(v for v in vals if v is not None)
    if len(clean) < 4:
        return vals
    lo = clean[max(0, int(0.05 * len(clean)))]
    hi = clean[min(len(clean) - 1, int(0.95 * len(clean)))]
    return [None if v is None else max(lo, min(hi, v)) for v in vals]


def _zscores(vals: list) -> list:
    clean = [v for v in vals if v is not None]
    if len(clean) < 2:
        return [None] * len(vals)
    mean = sum(clean) / len(clean)
    var  = sum((v - mean) ** 2 for v in clean) / (len(clean) - 1)
    sd   = math.sqrt(var)
    if sd == 0:
        return [0.0 if v is not None else None for v in vals]
    return [None if v is None else (v - mean) / sd for v in vals]


def _norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _group_z(z_lists: list, idx: int) -> Optional[float]:
    """Mean of available z-scores for stock idx across the group's factors."""
    vals = [zl[idx] for zl in z_lists if zl[idx] is not None]
    return sum(vals) / len(vals) if vals else None


# Swing-trading factor weights: momentum leads, quality confirms
GROUP_WEIGHTS = {"momentum": 0.35, "quality": 0.30, "value": 0.20, "low_risk": 0.15}


def cross_sectional_rank(rows: list[dict]) -> list[dict]:
    """
    rows: per-stock dicts with raw fundamentals + price factors.
    Adds z-composites, final score (0-100), flags, verdict; returns
    the list sorted best-first.
    """
    n = len(rows)
    if n == 0:
        return rows

    def col(key, transform=None):
        out = []
        for r in rows:
            v = r.get(key)
            if v is not None and transform:
                try:
                    v = transform(v)
                except Exception:
                    v = None
            out.append(v)
        return _zscores(_winsorize(out))

    # ── factor z-scores (higher = better for every factor) ──────────────────
    mom_z = [
        col("ret_3m"),
        col("ret_6m"),
        col("prox_52w"),
        col("risk_adj_mom"),
        col("mom_12_1"),
    ]
    qual_z = [
        col("piotroski_score"),
        col("altman_z"),
        col("roce"),
        col("roe"),
    ]
    val_z = [
        col("earnings_yield"),
        col("pe_ratio", lambda v: 1.0 / v if v > 0 else None),   # inverse P/E
        col("pb_ratio", lambda v: 1.0 / v if v > 0 else None),   # inverse P/B
        col("dividend_yield"),
    ]
    risk_z = [
        col("atr_pct",        lambda v: -v),   # lower volatility = better
        col("vol_ann",        lambda v: -v),
        col("debt_to_equity", lambda v: -v),   # lower leverage = better
    ]

    groups = {"momentum": mom_z, "quality": qual_z, "value": val_z, "low_risk": risk_z}

    for i, r in enumerate(rows):
        gz: dict = {}
        for name, zl in groups.items():
            gz[name] = _group_z(zl, i)

        # Weighted composite; renormalize over the groups that have data
        avail = {k: v for k, v in gz.items() if v is not None}
        if avail:
            wsum = sum(GROUP_WEIGHTS[k] for k in avail)
            composite = sum(GROUP_WEIGHTS[k] * v for k, v in avail.items()) / wsum
        else:
            composite = None

        r["z_momentum"] = round(gz["momentum"], 2) if gz["momentum"] is not None else None
        r["z_quality"]  = round(gz["quality"],  2) if gz["quality"]  is not None else None
        r["z_value"]    = round(gz["value"],    2) if gz["value"]    is not None else None
        r["z_low_risk"] = round(gz["low_risk"], 2) if gz["low_risk"] is not None else None
        r["composite_z"] = round(composite, 3) if composite is not None else None
        r["score"] = round(_norm_cdf(composite) * 100, 1) if composite is not None else None

        # ── hard flags ────────────────────────────────────────────────────────
        flags = []
        ben = r.get("beneish_m")
        alt = r.get("altman_z")
        pio = r.get("piotroski_score")
        rsi = r.get("rsi")
        if ben is not None and ben > -1.78:
            flags.append("Manipulation risk (Beneish M > -1.78)")
        if alt is not None and alt <= 1.1:
            flags.append("Financial distress (Altman Z″ ≤ 1.1)")
        if pio is not None and pio <= 3:
            flags.append("Weak fundamentals (Piotroski <= 3)")
        if rsi is not None and rsi > 75:
            flags.append("Overbought (RSI > 75)")
        if r.get("trend_score", 0) < 0:
            flags.append("Below 200-DMA (against trend)")
        r["flags"] = flags

        # ── verdict ───────────────────────────────────────────────────────────
        hard_fail = any("Manipulation" in f or "distress" in f for f in flags)
        score = r["score"] or 0
        if hard_fail:
            r["verdict"] = "Avoid"
        elif score >= 70 and r.get("trend_score", 0) >= 1 and pio is not None and pio >= 6:
            r["verdict"] = "Strong Candidate"
        elif score >= 60:
            r["verdict"] = "Buy Watch"
        elif score >= 40:
            r["verdict"] = "Neutral"
        else:
            r["verdict"] = "Avoid"

    rows.sort(key=lambda r: (r["score"] is not None, r["score"] or 0), reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows
