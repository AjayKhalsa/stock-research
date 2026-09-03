"""Forward evaluator for every actionable, immutable model recommendation."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Optional

import db
import price_service as price
import trade_lifecycle

EVAL_CONCURRENCY = 6


def _evaluate_outcome(outcome: dict, candles: list[dict]):
    evaluation = trade_lifecycle.evaluate_daily(outcome, candles)
    if not evaluation:
        return None
    updates = dict(evaluation["updates"])
    updates["outcome"] = evaluation["status"] if evaluation["terminal"] else None
    updated = db.recommendation_outcome_patch(outcome["id"], **updates)
    return {
        "id": outcome["id"], "snapshot_id": outcome["snapshot_id"],
        "symbol": outcome["symbol"], "status": evaluation["status"],
        "pnl_r": evaluation["pnl_r"], "changed": evaluation["changed"],
        "outcome": updated,
    }


async def evaluate_open_outcomes(
    history_by_symbol: Optional[dict[str, list[dict]]] = None,
) -> dict:
    """Evaluate open rows, fetching each missing symbol only once."""
    open_outcomes = await asyncio.to_thread(db.recommendation_outcomes_open)
    if not open_outcomes:
        return {"evaluated": 0, "updated": 0, "provider_requests": 0, "results": []}

    grouped: dict[str, list[dict]] = defaultdict(list)
    for outcome in open_outcomes:
        grouped[outcome["symbol"]].append(outcome)
    supplied = history_by_symbol or {}
    semaphore = asyncio.Semaphore(EVAL_CONCURRENCY)

    async def evaluate_symbol(symbol: str, outcomes: list[dict]):
        async with semaphore:
            fetched = False
            try:
                candles = supplied.get(symbol) or supplied.get(f"NSE:{symbol}")
                if not candles:
                    fetched = True
                    candles = await price.get_historical(f"NSE:{symbol}", days=120)
                results = await asyncio.to_thread(
                    lambda: [_evaluate_outcome(outcome, candles) for outcome in outcomes]
                )
                return [result for result in results if result], fetched
            except Exception as exc:  # one symbol cannot abort snapshot publication
                error = f"{type(exc).__name__}: {exc}"
                return ([{
                    "id": outcome["id"], "snapshot_id": outcome["snapshot_id"],
                    "symbol": symbol, "status": outcome.get("status"), "error": error,
                } for outcome in outcomes], fetched)

    batches = await asyncio.gather(*(
        evaluate_symbol(symbol, outcomes) for symbol, outcomes in grouped.items()
    ))
    results = [result for batch, _fetched in batches for result in batch]
    return {
        "evaluated": len(open_outcomes),
        "updated": sum(1 for result in results if result.get("changed")),
        "provider_requests": sum(1 for _batch, fetched in batches if fetched),
        "results": results,
    }
