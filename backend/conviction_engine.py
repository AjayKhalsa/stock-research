"""
conviction_engine.py
Evidence layer that turns a trade-plan verdict into an argued case, using the
techniques systematic funds apply, adapted for a single retail account:

  1. Setup base rates (event study): find every historical occurrence of the
     currently-detected setup in the stock's own ~5y history, simulate the
     same stop/target rules forward, and report win rate / average R /
     expected value. "Trust the signal because it worked N times here."
  2. Expected value: EV(R) = win% x avg win R - loss% x avg loss R. A pretty
     R:R with a poor hit rate is a losing trade; EV exposes that.
  3. Market regime: NIFTY trend + volatility state. Long setups degrade badly
     in Risk-Off tape; institutions gate every signal on regime first.
  4. Relative strength: excess return vs NIFTY (institutions buy leaders,
     not laggards).
  5. Trend template: Minervini-style 8-point pass/fail checklist.
  6. Evidence ledger: every signal becomes a weighted bull/bear entry that
     nets to a transparent 0-100 conviction score.

Pure functions except the NIFTY cache (module-level, TTL 30 min).
All computations are on daily candles [{date, open, high, low, close, volume}].
"""

from __future__ import annotations

import math
from typing import Optional

import price_action

# ── rolling indicator series (aligned to candles; None until warm-up) ─────────

def _sma_series(vals: list, period: int) -> list:
    out = [None] * len(vals)
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= period:
            s -= vals[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


def _rsi_series(closes: list, period: int = 14) -> list:
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / period, losses / period
    out[period] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def _atr_series(highs: list, lows: list, closes: list, period: int = 14) -> list:
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
               abs(lows[i] - closes[i - 1])) for i in range(1, n)]
    atr = sum(trs[:period]) / period
    out[period] = atr
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i + 1] = atr
    return out


def _ema_series(vals: list, period: int) -> list:
    n = len(vals)
    out = [None] * n
    if n < period:
        return out
    k = 2.0 / (period + 1)
    ema = sum(vals[:period]) / period
    out[period - 1] = ema
    for i in range(period, n):
        ema = vals[i] * k + ema * (1 - k)
        out[i] = ema
    return out


def _macd_hist_series(closes: list) -> list:
    n = len(closes)
    e12, e26 = _ema_series(closes, 12), _ema_series(closes, 26)
    macd = [None if (e12[i] is None or e26[i] is None) else e12[i] - e26[i]
            for i in range(n)]
    first = next((i for i, v in enumerate(macd) if v is not None), None)
    out = [None] * n
    if first is None or n - first < 9:
        return out
    sig = _ema_series([v for v in macd[first:]], 9)
    for j, s in enumerate(sig):
        if s is not None:
            out[first + j] = macd[first + j] - s
    return out


# ── setup detection masks (must mirror decision_engine.detect_setup rules) ────

def _setup_signal(kind: str, i: int, closes, highs, vols,
                  ma50, ma200, rsi, macdh, atr) -> bool:
    """Was setup `kind` active at bar i? (uses only data up to bar i)"""
    c = closes[i]
    if ma200[i] is None or ma50[i] is None or rsi[i] is None or atr[i] is None:
        return False

    if kind == "trend_continuation":
        return (c > ma50[i] > ma200[i] and 50 <= rsi[i] <= 70
                and (macdh[i] or 0) > 0)

    if kind == "pullback":
        near_ma50 = abs(c - ma50[i]) / c * 100 <= 3
        return (c > ma200[i] and ma50[i] > ma200[i]
                and 35 <= rsi[i] <= 55 and near_ma50)

    if kind == "breakout":
        if i < 60:
            return False
        hi = max(highs[max(0, i - 250):i])          # prior high, excl. today
        v20 = sum(vols[i - 19:i + 1]) / 20
        v60 = sum(vols[i - 59:i + 1]) / 60
        vol_surge = v60 > 0 and v20 / v60 >= 1.3
        return c >= hi * 0.98 and vol_surge and c > ma200[i]

    return False


