"""Daily evaluator for user-selected, point-in-time paper tests."""

from __future__ import annotations

import asyncio

import db
import price_service as price
import trade_lifecycle

EVAL_CONCURRENCY = 6
ARM_EXPIRY_SESSIONS = trade_lifecycle.ARM_EXPIRY_SESSIONS
ACTIVE_TIME_STOP_SESSIONS = trade_lifecycle.ACTIVE_TIME_STOP_SESSIONS


def _evaluate_trade(trade: dict, candles: list[dict]):
    latest_analysis = db.candidate_analysis(trade["symbol"])
    evaluation = trade_lifecycle.evaluate_daily(
        trade, candles,
        results_blocked=(trade.get("status") == "ARMED"
                         and (latest_analysis or {}).get("results_risk") == "blocked"),
    )
    if not evaluation:
        return None
    updated = db.paper_trade_patch(trade["id"], **evaluation["updates"])
    return {
        "id": trade["id"], "symbol": trade["symbol"],
        "status": evaluation["status"], "pnl_r": evaluation["pnl_r"],
        "changed": evaluation["changed"], "trade": updated,
    }


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
                        "status": trade.get("status"),
                        "error": f"{type(exc).__name__}: {exc}"}

    results = [result for result in await asyncio.gather(*(check(t) for t in open_tests))
               if result]
    updated = sum(1 for result in results if result.get("changed"))
    return {"evaluated": len(open_tests), "updated": updated, "results": results}
