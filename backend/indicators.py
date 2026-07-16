"""
indicators.py
Single source of truth for technical-indicator math. Every engine
(swing_engine, conviction_engine, decision_engine via swing, main routes)
imports from here — no more per-file reimplementations drifting apart.

Conventions:
  - *_series functions return a list aligned 1:1 with the input
    (None until the indicator has enough warm-up data).
  - Scalar helpers (rsi, atr, sma, macd_hist) return the latest value
    or None when there isn't enough history.
  - RSI and ATR use Wilder smoothing; EMA is seeded with the SMA of the
    first `period` values; MACD is 12/26 EMA with a 9-EMA signal line.
"""

from __future__ import annotations

from typing import Optional

# ── Simple moving average ─────────────────────────────────────────────────────

def sma(values: list, period: int) -> Optional[float]:
    """Latest simple moving average, or None if not enough data."""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def sma_series(values: list, period: int) -> list:
    """SMA aligned to input; None before warm-up. O(n) via running sum."""
    out = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period:
            s -= values[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


# ── Exponential moving average ────────────────────────────────────────────────

def ema_series(values: list, period: int) -> list:
    """EMA aligned to input (seeded with the SMA of the first `period`)."""
    n = len(values)
    out = [None] * n
    if n < period:
        return out
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    out[period - 1] = ema
    for i in range(period, n):
        ema = values[i] * k + ema * (1 - k)
        out[i] = ema
    return out


# ── RSI (Wilder) ──────────────────────────────────────────────────────────────

def rsi(closes: list, period: int = 14) -> Optional[float]:
    """Latest Wilder-smoothed RSI, rounded to 2dp (matches legacy engines)."""
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 2)


def rsi_series(closes: list, period: int = 14) -> list:
    """Wilder RSI aligned to input (unrounded floats for downstream math)."""
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


# ── ATR (Wilder) ──────────────────────────────────────────────────────────────

def _true_ranges(highs: list, lows: list, closes: list) -> list:
    return [max(highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]))
            for i in range(1, len(closes))]


def atr(highs: list, lows: list, closes: list, period: int = 14) -> Optional[float]:
    """Latest Wilder-smoothed Average True Range."""
    if len(closes) < period + 1:
        return None
    trs = _true_ranges(highs, lows, closes)
    val = sum(trs[:period]) / period
    for tr in trs[period:]:
        val = (val * (period - 1) + tr) / period
    return val


def atr_series(highs: list, lows: list, closes: list, period: int = 14) -> list:
    """Wilder ATR aligned to input; None before warm-up."""
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    trs = _true_ranges(highs, lows, closes)
    val = sum(trs[:period]) / period
    out[period] = val
    for i in range(period, len(trs)):
        val = (val * (period - 1) + trs[i]) / period
        out[i + 1] = val
    return out


# ── MACD histogram (12/26/9) ──────────────────────────────────────────────────

def macd_hist_series(closes: list) -> list:
    """MACD histogram (MACD line − signal line) aligned to input."""
    n = len(closes)
    e12, e26 = ema_series(closes, 12), ema_series(closes, 26)
    macd = [None if (e12[i] is None or e26[i] is None) else e12[i] - e26[i]
            for i in range(n)]
    first = next((i for i, v in enumerate(macd) if v is not None), None)
    out = [None] * n
    if first is None or n - first < 9:
        return out
    sig = ema_series(macd[first:], 9)
    for j, s in enumerate(sig):
        if s is not None:
            out[first + j] = macd[first + j] - s
    return out


def macd_hist(closes: list) -> Optional[float]:
    """Latest MACD histogram value."""
    series = macd_hist_series(closes)
    return series[-1] if series else None
