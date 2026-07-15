"""
alert_store.py
JSON-file-backed price alerts (same no-DB pattern as watchlist.json).

An alert is a single price level with a fixed crossing direction:
    direction "above" triggers when ltp >= level
    direction "below" triggers when ltp <= level

Dedup is the status flip: a triggered alert never refires. Re-arming a plan's
alerts is done by re-creating them (create_from_plan replaces the existing
symbol+horizon set).

Alerts are checked opportunistically during the watchlist price poll — on
delayed Yahoo Finance data, while the app is open. They are advisory only.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
ALERTS_FILE = os.path.join(DATA_DIR, "alerts.json")


def load_alerts() -> list:
    if os.path.exists(ALERTS_FILE):
        try:
            return json.load(open(ALERTS_FILE))
        except Exception:
            pass
    return []


def save_alerts(alerts: list) -> None:
    json.dump(alerts, open(ALERTS_FILE, "w"), indent=2)


def _new_alert(symbol: str, exchange: str, kind: str, label: str,
               level: float, direction: str,
               horizon: Optional[str] = None) -> dict:
    return {
        "id": uuid.uuid4().hex[:8],
        "symbol": symbol.upper(),
        "exchange": exchange,
        "kind": kind,                # entry | stop | target | custom
        "label": label,
        "horizon": horizon,          # swing | positional | None
        "level": round(float(level), 2),
        "direction": direction,      # above | below
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "active",
        "triggered_at": None,
        "triggered_price": None,
        "acknowledged": False,
    }


def create_custom(symbol: str, exchange: str, level: float, direction: str,
                  label: str = "") -> dict:
    alerts = load_alerts()
    alert = _new_alert(symbol, exchange, "custom",
                       label or f"Custom level {round(float(level), 2)}",
                       level, direction)
    alerts.append(alert)
    save_alerts(alerts)
    return alert


def create_from_plan(symbol: str, exchange: str, horizon: str, plan: dict) -> list:
    """
    Arm entry / stop / target alerts from one horizon's trade plan.
    Replaces any existing alerts for the same (symbol, horizon).
    """
    symbol = symbol.upper()
    alerts = [a for a in load_alerts()
              if not (a["symbol"] == symbol and a.get("horizon") == horizon)]

    created = []
    entry = plan.get("entry") or {}
    stop  = plan.get("stop") or {}
    entry_type = entry.get("type", "")

    if entry.get("low") is not None and entry.get("high") is not None:
        if entry_type == "breakout":
            # Trigger when price pushes up into the breakout band
            created.append(_new_alert(symbol, exchange, "entry",
                                      f"{horizon.title()} breakout entry above {entry['low']}",
                                      entry["low"], "above", horizon))
        else:
            # Pullback/continuation: trigger when price dips into the band
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

    alerts.extend(created)
    save_alerts(alerts)
    return created


def delete_alert(alert_id: str) -> bool:
    alerts = load_alerts()
    kept = [a for a in alerts if a["id"] != alert_id]
    if len(kept) != len(alerts):
        save_alerts(kept)
        return True
    return False


def acknowledge(alert_id: str) -> bool:
    alerts = load_alerts()
    for a in alerts:
        if a["id"] == alert_id:
            a["acknowledged"] = True
            save_alerts(alerts)
            return True
    return False


def check_alerts(price_map: dict) -> list:
    """
    price_map: {"NSE:RELIANCE": 1502.3, ...}
    Flips crossed active alerts to triggered, persists, and returns ONLY
    the newly-triggered alerts.
    """
    alerts = load_alerts()
    newly = []
    for a in alerts:
        if a["status"] != "active":
            continue
        ltp = price_map.get(f"{a['exchange']}:{a['symbol']}")
        if ltp is None:
            continue
        crossed = (ltp >= a["level"]) if a["direction"] == "above" else (ltp <= a["level"])
        if crossed:
            a["status"] = "triggered"
            a["triggered_at"] = datetime.now().isoformat(timespec="seconds")
            a["triggered_price"] = round(float(ltp), 2)
            newly.append(a)
    if newly:
        save_alerts(alerts)
    return newly


def summary_by_symbol() -> dict:
    """{"RELIANCE": {"active": 3, "triggered_unacked": 1}, ...}"""
    out: dict = {}
    for a in load_alerts():
        s = out.setdefault(a["symbol"], {"active": 0, "triggered_unacked": 0})
        if a["status"] == "active":
            s["active"] += 1
        elif a["status"] == "triggered" and not a.get("acknowledged"):
            s["triggered_unacked"] += 1
    return out


def symbols_with_active_alerts() -> list:
    """[(symbol, exchange), ...] unique pairs having at least one active alert."""
    seen, out = set(), []
    for a in load_alerts():
        if a["status"] == "active":
            key = (a["symbol"], a["exchange"])
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out
