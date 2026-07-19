"""
decision_engine.py
Turns daily candles + price factors + quant scores into actionable,
horizon-specific trade plans (swing: days-weeks, positional: weeks-months).

Every level (entry / stop / target) is anchored to detected chart structure
(fractal pivot supports/resistances, MA50/MA200) with ATR math as floor/cap,
and carries a human-readable `basis`/`rationale` explaining why it was chosen.

Pure functions, no I/O. Indicator math is reused from swing_engine.
"""

from __future__ import annotations

from typing import Optional

import price_action
import swing_engine

DISCLAIMER = (
    "Educational analysis only — not investment advice. "
    "Price data is delayed (Yahoo Finance)."
)

MIN_CANDLES = 60


def _r2(v) -> Optional[float]:
    return round(v, 2) if v is not None else None


# ── support / resistance detection ────────────────────────────────────────────

def find_pivots(candles: list, span: int = 5, cluster_pct: float = 1.5,
                max_levels: int = 6) -> dict:
    """
    Fractal swing points over the trailing ~250 candles: a pivot high is a bar
    whose high exceeds the highs of `span` bars on each side (mirror for lows).
    Levels within cluster_pct% of each other are merged into one, weighted by
    touch count. Split around the latest close into supports (below, nearest
    first) and resistances (above, nearest first).
    """
    window = candles[-250:]
    if len(window) < 2 * span + 1:
        return {"supports": [], "resistances": []}

    highs = [c.get("high", c.get("close")) for c in window]
    lows  = [c.get("low",  c.get("close")) for c in window]
    dates = [c.get("date", "") for c in window]
    price = window[-1].get("close")
    if not price:
        return {"supports": [], "resistances": []}

    raw = []  # (level, date)
    for i in range(span, len(window) - span):
        h, l = highs[i], lows[i]
        if h is not None and h > max(highs[i - span:i]) and h > max(highs[i + 1:i + span + 1]):
            raw.append((h, dates[i]))
        if l is not None and l < min(lows[i - span:i]) and l < min(lows[i + 1:i + span + 1]):
            raw.append((l, dates[i]))

    if not raw:
        return {"supports": [], "resistances": []}

    # Cluster nearby levels (weighted mean by touch count)
    raw.sort(key=lambda t: t[0])
    clusters = []
    for level, date in raw:
        if clusters and (level - clusters[-1]["price"]) / clusters[-1]["price"] * 100 <= cluster_pct:
            c = clusters[-1]
            c["price"] = (c["price"] * c["touches"] + level) / (c["touches"] + 1)
            c["touches"] += 1
            c["last_touch"] = max(c["last_touch"], date)
        else:
            clusters.append({"price": level, "touches": 1, "last_touch": date})

    for c in clusters:
        c["price"] = round(c["price"], 2)

    supports    = sorted((c for c in clusters if c["price"] < price),
                         key=lambda c: -c["price"])[:max_levels]
    resistances = sorted((c for c in clusters if c["price"] >= price),
                         key=lambda c: c["price"])[:max_levels]
    return {"supports": supports, "resistances": resistances}


def _nearest_support(price: float, pivots: dict, ma50=None, ma200=None,
                     below: Optional[float] = None) -> Optional[dict]:
    """
    Nearest support candidate below `below` (default: price). Pivot levels
    plus MA50/MA200 as soft candidates. Returns {"price", "kind", "touches"}.
    """
    ceiling = below if below is not None else price
    cands = [{"price": s["price"], "kind": "pivot", "touches": s["touches"]}
             for s in pivots.get("supports", []) if s["price"] < ceiling]
    for ma, name in ((ma50, "MA50"), (ma200, "MA200")):
        if ma and ma < ceiling:
            cands.append({"price": round(ma, 2), "kind": name, "touches": 1})
    return max(cands, key=lambda c: c["price"]) if cands else None


def _nearest_resistance(price: float, pivots: dict,
                        above: Optional[float] = None) -> Optional[dict]:
    floor_ = above if above is not None else price
    cands = [r for r in pivots.get("resistances", []) if r["price"] > floor_]
    return min(cands, key=lambda r: r["price"]) if cands else None


# ── setup detection ───────────────────────────────────────────────────────────

