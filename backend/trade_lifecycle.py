"""Pure, conservative daily-bar lifecycle shared by forward outcome ledgers."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

ARM_EXPIRY_SESSIONS = 10
ACTIVE_TIME_STOP_SESSIONS = 40


def _number(value, fallback: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _signal_date(record: dict) -> str:
    value = (record.get("signal_date") or record.get("entry_date")
             or record.get("opened_at") or record.get("created_at") or "")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).date().isoformat()
    return str(value)[:10]


def _terminal(status: str, pnl_r: float, date: str, now: float, **updates) -> dict:
    updates.update({
        "status": status, "pnl_r": round(float(pnl_r), 2),
        "closed_at": now, "last_evaluated_date": date,
        "outcome_date": date,
    })
    if "mfe_r" in updates:
        updates["mfe_r"] = round(float(updates["mfe_r"]), 2)
    if "mae_r" in updates:
        updates["mae_r"] = round(float(updates["mae_r"]), 2)
    return {"status": status, "pnl_r": round(float(pnl_r), 2),
            "terminal": True, "changed": True, "updates": updates}


def evaluate_daily(record: dict, candles: list[dict], *,
                   results_blocked: bool = False,
                   now: Optional[float] = None) -> Optional[dict]:
    """Advance one planned trade using only candles strictly after its cursor.

    Daily bars cannot reveal intraday ordering. An entry-bar stop/target clash
    is excluded; after activation, a stop wins any same-bar stop/target clash.
    """
    evaluated_at = float(now if now is not None else time.time())
    last_date = str(record.get("last_evaluated_date") or _signal_date(record))[:10]
    future = [c for c in candles if str(c.get("date") or "") > last_date]
    if not future:
        return None

    original_status = record.get("status") or "ACTIVE"
    status = original_status
    armed_sessions = int(record.get("armed_sessions") or 0)
    active_sessions = int(record.get("active_sessions") or 0)
    entry_low = _number(record.get("entry_low"), _number(record.get("entry_price")))
    entry_high = _number(record.get("entry_high"), _number(record.get("entry_price")))
    entry = _number(record.get("entry_price"), entry_high)
    stop = _number(record.get("stop_loss"), _number(record.get("stop_price")))
    t1 = _number(record.get("target_t1"))
    t2 = _number(record.get("target_t2"), t1)
    mfe_r = max(0.0, _number(record.get("mfe_r"), 0.0) or 0.0)
    mae_r = max(0.0, _number(record.get("mae_r"), 0.0) or 0.0)
    activated_at = record.get("activated_at")

    if None in (entry_low, entry_high, entry, stop, t1, t2):
        return _terminal("INVALIDATED", 0, str(future[-1].get("date") or ""),
                         evaluated_at)
    if status == "ARMED" and results_blocked:
        return _terminal("INVALIDATED", 0, str(future[-1].get("date") or ""),
                         evaluated_at, armed_sessions=armed_sessions)

    for candle in future:
        date = str(candle.get("date") or "")
        high = _number(candle.get("high"))
        low = _number(candle.get("low"))
        close = _number(candle.get("close"))
        if None in (high, low, close):
            continue

        if status == "ARMED":
            armed_sessions += 1
            touched = high >= entry_low and low <= entry_high
            if touched:
                if low <= stop or high >= t1:
                    return _terminal(
                        "AMBIGUOUS", 0, date, evaluated_at,
                        armed_sessions=armed_sessions, entry_price=entry_high,
                        activated_at=evaluated_at, mfe_r=mfe_r, mae_r=mae_r,
                    )
                status = "ACTIVE"
                entry = entry_high
                active_sessions = 0
                activated_at = evaluated_at
                continue
            if low <= stop:
                return _terminal("INVALIDATED", 0, date, evaluated_at,
                                 armed_sessions=armed_sessions)
            if armed_sessions >= ARM_EXPIRY_SESSIONS:
                return _terminal("EXPIRED", 0, date, evaluated_at,
                                 armed_sessions=armed_sessions)

        elif status == "ACTIVE":
            active_sessions += 1
            risk = max(entry - stop, 0.0001)
            if low <= stop:
                return _terminal(
                    "STOPPED_OUT", -1, date, evaluated_at,
                    active_sessions=active_sessions, exit_price=stop,
                    mfe_r=mfe_r, mae_r=max(mae_r, 1.0),
                )
            mfe_r = max(mfe_r, (high - entry) / risk, 0.0)
            mae_r = max(mae_r, (entry - low) / risk, 0.0)
            if high >= t2:
                return _terminal(
                    "WIN_T2", (t2 - entry) / risk, date, evaluated_at,
                    active_sessions=active_sessions, exit_price=t2,
                    mfe_r=mfe_r, mae_r=mae_r,
                )
            if high >= t1:
                return _terminal(
                    "WIN_T1", (t1 - entry) / risk, date, evaluated_at,
                    active_sessions=active_sessions, exit_price=t1,
                    mfe_r=mfe_r, mae_r=mae_r,
                )
            if active_sessions >= ACTIVE_TIME_STOP_SESSIONS:
                return _terminal(
                    "TIME_STOP", (close - entry) / risk, date, evaluated_at,
                    active_sessions=active_sessions, exit_price=close,
                    mfe_r=mfe_r, mae_r=mae_r,
                )

    updates = {
        "status": status, "armed_sessions": armed_sessions,
        "active_sessions": active_sessions,
        "last_evaluated_date": str(future[-1].get("date") or ""),
        "mfe_r": round(mfe_r, 2), "mae_r": round(mae_r, 2),
    }
    if status == "ACTIVE" and original_status == "ARMED":
        updates.update({"entry_price": entry_high, "activated_at": activated_at})
    return {"status": status, "pnl_r": round(float(record.get("pnl_r") or 0), 2),
            "terminal": False, "changed": True, "updates": updates}
