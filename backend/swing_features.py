"""Deterministic Phase-A swing features.

All calculations operate only on supplied candles.  There is no network, AI,
or mutable state here, which keeps daily snapshots reproducible and backtests
safe once point-in-time inputs are supplied.
"""

from __future__ import annotations

import math
from statistics import median, pstdev
from typing import Optional


def _number(value) -> Optional[float]:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _closes(candles: list[dict]) -> list[float]:
    return [value for value in (_number(row.get("close")) for row in candles)
            if value is not None and value > 0]


def resistance_zones(candles: list[dict], span: int = 4,
                     cluster_pct: float = 1.5) -> list[dict]:
    """Cluster historical pivot highs without misclassifying them as support."""
    rows = candles[-252:]
    if len(rows) < span * 2 + 1:
        return []
    highs = [_number(row.get("high")) or _number(row.get("close")) for row in rows]
    pivots = []
    for index in range(span, len(rows) - span):
        high = highs[index]
        neighbours = highs[index - span:index] + highs[index + 1:index + span + 1]
        if high is not None and all(value is not None for value in neighbours) \
                and high > max(neighbours):
            pivots.append({"price": high, "date": rows[index].get("date")})

    zones = []
    for pivot in sorted(pivots, key=lambda item: item["price"]):
        if zones and (pivot["price"] - zones[-1]["mid"]) / zones[-1]["mid"] * 100 <= cluster_pct:
            zone = zones[-1]
            count = zone["touches"]
            zone["low"] = min(zone["low"], pivot["price"])
            zone["high"] = max(zone["high"], pivot["price"])
            zone["mid"] = (zone["mid"] * count + pivot["price"]) / (count + 1)
            zone["touches"] += 1
            zone["last_touch"] = max(str(zone["last_touch"] or ""), str(pivot["date"] or ""))
        else:
            zones.append({
                "low": pivot["price"], "high": pivot["price"], "mid": pivot["price"],
                "touches": 1, "last_touch": pivot["date"],
            })
    for zone in zones:
        for key in ("low", "high", "mid"):
            zone[key] = round(zone[key], 2)
    return zones


def assess_overhead_supply(candles: list[dict], entry_high: Optional[float],
                           atr: Optional[float]) -> dict:
    price = _number(entry_high) or (_closes(candles)[-1] if _closes(candles) else None)
    atr = _number(atr)
    zones = resistance_zones(candles)
    overhead = [zone for zone in zones if price is not None and zone["high"] > price]
    overhead.sort(key=lambda zone: zone["low"])
    next_zone = overhead[0] if overhead else None
    clear_air_pct = None
    clear_air_atr = None
    if price and next_zone:
        clear_air = max(0.0, next_zone["low"] - price)
        clear_air_pct = clear_air / price * 100
        clear_air_atr = clear_air / atr if atr else None

    if next_zone is None:
        score = 100.0
        severity = "clear"
    else:
        distance_score = _clamp((clear_air_pct or 0) * 6)
        atr_score = _clamp((clear_air_atr or 0) * 18)
        touch_penalty = min(25, max(0, next_zone["touches"] - 1) * 6)
        score = _clamp(distance_score * 0.55 + atr_score * 0.45 - touch_penalty)
        severity = "severe" if (clear_air_atr or 0) < 1.25 \
            else "crowded" if (clear_air_atr or 0) < 2.5 else "acceptable"

    return {
        "score": round(score, 1),
        "severity": severity,
        "clear_air_pct": round(clear_air_pct, 2) if clear_air_pct is not None else None,
        "clear_air_atr": round(clear_air_atr, 2) if clear_air_atr is not None else None,
        "next_resistance": next_zone,
        "zones": overhead[:5],
    }


