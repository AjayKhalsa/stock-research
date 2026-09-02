"""Deterministic, daily-only lifecycle for user-selected paper tests."""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import db
import price_service as price

EVAL_CONCURRENCY = 6
ARM_EXPIRY_SESSIONS = 10
ACTIVE_TIME_STOP_SESSIONS = 40


def _number(value, fallback: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _result(trade: dict, status: str, pnl_r: float, date: str, **extra) -> dict:
    if "mfe_r" in extra:
        extra["mfe_r"] = round(float(extra["mfe_r"]), 2)
    if "mae_r" in extra:
        extra["mae_r"] = round(float(extra["mae_r"]), 2)
    updated = db.paper_trade_patch(
        trade["id"], status=status, pnl_r=round(float(pnl_r), 2),
        closed_at=time.time(), last_evaluated_date=date, outcome_date=date, **extra,
    )
    return {"id": trade["id"], "symbol": trade["symbol"], "status": status,
            "pnl_r": round(float(pnl_r), 2), "trade": updated}


def _signal_date(trade: dict) -> str:
    value = trade.get("signal_date") or trade.get("entry_date") or trade.get("created_at") or ""
    return str(value)[:10]


def _evaluate_trade(trade: dict, candles: list[dict]) -> Optional[dict]:
    last_date = str(trade.get("last_evaluated_date") or _signal_date(trade))[:10]
    future = [c for c in candles if str(c.get("date") or "") > last_date]
    if not future:
        return None

    status = trade.get("status") or "ACTIVE"
    armed_sessions = int(trade.get("armed_sessions") or 0)
    active_sessions = int(trade.get("active_sessions") or 0)
    entry_low = _number(trade.get("entry_low"), _number(trade.get("entry_price")))
    entry_high = _number(trade.get("entry_high"), _number(trade.get("entry_price")))
    entry = _number(trade.get("entry_price"), entry_high)
    stop = _number(trade.get("stop_loss"))
    t1 = _number(trade.get("target_t1"))
    t2 = _number(trade.get("target_t2"), t1)
    mfe_r = max(0.0, _number(trade.get("mfe_r"), 0.0) or 0.0)
    mae_r = max(0.0, _number(trade.get("mae_r"), 0.0) or 0.0)
    if None in (entry_low, entry_high, entry, stop, t1, t2):
        return _result(trade, "INVALIDATED", 0, future[-1]["date"])

    latest_analysis = db.candidate_analysis(trade["symbol"])
    if status == "ARMED" and (latest_analysis or {}).get("results_risk") == "blocked":
        return _result(trade, "INVALIDATED", 0, future[-1]["date"],
                       armed_sessions=armed_sessions)

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
                # Daily bars cannot tell whether entry, stop, or target occurred
                # first. Excluding that bar is more honest than inventing a path.
                if low <= stop or high >= t1:
                    return _result(trade, "AMBIGUOUS", 0, date,
                                   armed_sessions=armed_sessions,
                                   entry_price=entry_high, activated_at=time.time())
                status = "ACTIVE"
                entry = entry_high
                active_sessions = 0
                db.paper_trade_patch(
                    trade["id"], status="ACTIVE", entry_price=entry,
                    armed_sessions=armed_sessions, active_sessions=0,
                    activated_at=time.time(), last_evaluated_date=date,
                    mfe_r=mfe_r, mae_r=mae_r,
                )
                continue
            if low <= stop:
                return _result(trade, "INVALIDATED", 0, date,
                               armed_sessions=armed_sessions)
            if armed_sessions >= ARM_EXPIRY_SESSIONS:
                return _result(trade, "EXPIRED", 0, date,
                               armed_sessions=armed_sessions)

        elif status == "ACTIVE":
            active_sessions += 1
            risk = max(entry - stop, 0.0001)
            if low <= stop:  # conservative when stop and target share a later bar
                return _result(trade, "STOPPED_OUT", -1, date,
                               active_sessions=active_sessions, exit_price=stop,
                               mfe_r=mfe_r, mae_r=max(mae_r, 1.0))
            mfe_r = max(mfe_r, (high - entry) / risk, 0.0)
            mae_r = max(mae_r, (entry - low) / risk, 0.0)
            if high >= t2:
                return _result(trade, "WIN_T2", (t2 - entry) / risk, date,
                               active_sessions=active_sessions, exit_price=t2,
                               mfe_r=mfe_r, mae_r=mae_r)
            if high >= t1:
                return _result(trade, "WIN_T1", (t1 - entry) / risk, date,
                               active_sessions=active_sessions, exit_price=t1,
                               mfe_r=mfe_r, mae_r=mae_r)
            if active_sessions >= ACTIVE_TIME_STOP_SESSIONS:
                return _result(trade, "TIME_STOP", (close - entry) / risk, date,
                               active_sessions=active_sessions, exit_price=close,
                               mfe_r=mfe_r, mae_r=mae_r)

    db.paper_trade_patch(
        trade["id"], status=status, armed_sessions=armed_sessions,
        active_sessions=active_sessions, last_evaluated_date=future[-1]["date"],
        mfe_r=round(mfe_r, 2), mae_r=round(mae_r, 2),
    )
    return {"id": trade["id"], "symbol": trade["symbol"], "status": status,
            "pnl_r": trade.get("pnl_r") or 0, "changed": status != trade.get("status")}


async def evaluate_open_tests() -> dict:
    open_tests = await asyncio.to_thread(db.paper_trades_open)
    if not open_tests:
        return {"evaluated": 0, "updated": 0, "results": []}
    semaphore = asyncio.Semaphore(EVAL_CONCURRENCY)

    async def check(trade: dict):
        async with semaphore:
            try:
                candles = await price.get_historical(f"NSE:{trade['symbol']}", days=120)
                return await asyncio.to_thread(_evaluate_trade, trade, candles)
            except Exception as exc:  # one provider failure cannot block the daily snapshot
                return {"id": trade["id"], "symbol": trade["symbol"],
                        "status": trade.get("status"), "error": f"{type(exc).__name__}: {exc}"}

    results = [result for result in await asyncio.gather(*(check(t) for t in open_tests)) if result]
    updated = sum(1 for result in results if result.get("changed") or
                  result.get("status") not in {"ARMED", "ACTIVE"})
    return {"evaluated": len(open_tests), "updated": updated, "results": results}