def detect_setup(factors: dict, pivots: dict, ma50=None, ma200=None,
                 high_52w: Optional[float] = None,
                 pa: Optional[dict] = None) -> dict:
    """
    Classify the current chart into breakout / pullback / trend_continuation /
    none. `pa` is price_action.analyze()["signals"] — used as a present-day
    confirmation layer in the evidence. Returns {"setup", "label", "evidence"}.
    """
    price   = factors.get("price")
    rsi     = factors.get("rsi")
    macd_h  = factors.get("macd_hist")
    trend   = factors.get("trend_score", 0)
    vol_r   = factors.get("vol_ratio")
    prox52  = factors.get("prox_52w")
    pa      = pa or {}

    near_res = _nearest_resistance(price, pivots)

    # Breakout: pressing into / through overhead resistance or the 52w high on volume
    at_resistance = (near_res and price >= near_res["price"] * 0.98) or \
                    (prox52 is not None and prox52 >= 0.98)
    if at_resistance and (vol_r or 0) >= 1.3 and trend >= 1:
        ev = []
        if prox52 is not None and prox52 >= 0.98:
            ev.append(f"Within {round((1 - prox52) * 100, 1)}% of 52-week high")
        if near_res:
            ev.append(f"Testing resistance at {near_res['price']} ({near_res['touches']} touches)")
        ev.append(f"Volume surge {vol_r}x vs 60-day average")
        # Bar quality: a real breakout closes strong, a trap closes weak
        crq = (pa.get("close_range") or {}).get("last")
        if crq is not None:
            if crq >= 0.67:
                ev.append(f"Closed in the top third of the day's range ({int(crq*100)}%) — buyers in control")
            elif crq <= 0.33:
                ev.append(f"Weak close ({int(crq*100)}% of range) — breakout may be a trap")
        if (pa.get("tightness") or {}).get("contracting"):
            ev.append("Breaking out of a volatility contraction — highest-odds breakout context")
        return {"setup": "breakout", "label": "Breakout attempt at resistance / 52-week high",
                "evidence": ev}

    # Pullback: healthy uptrend resting on the 50-DMA or a pivot support
    near_sup = _nearest_support(price, pivots)
    near_ma50 = ma50 and abs(price - ma50) / price * 100 <= 3
    near_pivot = near_sup and near_sup["kind"] == "pivot" and \
        (price - near_sup["price"]) / price * 100 <= 3
    above_200 = not ma200 or price > ma200
    if trend >= 1 and above_200 and rsi is not None and 35 <= rsi <= 55 and \
            (near_ma50 or near_pivot):
        anchor = "rising 50-DMA" if near_ma50 else f"support at {near_sup['price']}"
        ev = [f"Price within 3% of {anchor}",
              f"RSI {rsi} — reset, not oversold",
              "Above 200-DMA" if ma200 else "Long-term MA unavailable"]
        pvc = pa.get("pullback_volume") or {}
        if pvc.get("state") == "dry_up":
            ev.append("Volume drying up on the pullback — sellers exhausted")
        elif pvc.get("state") == "expansion":
            ev.append("Caution: volume expanding on the pullback — may be distribution, not a dip")
        return {"setup": "pullback", "label": f"Pullback toward {anchor}", "evidence": ev}

    # Trend continuation: strong aligned trend with momentum and clear air overhead
    res_headroom = not near_res or (near_res["price"] - price) / price * 100 > 5
    if trend == 2 and rsi is not None and 50 <= rsi <= 70 and \
            (macd_h or 0) > 0 and res_headroom:
        ev = ["Price > MA50 > MA200 (aligned uptrend)",
              f"RSI {rsi} — momentum without excess",
              "MACD histogram positive"]
        if res_headroom and near_res:
            ev.append(f"Next resistance {round((near_res['price'] - price) / price * 100, 1)}% above")
        return {"setup": "trend_continuation", "label": "Established uptrend continuation",
                "evidence": ev}

    label = "No long setup — downtrend" if trend < 0 else "No actionable setup currently"
    return {"setup": "none", "label": label, "evidence": []}


# ── plan builders ─────────────────────────────────────────────────────────────

def _targets_from_risk(entry_mid: float, risk: float, pivots: dict,
                       mults=(1.5, 2.5)) -> list:
    """R-multiple targets; T1 capped at the nearest overhead resistance."""
    targets = []
    for i, m in enumerate(mults):
        t = entry_mid + m * risk
        basis = f"{m}R"
        if i == 0:
            res = _nearest_resistance(entry_mid, pivots, above=entry_mid * 1.01)
            if res and res["price"] < t:
                t = res["price"]
                basis = f"{m}R capped at resistance {res['price']} ({res['touches']} touches)"
        rr = round((t - entry_mid) / risk, 2) if risk > 0 else None
        targets.append({"label": f"T{i + 1}", "price": round(t, 2), "basis": basis, "rr": rr})
    return targets


