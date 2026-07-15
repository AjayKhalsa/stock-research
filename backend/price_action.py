"""
price_action.py
Price-action & volume analysis — the footprints institutional money leaves in
OHLCV data. These signals confirm or veto setups; they are computed on the
CURRENT chart (present-day confirmation layer), while base rates in
conviction_engine stay on the simpler historical conditions for comparability.

Signals (all pure functions on daily candles [{date, open, high, low, close, volume}]):
  - OBV and Chaikin A/D line slope vs price slope (confirmation / divergence)
  - Up/down volume ratio (50d) — accumulation vs distribution balance
  - Distribution days (O'Neil): heavy-volume down days in the last 25 sessions
  - Pocket pivots (Kacher/Morales): up-day volume > every down-day volume of
    the prior 10 days — an institutional buying signature
  - Pullback volume character: dry-up (healthy) vs expansion (distribution)
  - Close-in-range quality: where the close sits within the bar's range
  - Market structure: HH/HL vs LH/LL from the raw fractal pivot sequence
  - Tightness: VCP-lite contraction of successive pullbacks + NR7 flag
  - Climax volume: exhaustion spike after an extended run
"""

from __future__ import annotations

from typing import Optional


def _closes(candles):  return [c["close"] for c in candles]
def _highs(candles):   return [c.get("high", c["close"]) for c in candles]
def _lows(candles):    return [c.get("low", c["close"]) for c in candles]
def _vols(candles):    return [c.get("volume", 0) or 0 for c in candles]


def _slope_pct(series: list, window: int = 20) -> Optional[float]:
    """% change of a series over the trailing window (simple, robust)."""
    if len(series) < window + 1:
        return None
    a, b = series[-1 - window], series[-1]
    if a == 0:
        return None
    return (b - a) / abs(a)


# ── volume flow ───────────────────────────────────────────────────────────────

def _obv_series(candles: list) -> list:
    closes, vols = _closes(candles), _vols(candles)
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + vols[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - vols[i])
        else:
            obv.append(obv[-1])
    return obv


def obv_signal(candles: list, window: int = 20) -> dict:
    """
    OBV slope vs price slope over the window:
      confirming | bullish_divergence (price down, OBV up — accumulation into
      weakness) | bearish_divergence (price up, OBV down — rally not funded)
    """
    if len(candles) < window + 5 or sum(_vols(candles)[-window:]) == 0:
        return {"state": None, "detail": "insufficient volume data"}
    obv = _obv_series(candles)
    # OBV can cross zero, so slope on a shifted series: use raw delta vs mean |OBV|
    delta = obv[-1] - obv[-1 - window]
    scale = max(abs(v) for v in obv[-window:]) or 1
    obv_dir = delta / scale
    px = _slope_pct(_closes(candles), window) or 0

    if px >= 0 and obv_dir >= 0:
        state, detail = "confirming", "volume flow confirms the price trend"
    elif px < 0 and obv_dir > 0.02:
        state, detail = "bullish_divergence", "price weak but OBV rising — accumulation into weakness"
    elif px > 0 and obv_dir < -0.02:
        state, detail = "bearish_divergence", "price up but OBV falling — the rally is not being funded by volume"
    elif px < 0 and obv_dir < 0:
        state, detail = "confirming_down", "volume flow confirms the downtrend"
    else:
        state, detail = "flat", "no clear volume-flow signal"
    return {"state": state, "detail": detail}


def ad_line_signal(candles: list, window: int = 20) -> dict:
    """Chaikin A/D line (close-location-value x volume) direction over window."""
    if len(candles) < window + 5:
        return {"state": None}
    ad = [0.0]
    for c in candles:
        h, l, cl, v = c.get("high", c["close"]), c.get("low", c["close"]), c["close"], c.get("volume", 0) or 0
        rng = h - l
        clv = ((cl - l) - (h - cl)) / rng if rng > 0 else 0.0
        ad.append(ad[-1] + clv * v)
    delta = ad[-1] - ad[-1 - window]
    scale = max(abs(v) for v in ad[-window:]) or 1
    d = delta / scale
    state = "rising" if d > 0.02 else "falling" if d < -0.02 else "flat"
    return {"state": state}


def up_down_volume_ratio(candles: list, window: int = 50) -> Optional[float]:
    """Ratio of total volume on up days vs down days over the window."""
    if len(candles) < window + 1:
        window = len(candles) - 1
    if window < 15:
        return None
    closes, vols = _closes(candles), _vols(candles)
    up = dn = 0
    for i in range(len(candles) - window, len(candles)):
        if closes[i] >= closes[i - 1]:
            up += vols[i]
        else:
            dn += vols[i]
    if dn == 0:
        return None if up == 0 else 9.99
    return round(up / dn, 2)


