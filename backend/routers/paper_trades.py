"""
Route: paper-trading (forward-test) log — one log entry per trade sized by
the Trade Plan's Position Sizer, plus the on-demand evaluator that marks
trades WIN/STOPPED_OUT against live daily price data.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import db
import price_service as price

router = APIRouter()

# Bounded concurrency for the evaluator's per-symbol Yahoo Finance lookups —
# same rationale as the screener's FETCH_CONCURRENCY (be polite, avoid bursts).
EVAL_CONCURRENCY = 6

# R-multiples booked on a target hit — mirrors decision_engine's own swing
# targets (T1 = 1.5R, T2 = 2.5R), so a paper trade's expectancy is measured on
# the same R scale the trade plan itself was built on. A stop-out books -1R
# by definition (that's what "R" is normalized to).
PNL_R_TARGET_T1 = 1.5
PNL_R_TARGET_T2 = 2.5
PNL_R_STOPPED_OUT = -1.0


class PaperTradeCreate(BaseModel):
    symbol: str
    entry_price: float
    stop_loss: float
    target_t1: float
    target_t2: Optional[float] = None
    score: Optional[float] = None
    setup_type: Optional[str] = None


@router.post("/api/paper-trades")
def create_paper_trade(body: PaperTradeCreate):
    """Log a new forward-test trade. target_t2 falls back to target_t1 when
    a plan only has one target, since the column is NOT NULL."""
    if body.entry_price <= 0 or body.stop_loss <= 0 or body.target_t1 <= 0:
        raise HTTPException(status_code=400, detail="Prices must be positive")
    trade = db.paper_trade_insert(
        symbol=body.symbol,
        entry_price=body.entry_price,
        stop_loss=body.stop_loss,
        target_t1=body.target_t1,
        target_t2=body.target_t2 if body.target_t2 is not None else body.target_t1,
        score=body.score,
        setup_type=body.setup_type,
    )
    return trade


@router.get("/api/paper-trades/stats")
def paper_trade_stats():
    return db.paper_trades_stats()


@router.get("/api/paper-trades/list")
def list_paper_trades():
    return db.paper_trades_all()


@router.get("/api/paper-trades/snapshot")
def paper_trade_snapshot(limit: int = 100):
    """Fast sidebar bootstrap: aggregate stats and recent trades together."""
    return db.paper_trades_snapshot(limit=limit)


@router.post("/api/paper-trades/evaluate")
async def evaluate_paper_trades():
    """
    Compare every ACTIVE paper trade against today's Yahoo Finance daily
    High/Low. Same-bar ambiguity (both stop and target crossed on one day) is
    resolved conservatively in favour of the stop, matching the convention
    conviction_engine's own base-rate backtester uses. Skips (leaves ACTIVE)
    any symbol whose quote can't be fetched right now.
    """
    active = await run_in_threadpool(db.paper_trades_active)
    if not active:
        return {"evaluated": 0, "updated": 0, "results": []}

    sem = asyncio.Semaphore(EVAL_CONCURRENCY)

    async def _check(trade: dict):
        async with sem:
            try:
                ohlc = await price.get_ohlc(f"NSE:{trade['symbol']}")
            except Exception:                                 # noqa: BLE001
                ohlc = {}
            high, low = ohlc.get("high"), ohlc.get("low")
            if high is None or low is None:
                return None

            if low <= trade["stop_loss"]:
                status, pnl_r = "STOPPED_OUT", PNL_R_STOPPED_OUT
            elif high >= trade["target_t2"]:
                status, pnl_r = "WIN_T2", PNL_R_TARGET_T2
            elif high >= trade["target_t1"]:
                status, pnl_r = "WIN_T1", PNL_R_TARGET_T1
            else:
                return None   # still active, nothing to update

            await run_in_threadpool(db.paper_trade_update_status, trade["id"], status, pnl_r)
            return {"id": trade["id"], "symbol": trade["symbol"],
                    "status": status, "pnl_r": pnl_r}

    results = await asyncio.gather(*(_check(t) for t in active))
    updates = [r for r in results if r is not None]
    return {"evaluated": len(active), "updated": len(updates), "results": updates}