def _no_trade_plan(horizon: str, setup: dict, factors: dict, reason: str) -> dict:
    return {
        "horizon": horizon, "verdict": "Avoid",
        "setup": setup["setup"], "setup_label": setup["label"],
        "evidence": setup["evidence"], "confidence": 10,
        "entry": None, "stop": None, "targets": [], "risk_reward": None,
        "invalidation": None, "notes": [reason],
        "flags": [reason],
    }


def _confidence(factors: dict, setup: dict, quant_component: float) -> int:
    """0-100: trend (30) + setup quality (25) + quant/momentum (25) + RSI sanity (20)."""
    trend = factors.get("trend_score", 0)
    trend_pts = {2: 30, 1: 20, 0: 10}.get(trend, 0)

    setup_pts = 8 if setup["setup"] == "none" else min(25, 10 + 5 * len(setup["evidence"]))

    rsi = factors.get("rsi")
    if rsi is None:               rsi_pts = 10
    elif 40 <= rsi <= 65:         rsi_pts = 20
    elif 65 < rsi <= 75:          rsi_pts = 10
    elif rsi > 75:                rsi_pts = 0
    else:                         rsi_pts = 8   # < 40: washed out

    return int(min(100, max(0, trend_pts + setup_pts + quant_component + rsi_pts)))


def _intraday_stop_refinement(entry_low: float, entry_mid: float,
                              daily_stop: float, atr: float,
                              intraday_candles: Optional[list]) -> Optional[dict]:
    """
    Tighten the daily-structure stop using lower-timeframe (1H) swing lows.
    Finds fractal pivot lows on the intraday series that sit BETWEEN the
    daily stop and the entry zone; the highest such level is finer structure
    the daily chart cannot see. The refined stop goes 0.15 daily-ATR below it.
    Returns {"price", "anchor", "bars"} or None when no refinement applies.
    """
    if not intraday_candles or len(intraday_candles) < 40:
        return None
    lows = [c.get("low", c.get("close")) for c in intraday_candles]
    span = 3
    pivot_lows = []
    for i in range(span, len(lows) - span):
        if lows[i] < min(lows[i - span:i]) and lows[i] < min(lows[i + 1:i + span + 1]):
            pivot_lows.append(lows[i])
    # Candidate must be real structure between the daily stop and the entry
    cands = [p for p in pivot_lows if daily_stop < p < entry_low]
    if not cands:
        return None
    anchor = max(cands)
    refined = round(anchor - 0.15 * atr, 2)
    if refined <= daily_stop or refined >= entry_low:
        return None
    # Refuse silly-tight stops: keep at least 0.6 ATR of room from entry mid
    if entry_mid - refined < 0.6 * atr:
        return None
    return {"price": refined, "anchor": round(anchor, 2),
            "bars": len(intraday_candles)}