def _efficiency(values: list[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    travelled = sum(abs(values[index] - values[index - 1]) for index in range(1, len(values)))
    return abs(values[-1] - values[0]) / travelled if travelled else 0.0


def _regression_r2(values: list[float]) -> Optional[float]:
    if len(values) < 3:
        return None
    n = len(values)
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    denominator = sum((index - x_mean) ** 2 for index in range(n))
    if denominator == 0:
        return None
    slope = sum((index - x_mean) * (value - y_mean)
                for index, value in enumerate(values)) / denominator
    fitted = [y_mean + slope * (index - x_mean) for index in range(n)]
    total = sum((value - y_mean) ** 2 for value in values)
    residual = sum((value - fit) ** 2 for value, fit in zip(values, fitted))
    return 1 - residual / total if total else 1.0


def _true_ranges(candles: list[dict]) -> list[float]:
    values = []
    previous = None
    for row in candles:
        high, low, close = (_number(row.get(key)) for key in ("high", "low", "close"))
        if high is None or low is None or close is None:
            continue
        values.append(max(high - low, abs(high - previous), abs(low - previous))
                      if previous is not None else high - low)
        previous = close
    return values


def assess_tradeability(candles: list[dict]) -> dict:
    rows = candles[-120:]
    closes = _closes(rows)
    if len(closes) < 50:
        return {"score": 0.0, "label": "Unavailable", "metrics": {}}

    efficiency_20 = _efficiency(closes[-20:])
    efficiency_50 = _efficiency(closes[-50:])
    r2_20 = _regression_r2(closes[-20:])
    r2_50 = _regression_r2(closes[-50:])

    wick_ratios, gap_flags = [], []
    previous_close = None
    for row in rows[-50:]:
        open_, high, low, close = (_number(row.get(key)) for key in ("open", "high", "low", "close"))
        if None not in (open_, high, low, close) and high > low:
            body_high, body_low = max(open_, close), min(open_, close)
            wick_ratios.append(((high - body_high) + (body_low - low)) / (high - low))
        if previous_close and open_:
            gap_flags.append(abs(open_ / previous_close - 1) >= 0.02)
        if close:
            previous_close = close

    ranges = _true_ranges(rows[-50:])
    range_cv = pstdev(ranges) / (sum(ranges) / len(ranges)) if len(ranges) >= 10 and sum(ranges) else None
    sharp_reversals = 0
    returns = [(closes[index] / closes[index - 1] - 1) for index in range(1, len(closes))]
    for index in range(1, len(returns)):
        if returns[index] * returns[index - 1] < 0 and abs(returns[index]) >= 0.02:
            sharp_reversals += 1
    reversal_frequency = sharp_reversals / max(1, len(returns) - 1)

    ma20, ma50 = [], []
    for index in range(49, len(closes)):
        ma20.append(sum(closes[index - 19:index + 1]) / 20)
        ma50.append(sum(closes[index - 49:index + 1]) / 50)
    whipsaws = sum(
        (ma20[index] - ma50[index]) * (ma20[index - 1] - ma50[index - 1]) < 0
        for index in range(1, len(ma20))
    )

    efficiency_score = _clamp(_average_non_null([efficiency_20, efficiency_50]) * 180)
    r2_score = _clamp(_average_non_null([r2_20, r2_50]) * 100)
    wick_score = _clamp(100 - (median(wick_ratios) if wick_ratios else 1) * 100)
    gap_score = _clamp(100 - (sum(gap_flags) / len(gap_flags) if gap_flags else 1) * 300)
    stability_score = _clamp(100 - (range_cv if range_cv is not None else 1) * 100)
    reversal_score = _clamp(100 - reversal_frequency * 400)
    whipsaw_score = _clamp(100 - whipsaws * 18)
    score = (efficiency_score * 0.22 + r2_score * 0.20 + wick_score * 0.14
             + gap_score * 0.12 + stability_score * 0.12
             + reversal_score * 0.10 + whipsaw_score * 0.10)
    label = "Very clean" if score >= 80 else "Clean" if score >= 65 \
        else "Moderate" if score >= 50 else "Erratic" if score >= 35 else "Very erratic"
    return {
        "score": round(score, 1), "label": label,
        "metrics": {
            "efficiency_20": _round(efficiency_20), "efficiency_50": _round(efficiency_50),
            "r2_20": _round(r2_20), "r2_50": _round(r2_50),
            "median_wick_ratio": _round(median(wick_ratios) if wick_ratios else None),
            "gap_frequency": _round(sum(gap_flags) / len(gap_flags) if gap_flags else None),
            "atr_stability_cv": _round(range_cv),
            "reversal_frequency": _round(reversal_frequency), "ma_whipsaws": whipsaws,
        },
    }


def _average_non_null(values: list[Optional[float]]) -> float:
    usable = [value for value in values if value is not None]
    return sum(usable) / len(usable) if usable else 0.0


def _round(value: Optional[float], digits: int = 3) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _realized_volatility(closes: list[float], sessions: int) -> Optional[float]:
    values = closes[-(sessions + 1):]
    if len(values) < sessions + 1:
        return None
    returns = [math.log(values[index] / values[index - 1]) for index in range(1, len(values))]
    return pstdev(returns) * math.sqrt(252) * 100


def _median_forward_move(closes: list[float], sessions: int) -> Optional[float]:
    if len(closes) <= sessions:
        return None
    moves = [(closes[index + sessions] / closes[index] - 1) * 100
             for index in range(len(closes) - sessions)]
    return median(moves) if moves else None


def _post_breakout_moves(candles: list[dict], sessions: int) -> list[float]:
    closes = _closes(candles)
    if len(closes) != len(candles):
        return []
    moves = []
    for index in range(20, len(candles) - sessions):
        prior_high = max(_number(row.get("high")) or closes[pos]
                         for pos, row in enumerate(candles[index - 20:index], start=index - 20))
        volume = _number(candles[index].get("volume"))
        prior_volumes = [_number(row.get("volume")) for row in candles[index - 20:index]]
        usable_volumes = [value for value in prior_volumes if value is not None]
        volume_ok = not usable_volumes or (volume is not None and volume >= median(usable_volumes) * 1.2)
        if closes[index] > prior_high and volume_ok:
            future_high = max(closes[index + 1:index + sessions + 1])
            moves.append((future_high / closes[index] - 1) * 100)
    return moves


def assess_move_potential(candles: list[dict], atr: Optional[float]) -> dict:
    closes = _closes(candles)
    if len(closes) < 60:
        return {"score": 0.0, "label": "Unavailable", "metrics": {}}
    current = closes[-1]
    atr_pct = (_number(atr) / current * 100) if _number(atr) and current else None
    ranges = []
    for row in candles[-20:]:
        high, low, close = (_number(row.get(key)) for key in ("high", "low", "close"))
        if high is not None and low is not None and close:
            ranges.append((high - low) / close * 100)
    average_range = sum(ranges) / len(ranges) if ranges else None
    weekly_ranges = []
    for end in range(5, min(len(candles), 65) + 1, 5):
        chunk = candles[-end:-end + 5] if end > 5 else candles[-5:]
        highs = [_number(row.get("high")) for row in chunk]
        lows = [_number(row.get("low")) for row in chunk]
        if chunk and all(value is not None for value in highs + lows) and lows[0]:
            weekly_ranges.append((max(highs) - min(lows)) / lows[0] * 100)

    breakout = {}
    for sessions in (5, 10, 20):
        values = _post_breakout_moves(candles[-252:], sessions)
        breakout[f"median_post_breakout_{sessions}d"] = median(values) if values else None
        breakout[f"breakout_samples_{sessions}d"] = len(values)

    velocity_5 = _median_forward_move(closes, 5)
    velocity_10 = _median_forward_move(closes, 10)
    velocity_20 = _median_forward_move(closes, 20)
    historical_upside = _average_non_null([
        breakout["median_post_breakout_5d"], breakout["median_post_breakout_10d"],
        breakout["median_post_breakout_20d"],
    ])
    score = _clamp(20 + (atr_pct or 0) * 10 + (average_range or 0) * 6
                   + historical_upside * 2)
    label = "Very high" if score >= 80 else "High" if score >= 65 \
        else "Medium" if score >= 45 else "Low"
    metrics = {
        "atr_pct": atr_pct, "average_daily_range_pct": average_range,
        "median_weekly_range_pct": median(weekly_ranges) if weekly_ranges else None,
        "realized_volatility_20d": _realized_volatility(closes, 20),
        "realized_volatility_60d": _realized_volatility(closes, 60),
        "median_5d_move": velocity_5, "median_10d_move": velocity_10,
        "median_20d_move": velocity_20, **breakout,
    }
    return {
        "score": round(score, 1), "label": label,
        "metrics": {key: _round(value, 2) if isinstance(value, float) else value
                    for key, value in metrics.items()},
    }