def setup_base_rates(candles: list, setup_kind: str,
                     stop_atr: float = 2.0, target_r: float = 1.5,
                     max_hold: int = 40, min_gap: int = 10) -> dict:
    """
    Event study: every historical bar where `setup_kind` fired, enter at close,
    stop = 2 ATR below, target = +1.5R, exit at stop/target/timeout (40 bars,
    mark-to-market). Same-bar stop+target counts as a stop (conservative).

    Returns {n, wins, win_rate, avg_r, expected_r, median_hold, verdict_text}
    or {"n": 0, ...} when the setup never fired / not enough history.
    """
    empty = {"n": 0, "wins": None, "win_rate": None, "avg_r": None,
             "expected_r": None, "median_hold": None,
             "note": "No comparable historical setups found on this stock."}
    if setup_kind not in ("trend_continuation", "pullback", "breakout"):
        return {**empty, "note": "Base rates need an active setup (none detected)."}
    if not candles or len(candles) < 260:
        return {**empty, "note": "Needs ~1 year+ of price history."}

    closes = [c["close"] for c in candles]
    highs  = [c.get("high", c["close"]) for c in candles]
    lows   = [c.get("low",  c["close"]) for c in candles]
    vols   = [c.get("volume", 0) for c in candles]

    ma50  = _sma_series(closes, 50)
    ma200 = _sma_series(closes, 200)
    rsi   = _rsi_series(closes)
    macdh = _macd_hist_series(closes)
    atr   = _atr_series(highs, lows, closes)

    results, holds = [], []
    last_sig = -10**9
    # leave max_hold bars of runway; skip the most recent 5 bars (open trades)
    for i in range(200, len(candles) - 5):
        if i - last_sig < min_gap:
            continue
        if not _setup_signal(setup_kind, i, closes, highs, vols,
                             ma50, ma200, rsi, macdh, atr):
            continue
        last_sig = i
        entry = closes[i]
        stop = entry - stop_atr * atr[i]
        risk = entry - stop
        if risk <= 0:
            continue
        target = entry + target_r * risk
        r_out, hold = None, None
        end = min(i + max_hold, len(candles) - 1)
        for j in range(i + 1, end + 1):
            if lows[j] <= stop:                 # stop first (conservative)
                r_out, hold = -1.0, j - i
                break
            if highs[j] >= target:
                r_out, hold = target_r, j - i
                break
        if r_out is None:                       # timeout: mark to market
            r_out, hold = (closes[end] - entry) / risk, end - i
        results.append(r_out)
        holds.append(hold)

    if len(results) < 5:
        return {**empty,
                "n": len(results),
                "note": f"Only {len(results)} comparable setups since "
                        f"{candles[0].get('date', '?')} — too few to trust."}

    wins = sum(1 for r in results if r > 0)
    win_rate = wins / len(results)
    avg_r = sum(results) / len(results)
    holds.sort()
    return {
        "n": len(results),
        "wins": wins,
        "win_rate": round(win_rate * 100, 1),
        "avg_r": round(avg_r, 2),
        "expected_r": round(avg_r, 2),          # avg R IS the per-trade EV
        "median_hold": holds[len(holds) // 2],
        "since": candles[0].get("date"),
        "note": (f"{len(results)} comparable {setup_kind.replace('_', ' ')} setups "
                 f"since {candles[0].get('date', '?')[:4]}: {wins} winners "
                 f"({round(win_rate * 100)}%), average {avg_r:+.2f}R per trade "
                 f"(2-ATR stop, {target_r}R target, {max_hold}-bar timeout)."),
    }


# ── Minervini-style trend template ─────────────────────────────────────────────

def trend_template(candles: list, excess_3m: Optional[float] = None) -> dict:
    """8-point pass/fail checklist adapted from Minervini's trend template."""
    if not candles or len(candles) < 60:
        return {"score": None, "max_score": 8, "items": []}

    closes = [c["close"] for c in candles]
    highs  = [c.get("high", c["close"]) for c in candles]
    lows   = [c.get("low",  c["close"]) for c in candles]
    price  = closes[-1]

    ma50  = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    ma150 = sum(closes[-150:]) / 150 if len(closes) >= 150 else None
    ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
    ma200_prev = (sum(closes[-220:-20]) / 200) if len(closes) >= 220 else None
    lo_52w = min(lows[-252:]) if len(lows) >= 60 else None
    hi_52w = max(highs[-252:]) if len(highs) >= 60 else None

    items = []
    def add(label, ok, detail):
        items.append({"label": label, "pass": bool(ok), "detail": detail})

    if ma50 and ma150 and ma200:
        add("Price above MA50 > MA150 > MA200",
            price > ma50 > ma150 > ma200,
            f"price {price:.0f} / MA50 {ma50:.0f} / MA150 {ma150:.0f} / MA200 {ma200:.0f}")
    else:
        add("Price above MA50 > MA150 > MA200", False, "insufficient history")

    add("200-DMA rising (vs 1 month ago)",
        ma200 is not None and ma200_prev is not None and ma200 > ma200_prev,
        "long-term trend direction")

    add("At least 25% above 52-week low",
        lo_52w and price >= lo_52w * 1.25,
        f"52w low {lo_52w:.0f}" if lo_52w else "n/a")

    add("Within 25% of 52-week high",
        hi_52w and price >= hi_52w * 0.75,
        f"52w high {hi_52w:.0f}" if hi_52w else "n/a")

    add("Outperforming NIFTY over 3 months",
        excess_3m is not None and excess_3m > 0,
        f"excess return {excess_3m * 100:+.1f}%" if excess_3m is not None else "index data unavailable")

    # Accumulation: 50-day up/down volume ratio + A/D line direction
    udr = price_action.up_down_volume_ratio(candles, window=50)
    ad = price_action.ad_line_signal(candles)
    add("Net accumulation: up/down volume ratio > 1 (50d)",
        udr is not None and udr > 1.0,
        (f"ratio {udr}" if udr is not None else "n/a")
        + (f", A/D line {ad['state']}" if ad.get("state") else ""))

    add("Not a penny stock (price above ₹20)", price > 20, f"₹{price:.2f}")

    # Volatility contraction: current ATR% below its 6-month median
    atr = _atr_series(highs, lows, closes)
    atr_pcts = [atr[i] / closes[i] * 100 for i in range(len(closes))
                if atr[i] is not None and closes[i] > 0][-126:]
    if len(atr_pcts) >= 30:
        cur = atr_pcts[-1]
        med = sorted(atr_pcts)[len(atr_pcts) // 2]
        add("Volatility contracting (ATR% below 6-month median)",
            cur <= med, f"now {cur:.2f}% vs median {med:.2f}%")
    else:
        add("Volatility contracting (ATR% below 6-month median)", False,
            "insufficient history")

    return {"score": sum(1 for it in items if it["pass"]),
            "max_score": len(items), "items": items}


# ── relative strength vs index ─────────────────────────────────────────────────

def _ret(closes: list, lookback: int) -> Optional[float]:
    if len(closes) <= lookback or closes[-1 - lookback] == 0:
        return None
    return closes[-1] / closes[-1 - lookback] - 1.0


def relative_strength(candles: list, index_candles: list) -> dict:
    """Excess returns vs the index over 1M/3M/6M + RS-line new-high flag."""
    out = {"excess_1m": None, "excess_3m": None, "excess_6m": None,
           "rs_line_new_high": None, "label": "Index data unavailable"}
    if not candles or not index_candles or len(index_candles) < 30:
        return out
    sc = [c["close"] for c in candles]
    ic = [c["close"] for c in index_candles]
    for key, lb in (("excess_1m", 21), ("excess_3m", 63), ("excess_6m", 126)):
        sr, ir = _ret(sc, lb), _ret(ic, lb)
        if sr is not None and ir is not None:
            out[key] = round(sr - ir, 4)

    # RS line = stock/index ratio on the overlapping window (by date)
    idx_by_date = {c["date"]: c["close"] for c in index_candles}
    rs_line = [c["close"] / idx_by_date[c["date"]]
               for c in candles if c["date"] in idx_by_date and idx_by_date[c["date"]]]
    if len(rs_line) >= 60:
        window = rs_line[-252:]
        out["rs_line_new_high"] = window[-1] >= max(window) * 0.995

    e3 = out["excess_3m"]
    if e3 is not None:
        if e3 > 0.05:      out["label"] = f"Market leader: beating NIFTY by {e3*100:.1f}% over 3M"
        elif e3 > 0:       out["label"] = f"Mild outperformer: +{e3*100:.1f}% vs NIFTY over 3M"
        elif e3 > -0.05:   out["label"] = f"Mild laggard: {e3*100:.1f}% vs NIFTY over 3M"
        else:              out["label"] = f"Market laggard: {e3*100:.1f}% vs NIFTY over 3M"
    return out


# ── market regime (NIFTY) ──────────────────────────────────────────────────────

def market_regime(index_candles: list) -> dict:
    """
    Tape check on the NIFTY: trend (vs MA50/MA200), realized-vol percentile,
    drawdown from 52w high -> Risk-On / Neutral / Risk-Off with guidance.
    """
    out = {"regime": "Unknown", "label": "Index data unavailable",
           "guidance": "Could not fetch NIFTY data — treat signals with extra caution.",
           "nifty": None, "trend": None, "vol_percentile": None, "drawdown_pct": None}
    if not index_candles or len(index_candles) < 210:
        return out

    closes = [c["close"] for c in index_candles]
    price = closes[-1]
    ma50 = sum(closes[-50:]) / 50
    ma200 = sum(closes[-200:]) / 200
    hi_52w = max(closes[-252:])
    drawdown = (price / hi_52w - 1) * 100

    # 20-day realized vol, percentile over trailing year
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
            if closes[i - 1] > 0]
    def _vol(seg):
        if len(seg) < 15:
            return None
        m = sum(seg) / len(seg)
        return math.sqrt(sum((r - m) ** 2 for r in seg) / (len(seg) - 1)) * math.sqrt(252)
    vols = [_vol(rets[i - 20:i]) for i in range(20, len(rets) + 1)]
    vols = [v for v in vols if v is not None][-252:]
    vol_pct = None
    if vols:
        cur = vols[-1]
        vol_pct = round(sum(1 for v in vols if v <= cur) / len(vols) * 100)

    trend = ("up" if price > ma50 > ma200 else
             "recovering" if price > ma200 else
             "down")

    # O'Neil market health: heavy-volume down days on the index itself
    dist_days = price_action.distribution_days(index_candles)

    if trend == "up" and (vol_pct is None or vol_pct < 80) and (dist_days or 0) < 5:
        regime, label = "risk_on", "Risk-On"
        guidance = ("NIFTY in an uptrend with contained volatility — long setups "
                    "have tailwind; normal aggression is justified.")
    elif trend == "down" or (vol_pct is not None and vol_pct >= 90) \
            or (dist_days is not None and dist_days >= 6):
        regime, label = "risk_off", "Risk-Off"
        guidance = ("NIFTY below its 200-DMA, in a volatility spike, or under heavy "
                    "distribution — most long setups fail in this tape. Demand "
                    "A-grade setups only, expect stops to get hit more often, or stand aside.")
    else:
        regime, label = "neutral", "Neutral"
        guidance = ("Mixed tape — NIFTY above its 200-DMA but not fully trending. "
                    "Be selective; favour market leaders with high base-rate EV.")
    if dist_days is not None and dist_days >= 4:
        guidance += (f" Note: {dist_days} distribution days on the NIFTY in the last "
                     f"25 sessions — institutions are selling into strength.")

    return {"regime": regime, "label": label, "guidance": guidance,
            "nifty": round(price, 1), "trend": trend,
            "ma50": round(ma50, 1), "ma200": round(ma200, 1),
            "vol_percentile": vol_pct, "drawdown_pct": round(drawdown, 1),
            "distribution_days": dist_days,
            "as_of": index_candles[-1].get("date")}


# ── evidence ledger + conviction ───────────────────────────────────────────────

def build_case(plan: dict, quant: Optional[dict], base_rates: dict,
               template: dict, rs: dict, regime: dict,
               factors: Optional[dict] = None,
               pa_evidence: Optional[list] = None) -> dict:
    """
    Assemble the weighted bull/bear evidence ledger and net conviction (0-100).
    Every entry: {side: 'bull'|'bear', points, text, source}. Conviction =
    50 + sum(bull points) - sum(bear points), clamped to [2, 98].
    """
    ledger = []
    def bull(points, text, source):
        ledger.append({"side": "bull", "points": points, "text": text, "source": source})
    def bear(points, text, source):
        ledger.append({"side": "bear", "points": points, "text": text, "source": source})

    # 1. Setup & trend (from the trade plan)
    setup = plan.get("setup", "none")
    if setup != "none" and plan.get("entry"):
        bull(10, f"Active {setup.replace('_', ' ')} setup: {plan.get('setup_label')}", "technicals")
    elif plan.get("verdict") == "Avoid":
        bear(15, plan.get("notes", ["No long setup"])[0] if plan.get("notes")
             else "No long setup", "technicals")

    # 2. Trend template
    ts, tmax = template.get("score"), template.get("max_score", 8)
    if ts is not None:
        if ts >= 6:
            bull(10, f"Trend template {ts}/{tmax} — institutional-grade uptrend structure", "checklist")
        elif ts >= 4:
            bull(4, f"Trend template {ts}/{tmax} — partial uptrend structure", "checklist")
        else:
            bear(8, f"Trend template only {ts}/{tmax} — weak technical structure", "checklist")

    # 3. Base rates / expected value (the core "convince me" number)
    ev = base_rates.get("expected_r")
    n = base_rates.get("n", 0)
    if ev is not None and n >= 5:
        wr = base_rates.get("win_rate")
        if ev >= 0.3:
            bull(15, f"History is on your side: {n} comparable setups, {wr}% win rate, "
                     f"{ev:+.2f}R expected value per trade", "base_rates")
        elif ev > 0:
            bull(6, f"Mildly positive history: {n} setups, {wr}% wins, {ev:+.2f}R per trade", "base_rates")
        else:
            bear(15, f"History argues AGAINST this: {n} comparable setups averaged "
                     f"{ev:+.2f}R ({wr}% wins) — this setup has lost money on this stock", "base_rates")
    else:
        bear(3, base_rates.get("note", "No base-rate history available"), "base_rates")

    # 4. Relative strength
    e3 = rs.get("excess_3m")
    if e3 is not None:
        if e3 > 0.05:
            bull(8, rs["label"], "relative_strength")
            if rs.get("rs_line_new_high"):
                bull(4, "RS line at a 52-week high — classic institutional accumulation signal",
                     "relative_strength")
        elif e3 > 0:
            bull(3, rs["label"], "relative_strength")
        else:
            bear(8, rs["label"] + " — institutions buy leaders, not laggards", "relative_strength")

    # 5. Fundamentals (quant scores)
    if quant:
        pio = (quant.get("piotroski") or {}).get("score")
        alt = (quant.get("altman") or {})
        ben = (quant.get("beneish") or {})
        comp = quant.get("composite_quality_score")
        if ben.get("m_score") is not None and ben["m_score"] > -1.78:
            bear(20, f"Beneish M-Score {ben['m_score']} flags earnings-manipulation risk — "
                     f"a hard disqualifier for any horizon beyond a quick swing", "fundamentals")
        if alt.get("zone") == "Distress":
            bear(15, f"Altman Z {alt.get('z_score')} in the distress zone (caveat: "
                     f"unreliable for banks/NBFCs)", "fundamentals")
        if pio is not None:
            if pio >= 7:
                bull(8, f"Piotroski {pio}/9 — fundamentals improving on most fronts", "fundamentals")
            elif pio <= 3:
                bear(8, f"Piotroski {pio}/9 — deteriorating fundamentals", "fundamentals")
        if comp is not None and comp >= 70:
            bull(4, f"Composite quality {comp}/100", "fundamentals")
    else:
        bear(2, "Fundamental data unavailable — case rests on technicals alone", "fundamentals")

    # 5b. Price action & volume (pre-weighted by price_action.analyze)
    for e in (pa_evidence or []):
        ledger.append({"side": e["side"], "points": e["points"],
                       "text": e["text"], "source": "price_action"})

    # 6. Market regime (gate, applied last)
    if regime.get("regime") == "risk_on":
        bull(6, f"Tape supports longs: {regime['label']} — {regime.get('trend')} trend, "
                f"vol at {regime.get('vol_percentile')}th percentile", "regime")
    elif regime.get("regime") == "risk_off":
        bear(12, f"Tape is against you: NIFTY {regime.get('trend')}trend, "
                 f"drawdown {regime.get('drawdown_pct')}% — long setups fail more often here", "regime")

    # 7. Risk:reward from the plan
    rr = plan.get("risk_reward")
    if rr is not None:
        if rr >= 2:
            bull(5, f"Asymmetric payoff: {rr}:1 reward-to-risk at the planned levels", "plan")
        elif rr < 1.2:
            bear(6, f"Poor payoff: only {rr}:1 reward-to-risk — resistance caps the upside", "plan")

    bull_pts = sum(e["points"] for e in ledger if e["side"] == "bull")
    bear_pts = sum(e["points"] for e in ledger if e["side"] == "bear")
    conviction = max(2, min(98, 50 + bull_pts - bear_pts))

    # Final call: verdict x conviction
    verdict = plan.get("verdict", "Wait")
    if verdict in ("Buy", "Buy on Dip"):
        if conviction >= 70:   final = f"High-conviction {verdict}"
        elif conviction >= 50: final = verdict
        else:                  final = f"Low-conviction {verdict} — evidence is mixed, size down or skip"
    elif verdict == "Wait":
        final = "Wait — " + ("strong stock, no entry yet" if conviction >= 60
                             else "no edge worth paying for right now")
    else:
        final = "Avoid — the evidence stack is against a long here"

    ledger.sort(key=lambda e: -e["points"])
    return {
        "conviction": conviction,
        "bull_points": bull_pts,
        "bear_points": bear_pts,
        "final_call": final,
        "ledger": ledger,
    }


def synthesize_verdicts(trade_plans: dict, quant: Optional[dict],
                        ai_thesis: Optional[dict] = None) -> dict:
    """
    The Bottom Line: reconcile the three lenses — trade setup (chart,
    days-weeks), business quality (financials, quarters-years), and the AI
    analyst (blended narrative) — into a named disagreement pattern and one
    plain-language directive per horizon. Disagreement between lenses is
    information: they answer DIFFERENT questions, and the pattern of who
    says what IS the playbook.
    """
    swing = trade_plans.get("swing") or {}
    positional = trade_plans.get("positional") or {}
    case = (trade_plans.get("dossier") or {}).get("case") or {}
    quant = quant or {}

    trade_score = case.get("conviction")
    trade_verdict = swing.get("verdict", "Wait")

    business_score = quant.get("composite_quality_score")
    pio = (quant.get("piotroski") or {}).get("score")
    alt = quant.get("altman") or {}
    ben = quant.get("beneish") or {}
    gate = positional.get("fundamentals_gate") or {}
    biz_bits = []
    if pio is not None:
        biz_bits.append(f"Piotroski {pio}/9")
    if alt.get("zone"):
        biz_bits.append(f"Altman {alt['zone']}")
    if gate.get("status"):
        biz_bits.append(f"gate: {gate['status'].replace('_', ' ')}")

    ai_score = (ai_thesis or {}).get("conviction_score")
    ai_label = (ai_thesis or {}).get("conviction_label")
    ai_comment = (ai_thesis or {}).get("plan_commentary") or ""
    ai_available = ai_score is not None
    ai_pending = ai_thesis is None   # /plan endpoint: alpha hasn't run yet

    lenses = [
        {"key": "trade", "label": "Trade Setup", "score": trade_score,
         "verdict": trade_verdict, "horizon": "days–weeks",
         "question": "Is this a good trade right now?",
         "detail": swing.get("setup_label", "")},
        {"key": "business", "label": "Business Quality", "score": business_score,
         "verdict": ("Strong" if (business_score or 0) >= 65 else
                     "Weak" if business_score is not None and business_score < 45 else
                     "Average" if business_score is not None else "Unknown"),
         "horizon": "quarters–years",
         "question": "Is this a good business to own?",
         "detail": ", ".join(biz_bits) if biz_bits else "fundamental data unavailable"},
        {"key": "ai", "label": "AI Analyst", "score": ai_score,
         "verdict": ai_label if ai_available else ("pending" if ai_pending else "unavailable"),
         "horizon": "blended",
         "question": "Narrative judge weighing everything",
         "detail": ai_comment[:180] if ai_comment else ""},
    ]

    t = trade_score if trade_score is not None else 0
    b = business_score if business_score is not None else 50   # unknown = neutral

    hard_fail = (alt.get("zone") == "Distress" or
                 (ben.get("m_score") is not None and ben["m_score"] > -1.78))

    entry, stop = swing.get("entry") or {}, swing.get("stop") or {}
    targets = swing.get("targets") or []
    t1 = targets[0]["price"] if targets else None
    plan_line = ""
    if entry.get("low") is not None:
        plan_line = (f"entry {entry['low']}–{entry['high']}, stop {stop.get('price')}"
                     + (f", T1 {t1}" if t1 else ""))

    gate_reason = "; ".join(gate.get("reasons", [])[:1]) or "weak fundamentals"

    # ── pattern playbook (priority order) ─────────────────────────────────────
    if hard_fail:
        which = ("Beneish manipulation risk" if ben.get("m_score") is not None
                 and ben["m_score"] > -1.78 else "Altman distress zone")
        pattern, pattern_label = "hard_disqualified", f"Disqualified — {which}"
        directives = {
            "swing": "Do not trade. Accounting red flags make even the chart untrustworthy — "
                     "stops don't protect against fraud gaps.",
            "positional": f"Do not own. {which} is a hard disqualifier "
                          "(caveat: Altman is unreliable for banks/NBFCs — verify sector).",
            "long_term": "Not investable until the red flag clears in fresh annual numbers.",
        }
        reconciliation = (f"Whatever the chart ({t}) or narrative says, the forensic "
                          f"accounting layer failed ({which}). Institutions never override "
                          f"a forensic red flag with a technical signal.")
    elif t >= 65 and b >= 60 and gate.get("status") in ("pass", "unavailable", None):
        pattern, pattern_label = "aligned_bull", "Aligned — chart and business agree"
        directives = {
            "swing": f"Take the trade per the plan{': ' + plan_line if plan_line else ''}. "
                     f"Conviction {t}.",
            "positional": (f"Cleared to build: {positional.get('verdict', 'see plan')} — "
                           + (positional.get('entry', {}) or {}).get('rationale', 'see positional plan.')
                           if positional.get("verdict") in ("Buy", "Buy on Dip")
                           else f"Positional plan says {positional.get('verdict', 'Wait')} — "
                                f"follow its entry band rather than chasing."),
            "long_term": f"Quality {business_score}/100 supports holding winners — "
                         f"let the positional exit rule (not impatience) take you out.",
        }
        reconciliation = (f"Rare alignment: the chart ({t}) and the business ({business_score}) "
                          f"point the same way. These are the setups to be aggressive on — "
                          f"subject to the market regime.")
    elif t >= 65 and (b < 55 or gate.get("status") == "soft_fail"):
        pattern, pattern_label = "momentum_trade", "Momentum trade — rent it, don't own it"
        directives = {
            "swing": f"Take the swing trade per the plan{': ' + plan_line if plan_line else ''}. "
                     f"The chart earns it (conviction {t}).",
            "positional": f"Do not build a position — {gate_reason}. "
                          f"The positional plan is capped at {positional.get('verdict', 'Wait')} for a reason.",
            "long_term": f"Not an investment at current quality ({business_score if business_score is not None else '?'}/100). "
                         f"Exit at targets or stop — never average down, never 'convert' a failed trade into a hold.",
        }
        reconciliation = (f"These scores don't contradict — they answer different questions. "
                          f"The chart ({t}) says buyers control the next few weeks; the financials "
                          f"({business_score if business_score is not None else 'unknown'}, {gate_reason}) say the business "
                          f"hasn't earned a long-term hold. Classic momentum trade: strict stops, "
                          f"take profits at targets, no emotional attachment.")
    elif t < 45 and b >= 65:
        pattern, pattern_label = "quality_watch", "Good business, bad chart — stalk it"
        directives = {
            "swing": "No trade — there is no setup to attach a stop to. Buying quality into a "
                     "falling chart is how drawdowns compound.",
            "positional": "Arm an entry alert at the plan's accumulation band and wait for the "
                          "chart to base (reclaim the 200-DMA / form higher lows).",
            "long_term": f"Quality {business_score}/100 justifies patient interest — the edge is in "
                         f"WAITING for the technical turn, not anticipating it.",
        }
        reconciliation = (f"The business ({business_score}) is better than the chart ({t}). "
                          f"Institutions handle this by stalking, not buying: quality names go on "
                          f"the watchlist and get bought when the chart confirms, because 'cheap "
                          f"and falling' usually gets cheaper first.")
    elif t < 45 and b < 55:
        pattern, pattern_label = "no_edge", "No edge — avoid"
        directives = {
            "swing": "No setup, no trade.",
            "positional": "Nothing to accumulate — both the chart and the business argue against it.",
            "long_term": "Not a candidate. Spend your attention on stocks where at least one lens is strong.",
        }
        reconciliation = (f"Chart ({t}) and business ({business_score if business_score is not None else 'unknown'}) "
                          f"both weak — there is no disagreement to resolve and no edge to argue about.")
    else:
        pattern, pattern_label = "mixed", "Marginal edge — let the regime decide"
        directives = {
            "swing": f"Only in a Risk-On tape, at reduced size{': ' + plan_line if plan_line else ''}. "
                     f"Marginal setups need a market tailwind to be worth the risk.",
            "positional": f"Positional plan says {positional.get('verdict', 'Wait')} — no urgency either way.",
            "long_term": "Neither strong enough to own nor weak enough to dismiss — revisit next quarter.",
        }
        reconciliation = (f"Neither lens is decisive (chart {t}, business "
                          f"{business_score if business_score is not None else 'unknown'}). When your own signals "
                          f"are lukewarm, the market regime is the tiebreaker — take marginal trades "
                          f"only with the tape at your back.")

    # ── AI dissent: surfaced, never silently overriding ───────────────────────
    dissent = None
    if ai_available and trade_score is not None and abs(ai_score - trade_score) >= 20:
        reason = ai_comment or ((ai_thesis or {}).get("bear_case") or "").split(". ")[0]
        dissent = {
            "who": "ai",
            "gap": abs(ai_score - trade_score),
            "reason": (f"The AI analyst scores this {ai_score} vs the trade engine's {trade_score}. "
                       + (f"Its reasoning: {reason}" if reason else
                          "It weighs the fundamental/narrative risks more heavily than the chart."))
        }

    return {
        "lenses": lenses,
        "pattern": pattern,
        "pattern_label": pattern_label,
        "directives": directives,
        "reconciliation": reconciliation,
        "dissent": dissent,
    }


def build_dossier(candles: list, plan_envelope: dict, quant: Optional[dict],
                  index_candles: list, factors: Optional[dict] = None) -> dict:
    """
    Full evidence dossier for one stock. `plan_envelope` is the output of
    decision_engine.build_trade_plans; the swing plan drives setup/base rates.
    """
    regime = market_regime(index_candles)
    rs = relative_strength(candles, index_candles)
    template = trend_template(candles, excess_3m=rs.get("excess_3m"))

    swing = plan_envelope.get("swing") or {}
    base_rates = setup_base_rates(candles, swing.get("setup", "none"))

    pa = plan_envelope.get("price_action") or {}
    case = build_case(swing, quant, base_rates, template, rs, regime, factors,
                      pa_evidence=pa.get("evidence"))

    return {
        "regime": regime,
        "relative_strength": rs,
        "trend_template": template,
        "base_rates": base_rates,
        "price_action": pa.get("signals", {}),
        "case": case,
    }