def build_swing_plan(factors: dict, pivots: dict, setup: dict,
                     ma50=None, ma200=None,
                     intraday_candles: Optional[list] = None) -> dict:
    """Days-to-weeks technical plan: setup entry band, ATR/structure stop, R-multiple targets."""
    price = factors["price"]
    atr   = factors.get("atr")
    rsi   = factors.get("rsi")
    trend = factors.get("trend_score", 0)

    if trend < 0 or (ma200 and price < ma200):
        return _no_trade_plan("swing", setup, factors,
                              "Price below 200-DMA / downtrend — no long swing setup")
    if not atr:
        return _no_trade_plan("swing", setup, factors, "ATR unavailable — insufficient data")

    # ── entry zone ────────────────────────────────────────────────────────────
    notes, flags = [], []
    kind = setup["setup"]
    if kind == "breakout":
        near_res = _nearest_resistance(price, pivots)
        trigger = near_res["price"] if near_res else price
        entry_low, entry_high = trigger, trigger + 0.5 * atr
        rationale = f"Breakout band above resistance/trigger at {round(trigger, 2)}"
    elif kind == "pullback":
        sup = _nearest_support(price, pivots, ma50, ma200)
        anchor = sup["price"] if sup else price - atr
        entry_low, entry_high = anchor - 0.5 * atr, anchor + 0.5 * atr
        which = sup["kind"] if sup else "recent lows"
        rationale = f"Band around {which} support at {round(anchor, 2)}"
    elif kind == "trend_continuation":
        entry_low, entry_high = price - 0.5 * atr, price + 0.5 * atr
        rationale = "Trend continuation — enter near current price"
    else:
        # Uptrend but no active setup: stage a dip-buy at the nearest support
        sup = _nearest_support(price, pivots, ma50, ma200)
        if sup and (price - sup["price"]) / price * 100 <= 10:
            entry_low, entry_high = sup["price"] - 0.5 * atr, sup["price"] + 0.5 * atr
            rationale = f"No active setup — stage a dip-buy at {sup['kind']} support {sup['price']}"
        else:
            return _no_trade_plan("swing", setup, factors,
                                  "Uptrend but no setup and no nearby support to stage an entry")

    entry_mid = (entry_low + entry_high) / 2

    # ── stop: 2-ATR math floored by structure ─────────────────────────────────
    atr_stop = entry_low - 2 * atr
    sup_below = _nearest_support(price, pivots, ma50, ma200, below=entry_low)
    struct_stop = sup_below["price"] - 0.25 * atr if sup_below else None
    if struct_stop is not None and struct_stop > atr_stop:
        stop_price, basis = struct_stop, "structure"
        stop_rationale = (f"0.25 ATR below {sup_below['kind']} support "
                          f"{sup_below['price']} (tighter than 2-ATR stop)")
    else:
        stop_price, basis = atr_stop, "atr"
        stop_rationale = "2 ATR below entry zone low"
        if sup_below:
            stop_rationale += f" (below {sup_below['kind']} support {sup_below['price']})"

    # Lower-timeframe refinement: hourly swing lows expose finer structure
    # between the daily stop and the entry, allowing a tighter stop with
    # the same invalidation logic.
    refined = _intraday_stop_refinement(entry_low, entry_mid, stop_price,
                                        atr, intraday_candles)
    if refined:
        stop_price, basis = refined["price"], "intraday_structure"
        stop_rationale = (f"0.15 ATR below the 1H swing low {refined['anchor']} "
                          f"(tightened from the daily-structure stop)")

    risk = entry_mid - stop_price
    if risk <= 0:
        return _no_trade_plan("swing", setup, factors, "Could not derive a valid stop below entry")
    risk_pct = risk / entry_mid * 100

    targets = _targets_from_risk(entry_mid, risk, pivots)
    rr = targets[0]["rr"] if targets else None

    # ── verdict ───────────────────────────────────────────────────────────────
    if rsi is not None and rsi > 75:
        verdict = "Wait"
        notes.append(f"RSI {rsi} — overbought; wait for a cooldown or pullback")
    elif entry_low <= price <= entry_high:
        verdict = "Buy" if kind != "none" else "Buy on Dip"
    elif price > entry_high:
        verdict = "Buy on Dip"
        notes.append(f"Price {price} is above the entry band — wait for a dip to "
                     f"{round(entry_low, 2)}–{round(entry_high, 2)}")
    else:  # price below entry band (untriggered breakout)
        verdict = "Wait"
        notes.append(f"Entry triggers on a move into {round(entry_low, 2)}–{round(entry_high, 2)}")

    if rr is not None and rr < 1.2:
        flags.append(f"Weak risk:reward ({rr}) — T1 capped by nearby resistance")
        if verdict in ("Buy", "Buy on Dip"):
            verdict = "Wait"

    invalidation = f"Plan invalid if a daily close is below ₹{round(stop_price, 2)}"
    if kind == "breakout":
        invalidation += (f", or if price falls back below the trigger "
                         f"₹{round(entry_low, 2)} within 3 sessions")

    if rsi is not None and 40 <= rsi <= 60:
        notes.append(f"RSI {rsi} — room to run")

    return {
        "horizon": "swing", "verdict": verdict,
        "setup": kind, "setup_label": setup["label"], "evidence": setup["evidence"],
        "confidence": _confidence(factors, setup,
                                  12.5 + (6 if (factors.get("ret_3m") or 0) > 0 else 0)),
        "entry": {"low": round(entry_low, 2), "high": round(entry_high, 2),
                  "type": kind, "rationale": rationale},
        "stop": {"price": round(stop_price, 2), "basis": basis,
                 "rationale": stop_rationale, "risk_pct": round(risk_pct, 2)},
        "targets": targets,
        "risk_reward": rr,
        "invalidation": invalidation,
        "notes": notes, "flags": flags,
    }


