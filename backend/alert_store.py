"""
alert_store.py — price alerts, SQLite-backed (see db.py).

An alert is a single price level with a fixed crossing direction:
    direction "above" triggers when ltp >= level
    direction "below" triggers when ltp <= level

Dedup is the status flip: a triggered alert never refires. Re-arming a plan's
alerts replaces the existing (symbol, horizon) set. Alerts are checked during
the watchlist pulse on delayed Yahoo Finance data — advisory only.

The public API is unchanged from the JSON-file era; only persistence moved.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import db


def load_alerts() -> list:
    return db.alerts_all()


def _new_alert(symbol: str, exchange: str, kind: str, label: str,
               level: float, direction: str,
               horizon: Optional[str] = None) -> dict:
    return {
        "id": uuid.uuid4().hex[:8],
        "symbol": symbol.upper(),
        "exchange": exchange,
        "kind": kind,
        "label": label,
        "horizon": horizon,
        "level": round(float(level), 2),
        "direction": direction,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "active",
        "triggered_at": None,
        "triggered_price": None,
        "acknowledged": False,
    }


def create_custom(symbol: str, exchange: str, level: float, direction: str,
                  label: str = "") -> dict:
    alert = _new_alert(symbol, exchange, "custom",
                       label or f"Custom level {round(float(level), 2)}",
                       level, direction)
    db.alerts_insert(alert)
    return alert


def create_from_plan(symbol: str, exchange: str, horizon: str, plan: dict) -> list:
    """
    Arm entry / stop / target alerts from one horizon's trade plan.
    Replaces any existing alerts for the same (symbol, horizon).
    """
    symbol = symbol.upper()
    db.alerts_delete_plan_set(symbol, horizon)

    created = []
    entry = plan.get("entry") or {}
    stop = plan.get("stop") or {}
    entry_type = entry.get("type", "")

    if entry.get("low") is not None and entry.get("high") is not None:
        if entry_type == "breakout":
            created.append(_new_alert(symbol, exchange, "entry",
                                      f"{horizon.title()} breakout entry above {entry['low']}",
                                      entry["low"], "above", horizon))
        else:
            created.append(_new_alert(symbol, exchange, "entry",
                                      f"{horizon.title()} entry zone {entry['low']}–{entry['high']}",
                                      entry["high"], "below", horizon))

    if stop.get("price") is not None:
        created.append(_new_alert(symbol, exchange, "stop",
                                  f"{horizon.title()} stop loss broken",
                                  stop["price"], "below", horizon))

    for t in plan.get("targets", []):
        if t.get("price") is not None:
            created.append(_new_alert(symbol, exchange, "target",
                                      f"{horizon.title()} target {t.get('label', 'T?')} hit",
                                      t["price"], "above", horizon))

    for a in created:
        db.alerts_insert(a)
    return created


def delete_alert(alert_id: str) -> bool:
    return db.alerts_delete(alert_id)


def acknowledge(alert_id: str) -> bool:
    return db.alerts_acknowledge(alert_id)


def check_alerts(price_map: dict) -> list:
    """
    price_map: {"NSE:RELIANCE": 1502.3, ...}
    Flips crossed active alerts to triggered and returns ONLY the newly
    triggered ones.
    """
    newly = []
    now = datetime.now().isoformat(timespec="seconds")
    for a in db.alerts_all():
        if a["status"] != "active":
            continue
        ltp = price_map.get(f"{a['exchange']}:{a['symbol']}")
        if ltp is None:
            continue
        crossed = (ltp >= a["level"]) if a["direction"] == "above" else (ltp <= a["level"])
        if crossed:
            db.alerts_mark_triggered(a["id"], now, round(float(ltp), 2))
            a.update(status="triggered", triggered_at=now,
                     triggered_price=round(float(ltp), 2))
            newly.append(a)
    return newly


def summary_by_symbol() -> dict:
    out: dict = {}
    for a in db.alerts_all():
        s = out.setdefault(a["symbol"], {"active": 0, "triggered_unacked": 0})
        if a["status"] == "active":
            s["active"] += 1
        elif a["status"] == "triggered" and not a.get("acknowledged"):
            s["triggered_unacked"] += 1
    return out


def symbols_with_active_alerts() -> list:
    seen, out = set(), []
    for a in db.alerts_all():
        if a["status"] == "active":
            key = (a["symbol"], a["exchange"])
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out