def distribution_days(candles: list, window: int = 25) -> Optional[int]:
    """O'Neil distribution days: close <= -0.2% on volume above the prior day."""
    if len(candles) < window + 2:
        return None
    closes, vols = _closes(candles), _vols(candles)
    count = 0
    for i in range(len(candles) - window, len(candles)):
        if vols[i] == 0:
            continue
        chg = closes[i] / closes[i - 1] - 1 if closes[i - 1] else 0
        if chg <= -0.002 and vols[i] > vols[i - 1]:
            count += 1
    return count


def pocket_pivots(candles: list, lookback: int = 10, window: int = 15) -> list:
    """
    Pocket pivots in the last `window` bars: an UP day whose volume exceeds the
    highest DOWN-day volume of the preceding `lookback` days.
    """
    if len(candles) < lookback + window + 1:
        return []
    closes, vols = _closes(candles), _vols(candles)
    out = []
    for i in range(len(candles) - window, len(candles)):
        if closes[i] <= closes[i - 1]:
            continue
        down_vols = [vols[j] for j in range(i - lookback, i)
                     if closes[j] < closes[j - 1]]
        if down_vols and vols[i] > max(down_vols) and vols[i] > 0:
            out.append(candles[i].get("date", ""))
    return out


def pullback_volume_character(candles: list) -> dict:
    """
    If price sits below its 10-day high (i.e. pulling back), compare pullback
    volume to the 50d average: dry-up (<70%) is healthy supply exhaustion,
    expansion (>120%) is distribution.
    """
    if len(candles) < 60:
        return {"state": None}
    closes, highs, vols = _closes(candles), _highs(candles), _vols(candles)
    hi10 = max(highs[-10:])
    price = closes[-1]
    if price >= hi10 * 0.995:
        return {"state": "not_in_pullback", "detail": "price at/near recent highs"}
    # bars since the 10d-high bar
    hi_idx = len(candles) - 10 + highs[-10:].index(hi10)
    pull_vols = vols[hi_idx + 1:] or vols[-3:]
    avg50 = sum(vols[-50:]) / 50
    if avg50 == 0 or not pull_vols:
        return {"state": None}
    ratio = (sum(pull_vols) / len(pull_vols)) / avg50
    if ratio < 0.7:
        return {"state": "dry_up", "ratio": round(ratio, 2),
                "detail": f"pullback volume {round(ratio*100)}% of 50d average — sellers exhausted"}
    if ratio > 1.2:
        return {"state": "expansion", "ratio": round(ratio, 2),
                "detail": f"pullback volume {round(ratio*100)}% of 50d average — institutions may be selling"}
    return {"state": "normal", "ratio": round(ratio, 2),
            "detail": "pullback volume unremarkable"}


def close_range_quality(candles: list) -> dict:
    """Close position within the daily range: last bar + avg of last 10 up-days."""
    if not candles:
        return {"last": None, "avg_up_days": None}
    def pos(c):
        h, l = c.get("high", c["close"]), c.get("low", c["close"])
        return (c["close"] - l) / (h - l) if h > l else 0.5
    last = round(pos(candles[-1]), 2)
    closes = _closes(candles)
    ups = [pos(candles[i]) for i in range(max(1, len(candles) - 30), len(candles))
           if closes[i] > closes[i - 1]][-10:]
    return {"last": last,
            "avg_up_days": round(sum(ups) / len(ups), 2) if ups else None}


# ── price structure ───────────────────────────────────────────────────────────

def market_structure(candles: list, span: int = 5) -> dict:
    """
    Raw (unclustered, chronological) fractal pivots over ~180 bars; classify
    the last few swings: HH/HL uptrend, LH/LL downtrend, or mixed.
    """
    window = candles[-180:]
    if len(window) < 2 * span + 10:
        return {"state": None, "detail": "insufficient history"}
    highs, lows = _highs(window), _lows(window)
    piv_h, piv_l = [], []
    for i in range(span, len(window) - span):
        if highs[i] > max(highs[i - span:i]) and highs[i] > max(highs[i + 1:i + span + 1]):
            piv_h.append(highs[i])
        if lows[i] < min(lows[i - span:i]) and lows[i] < min(lows[i + 1:i + span + 1]):
            piv_l.append(lows[i])
    if len(piv_h) < 2 or len(piv_l) < 2:
        return {"state": "mixed", "detail": "too few swings to classify"}
    hh = piv_h[-1] > piv_h[-2]
    hl = piv_l[-1] > piv_l[-2]
    if hh and hl:
        return {"state": "uptrend", "detail": "higher highs and higher lows intact"}
    if not hh and not hl:
        return {"state": "downtrend", "detail": "lower highs and lower lows — structure broken"}
    return {"state": "mixed",
            "detail": "higher highs but lower lows" if hh else "higher lows but lower highs (coiling)"}