def _fundamentals_gate(quant: Optional[dict]) -> dict:
    """Hard-fail on distress/manipulation, soft-cap on weak quality."""
    if not quant:
        return {"status": "unavailable",
                "reasons": ["Fundamental data unavailable — plan is technicals-only"]}

    reasons, status = [], "pass"
    alt = quant.get("altman", {})
    ben = quant.get("beneish", {})
    pio = quant.get("piotroski", {})
    comp = quant.get("composite_quality_score")

    if alt.get("zone") == "Distress":
        status = "hard_fail"
        reasons.append(f"Altman Z {alt.get('z_score')} — financial distress zone")
    if ben.get("m_score") is not None and ben["m_score"] > -1.78:
        status = "hard_fail"
        reasons.append(f"Beneish M {ben.get('m_score')} — earnings-manipulation risk")

    if status != "hard_fail":
        if pio.get("score") is not None and pio["score"] <= 4:
            status = "soft_fail"
            reasons.append(f"Piotroski {pio['score']}/9 — weak fundamentals")
        if comp is not None and comp < 40:
            status = "soft_fail"
            reasons.append(f"Composite quality {comp}/100 — below threshold")

    if status == "pass":
        if pio.get("score") is not None:
            reasons.append(f"Piotroski {pio['score']}/9")
        if alt.get("zone"):
            reasons.append(f"Altman {alt['zone']}")
        if comp is not None:
            reasons.append(f"Quality composite {comp}/100")

    return {"status": status, "reasons": reasons}


def build_positional_plan(factors: dict, pivots: dict, setup: dict,
                          quant: Optional[dict] = None,
                          ma50=None, ma200=None,
                          candles: Optional[list] = None) -> dict:
    """Weeks-to-months plan: wider structure stops, measured-move target, MA trail exit."""
    price = factors["price"]
    atr   = factors.get("atr")
    trend = factors.get("trend_score", 0)
    prox52 = factors.get("prox_52w")

    gate = _fundamentals_gate(quant)
    quant_pts = 12.5
    if quant and quant.get("composite_quality_score") is not None:
        quant_pts = quant["composite_quality_score"] / 100 * 25

    def _finish_no_trade(reason: str) -> dict:
        p = _no_trade_plan("positional", setup, factors, reason)
        p["fundamentals_gate"] = gate
        p["exit_rule"] = None
        return p

    if gate["status"] == "hard_fail":
        return _finish_no_trade("Fundamental hard-fail: " + "; ".join(gate["reasons"]))
    if trend <= 0:
        return _finish_no_trade("No positional long while price is below/at long-term averages")
    if not atr:
        return _finish_no_trade("ATR unavailable — insufficient data")

    highs = [c.get("high", c.get("close")) for c in (candles or [])][-252:]
    high_52w = max(highs) if highs else None

    # ── entry zone (±1 ATR bands) ─────────────────────────────────────────────
    notes, flags = [], []
    if prox52 is not None and prox52 >= 0.95 and setup["setup"] == "breakout":
        anchor = high_52w or price
        entry_low, entry_high = anchor, anchor + atr
        rationale = f"Positional breakout above the 52-week high {round(anchor, 2)}"
        entry_type = "breakout"
    elif ma50 and trend == 2:
        entry_low, entry_high = ma50 - atr, ma50 + atr
        rationale = "Accumulation band around the rising 50-DMA (price > MA50 > MA200)"
        entry_type = "pullback"
    else:
        sup = _nearest_support(price, pivots, ma50, ma200)
        if not sup:
            return _finish_no_trade("No support structure to anchor a positional entry")
        entry_low, entry_high = sup["price"] - atr, sup["price"] + atr
        rationale = f"Accumulation band around {sup['kind']} support {sup['price']}"
        entry_type = "pullback"

    entry_mid = (entry_low + entry_high) / 2

    # ── stop: major swing low or MA200, whichever is nearer to price ─────────
    major = [s for s in pivots.get("supports", [])
             if s["touches"] >= 2 and s["price"] < entry_low]
    cands = []
    if major:
        m = max(major, key=lambda s: s["price"])
        cands.append((m["price"], f"major swing low {m['price']} ({m['touches']} touches)"))
    if ma200 and ma200 < entry_low:
        cands.append((ma200, f"200-DMA {round(ma200, 2)}"))
    if not cands:
        cands.append((entry_low - 3 * atr, "3 ATR below entry (no structure below)"))
    anchor_price, anchor_desc = max(cands, key=lambda c: c[0])
    stop_price = anchor_price - 0.5 * atr
    risk = entry_mid - stop_price
    if risk <= 0:
        return _finish_no_trade("Could not derive a valid positional stop below entry")
    risk_pct = risk / entry_mid * 100

    # ── T1: measured move from the recent consolidation range, capped at 25% ──
    rng_high = rng_low = None
    if candles and len(candles) >= 60:
        seg = candles[-60:]
        rng_high = max(c.get("high", c.get("close")) for c in seg)
        rng_low  = min(c.get("low",  c.get("close")) for c in seg)
    if rng_high and rng_low and rng_high > rng_low:
        measured = entry_mid + (rng_high - rng_low)
        t1 = min(measured, entry_mid * 1.25)
        basis = (f"Measured move: 60-day range height {round(rng_high - rng_low, 2)} "
                 f"projected from entry")
        if t1 < measured:
            basis += " (capped at +25%)"
    else:
        t1 = entry_mid + 2.5 * risk
        basis = "2.5R (range data unavailable for measured move)"
    rr = round((t1 - entry_mid) / risk, 2)
    targets = [{"label": "T1", "price": round(t1, 2), "basis": basis, "rr": rr}]
    exit_rule = "Trail: exit on a daily close below the 50-DMA"

    # ── verdict (gate-capped) ─────────────────────────────────────────────────
    if entry_low <= price <= entry_high:
        verdict = "Buy"
    elif price > entry_high:
        verdict = "Buy on Dip"
        notes.append(f"Price {price} is above the accumulation band — add on a dip to "
                     f"{round(entry_low, 2)}–{round(entry_high, 2)}")
    else:
        verdict = "Wait"
        notes.append(f"Entry triggers on a move into {round(entry_low, 2)}–{round(entry_high, 2)}")

    if gate["status"] == "soft_fail" and verdict in ("Buy", "Buy on Dip"):
        verdict = "Wait"
        flags.append("Verdict capped at Wait: " + "; ".join(gate["reasons"]))

    invalidation = (f"Plan invalid if a daily close is below ₹{round(stop_price, 2)} "
                    f"({anchor_desc})")

    return {
        "horizon": "positional", "verdict": verdict,
        "setup": entry_type, "setup_label": setup["label"], "evidence": setup["evidence"],
        "confidence": _confidence(factors, setup, quant_pts),
        "entry": {"low": round(entry_low, 2), "high": round(entry_high, 2),
                  "type": entry_type, "rationale": rationale},
        "stop": {"price": round(stop_price, 2), "basis": "structure",
                 "rationale": f"0.5 ATR below {anchor_desc}", "risk_pct": round(risk_pct, 2)},
        "targets": targets,
        "risk_reward": rr,
        "invalidation": invalidation,
        "exit_rule": exit_rule,
        "fundamentals_gate": gate,
        "notes": notes, "flags": flags,
    }


