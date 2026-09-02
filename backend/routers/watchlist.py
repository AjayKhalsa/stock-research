"""Routes: watchlist CRUD, live prices, alerts, and the 30s pulse."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import alert_store
import db
import price_service as price

router = APIRouter()


class WatchlistUpdate(BaseModel):
    note: Optional[str] = None
    name: Optional[str] = None


@router.get("/api/watchlist")
def get_watchlist():
    return db.watchlist_all()


@router.post("/api/watchlist")
def add_watchlist(item: dict):
    sym = item.get("symbol", "").upper()
    if not sym:
        return db.watchlist_all()
    latest = db.latest_analysis_snapshot() or {}
    return db.watchlist_add(
        sym, item.get("exchange", "NSE"), item.get("name", sym),
        note=str(item.get("note") or "")[:1000],
        added_snapshot_id=item.get("snapshot_id") or latest.get("snapshot_id"),
    )


@router.patch("/api/watchlist/{symbol}")
def update_watchlist(symbol: str, body: WatchlistUpdate):
    updated = db.watchlist_update(
        symbol,
        note=body.note[:1000] if body.note is not None else None,
        name=body.name[:200] if body.name is not None else None,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Stock is not in the watchlist")
    return updated


@router.delete("/api/watchlist/{symbol}")
def remove_watchlist(symbol: str):
    return db.watchlist_remove(symbol)


@router.get("/api/watchlist/prices")
async def watchlist_prices():
    wl = await run_in_threadpool(db.watchlist_all)
    if not wl:
        return {}
    instruments = [f"{w['exchange']}:{w['symbol']}" for w in wl]
    return await price.get_ltp_multiple(instruments)


@router.get("/api/watchlist/snapshot")
async def watchlist_snapshot():
    """One fast, decision-oriented view of the user's single watchlist."""
    items = await run_in_threadpool(db.watchlist_all)
    if not items:
        return {"items": [], "count": 0, "snapshot_id": None}
    latest = await run_in_threadpool(db.latest_analysis_snapshot)
    snapshot_id = (latest or {}).get("snapshot_id")
    instruments = [f"{item['exchange']}:{item['symbol']}" for item in items]
    try:
        prices = await price.get_ltp_multiple(instruments)
    except Exception:  # cached analysis remains useful during quote failure
        prices = {}
    enriched = []
    for item in items:
        analysis = await run_in_threadpool(db.candidate_analysis, item["symbol"], snapshot_id)
        plan = (analysis or {}).get("trade_plan") or {}
        quote = prices.get(f"{item['exchange']}:{item['symbol']}") or prices.get(item["symbol"]) or {}
        if not isinstance(quote, dict):
            quote = {"ltp": quote}
        enriched.append({
            **item,
            "price": quote.get("ltp") or quote.get("price") or (analysis or {}).get("price"),
            "action": (analysis or {}).get("action") or "NOT_RANKED",
            "action_reason": (analysis or {}).get("action_reason"),
            "sector": (analysis or {}).get("sector"),
            "global_rank": (analysis or {}).get("global_rank"),
            "sector_rank": (analysis or {}).get("sector_rank"),
            "score": (analysis or {}).get("score"),
            "confidence": (analysis or {}).get("confidence"),
            "entry_distance_pct": (analysis or {}).get("entry_distance_pct"),
            "results_risk": (analysis or {}).get("results_risk") or "unknown",
            "entry": plan.get("entry"),
            "freshness": (latest or {}).get("trading_date"),
            "ranked": bool(analysis),
        })
    return {"items": enriched, "count": len(enriched), "snapshot_id": snapshot_id,
            "trading_date": (latest or {}).get("trading_date")}


# ── alerts ────────────────────────────────────────────────────────────────────

@router.get("/api/alerts")
def get_alerts(symbol: Optional[str] = None):
    alerts = alert_store.load_alerts()
    if symbol:
        alerts = [a for a in alerts if a["symbol"] == symbol.upper()]
    return alerts


@router.post("/api/alerts")
def create_alert(item: dict):
    sym = item.get("symbol", "").upper().strip()
    level = item.get("level")
    direction = item.get("direction")
    if not sym or level is None or direction not in ("above", "below"):
        raise HTTPException(status_code=400,
                            detail="symbol, level and direction ('above'|'below') required")
    return alert_store.create_custom(
        sym, item.get("exchange", "NSE"), level, direction, item.get("label", "")
    )


@router.post("/api/alerts/from-plan")
def create_alerts_from_plan(item: dict):
    sym = item.get("symbol", "").upper().strip()
    horizon = item.get("horizon")
    plan = item.get("plan")
    if not sym or horizon not in ("swing", "positional") or not isinstance(plan, dict):
        raise HTTPException(status_code=400,
                            detail="symbol, horizon ('swing'|'positional') and plan required")
    return alert_store.create_from_plan(sym, item.get("exchange", "NSE"), horizon, plan)


@router.delete("/api/alerts/{alert_id}")
def remove_alert(alert_id: str):
    if not alert_store.delete_alert(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}


@router.post("/api/alerts/{alert_id}/ack")
def ack_alert(alert_id: str):
    if not alert_store.acknowledge(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}


@router.get("/api/watchlist/pulse")
async def watchlist_pulse():
    """
    Watchlist prices + alert check in one call (polled by the sidebar every
    30s). Fetches LTPs for watchlist symbols plus any symbol with an active
    alert, flips crossed alerts, and returns the newly-triggered ones.
    Alerts run on delayed Yahoo Finance data — advisory only.
    """
    wl = await run_in_threadpool(db.watchlist_all)
    instruments = {f"{w['exchange']}:{w['symbol']}" for w in wl}
    active_alerts = await run_in_threadpool(alert_store.symbols_with_active_alerts)
    instruments |= {f"{exc}:{sym}" for sym, exc in active_alerts}

    prices = await price.get_ltp_multiple(sorted(instruments)) if instruments else {}
    newly_triggered = await run_in_threadpool(alert_store.check_alerts, prices)
    alerts_by_symbol = await run_in_threadpool(alert_store.summary_by_symbol)

    return {
        "prices": prices,
        "newly_triggered": newly_triggered,
        "alerts_by_symbol": alerts_by_symbol,
    }