def tightness(candles: list) -> dict:
    """
    VCP-lite: are successive pullbacks contracting? Plus NR7 flag (yesterday's
    range narrowest of the last 7) — tightness precedes powerful breakouts.
    """
    if len(candles) < 60:
        return {"contracting": None, "nr7": None}
    highs, lows = _highs(candles), _lows(candles)
    # split trailing 60 bars into 3 x 20-bar windows, measure range% of each
    ranges = []
    for k in (3, 2, 1):
        seg_h = highs[-20 * k: -20 * (k - 1) or None]
        seg_l = lows[-20 * k: -20 * (k - 1) or None]
        hi, lo = max(seg_h), min(seg_l)
        ranges.append((hi - lo) / hi * 100 if hi > 0 else 0)
    contracting = ranges[0] > ranges[1] > ranges[2]
    day_ranges = [highs[i] - lows[i] for i in range(len(candles) - 7, len(candles))]
    nr7 = day_ranges[-1] == min(day_ranges)
    return {"contracting": contracting, "nr7": nr7,
            "ranges_pct": [round(r, 1) for r in ranges]}


def climax_volume(candles: list) -> dict:
    """Exhaustion: latest volume >= 3x the 50d average after a >=25% 3-month run."""
    if len(candles) < 70:
        return {"state": None}
    closes, vols = _closes(candles), _vols(candles)
    avg50 = sum(vols[-51:-1]) / 50
    run = closes[-1] / closes[-64] - 1 if len(closes) > 64 and closes[-64] else 0
    if avg50 > 0 and vols[-1] >= 3 * avg50 and run >= 0.25:
        return {"state": "climax", "detail":
                f"volume {round(vols[-1]/avg50, 1)}x average after a {round(run*100)}% 3-month run — possible exhaustion"}
    return {"state": "none"}


# ── orchestrator ──────────────────────────────────────────────────────────────

def analyze(candles: list) -> dict:
    """
    Run all detectors; return {"signals": {...}, "evidence": [{side, points, text}]}.
    Evidence entries are pre-weighted for conviction_engine's ledger.
    """
    if not candles or len(candles) < 30:
        return {"signals": {}, "evidence": []}

    obv   = obv_signal(candles)
    ad    = ad_line_signal(candles)
    udr   = up_down_volume_ratio(candles)
    dd    = distribution_days(candles)
    pp    = pocket_pivots(candles)
    pvc   = pullback_volume_character(candles)
    crq   = close_range_quality(candles)
    ms    = market_structure(candles)
    tight = tightness(candles)
    clx   = climax_volume(candles)

    signals = {
        "obv": obv, "ad_line": ad, "up_down_volume_ratio": udr,
        "distribution_days": dd, "pocket_pivots": pp,
        "pullback_volume": pvc, "close_range": crq,
        "structure": ms, "tightness": tight, "climax": clx,
    }

    ev = []
    def bull(points, text): ev.append({"side": "bull", "points": points, "text": text})
    def bear(points, text): ev.append({"side": "bear", "points": points, "text": text})

    if ms["state"] == "uptrend":
        bull(6, "Market structure intact: higher highs and higher lows")
    elif ms["state"] == "downtrend":
        bear(8, "Market structure broken: lower highs and lower lows")

    if obv["state"] == "confirming":
        bull(5, "OBV confirms the trend — volume is funding the move")
    elif obv["state"] == "bearish_divergence":
        bear(7, "Bearish volume divergence: price rising but OBV falling — " + obv["detail"])
    elif obv["state"] == "bullish_divergence":
        bull(5, "Bullish volume divergence: " + obv["detail"])

    if dd is not None and dd >= 4:
        bear(8, f"{dd} distribution days in the last 25 sessions — institutional selling pressure")
    elif dd is not None and dd <= 1:
        bull(3, f"Only {dd} distribution day(s) in 25 sessions — no meaningful selling pressure")

    if pp:
        bull(5, f"Pocket pivot on {pp[-1]} — up-day volume swamped every down-day of the prior 10 sessions")

    if pvc.get("state") == "dry_up":
        bull(6, "Volume drying up on the pullback — " + pvc["detail"])
    elif pvc.get("state") == "expansion":
        bear(6, "Volume expanding on the pullback — " + pvc["detail"])

    if udr is not None:
        if udr >= 1.5:
            bull(4, f"Up/down volume ratio {udr} over 50 days — net accumulation")
        elif udr <= 0.67:
            bear(4, f"Up/down volume ratio {udr} over 50 days — net distribution")

    if tight.get("contracting"):
        txt = "Volatility contraction pattern: each pullback shallower than the last"
        if tight.get("nr7"):
            txt += " + NR7 (tightest range in 7 days)"
        bull(4, txt)

    if clx.get("state") == "climax":
        bear(5, "Climax volume warning: " + clx["detail"])

    return {"signals": signals, "evidence": ev}