# ── orchestrator ──────────────────────────────────────────────────────────────

def build_trade_plans(candles: list, fundamentals: Optional[dict] = None,
                      quant: Optional[dict] = None,
                      intraday_candles: Optional[list] = None) -> dict:
    """
    candles: [{date, open, high, low, close, volume}, ...] oldest first.
    Returns the full trade-plans envelope, or {"error": ...} on thin history.
    """
    if not candles or len(candles) < MIN_CANDLES:
        return {"error": "insufficient price history for trade plans"}

    factors = swing_engine.compute_price_factors(candles)
    if not factors:
        return {"error": "insufficient price history for trade plans"}

    closes = [c["close"] for c in candles if c.get("close")]
    price  = closes[-1]
    ma50   = sum(closes[-50:])  / 50  if len(closes) >= 50  else None
    ma200  = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
    highs  = [c.get("high", c.get("close")) for c in candles if c.get("close")]
    high_52w = max(highs[-252:]) if highs else None

    pivots = find_pivots(candles)
    pa = price_action.analyze(candles)
    setup  = detect_setup(factors, pivots, ma50, ma200, high_52w,
                          pa=pa["signals"])

    swing = build_swing_plan(factors, pivots, setup, ma50, ma200,
                             intraday_candles=intraday_candles)
    positional = build_positional_plan(factors, pivots, setup, quant,
                                       ma50, ma200, candles)

    return {
        "as_of": candles[-1].get("date"),
        "price": round(price, 2),
        "atr":   factors.get("atr"),
        "price_action": pa,
        "key_levels": {
            "supports":    pivots["supports"],
            "resistances": pivots["resistances"],
            "ma50":  _r2(ma50),
            "ma200": _r2(ma200),
            "high_52w": _r2(high_52w),
        },
        "swing": swing,
        "positional": positional,
        "disclaimer": DISCLAIMER,
    }
