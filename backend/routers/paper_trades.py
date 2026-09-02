"""
Route: point-in-time paper tests with armed-entry and active-trade states.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db
import paper_test_service

router = APIRouter()

class PaperTradeCreate(BaseModel):
    symbol: str
    entry_price: float
    stop_loss: float
    target_t1: float
    target_t2: Optional[float] = None
    score: Optional[float] = None
    setup_type: Optional[str] = None
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    signal_date: Optional[str] = None
    snapshot_id: Optional[str] = None
    model_version: Optional[str] = None
    action_at_add: Optional[str] = None
    invalidation: Optional[str] = None
    note: Optional[str] = None


@router.post("/api/paper-trades")
def create_paper_trade(body: PaperTradeCreate):
    """Arm a planned entry, or preserve ACTIVE behavior for legacy callers."""
    symbol = body.symbol.upper().strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    if body.entry_price <= 0 or body.stop_loss <= 0 or body.target_t1 <= 0:
        raise HTTPException(status_code=400, detail="Prices must be positive")
    entry_low = body.entry_low if body.entry_low is not None else body.entry_price
    entry_high = body.entry_high if body.entry_high is not None else body.entry_price
    if entry_low > entry_high:
        entry_low, entry_high = entry_high, entry_low
    if body.stop_loss >= entry_low:
        raise HTTPException(status_code=400, detail="Stop must be below the entry zone")
    if body.target_t1 <= entry_high:
        raise HTTPException(status_code=400, detail="Target must be above the entry zone")
    if body.target_t2 is not None and body.target_t2 < body.target_t1:
        raise HTTPException(status_code=400, detail="Target 2 must not be below target 1")
    if db.paper_trade_open_for_symbol(symbol):
        raise HTTPException(status_code=409, detail="An open paper test already exists for this symbol")
    armed = body.entry_low is not None or body.entry_high is not None
    trade = db.paper_trade_insert(
        symbol=symbol,
        entry_price=body.entry_price,
        stop_loss=body.stop_loss,
        target_t1=body.target_t1,
        target_t2=body.target_t2 if body.target_t2 is not None else body.target_t1,
        score=body.score,
        setup_type=body.setup_type,
        status="ARMED" if armed else "ACTIVE",
        entry_low=entry_low, entry_high=entry_high,
        signal_date=body.signal_date, snapshot_id=body.snapshot_id,
        model_version=body.model_version, action_at_add=body.action_at_add,
        invalidation=body.invalidation, note=(body.note or "")[:1000],
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
    return await paper_test_service.evaluate_open_tests()
