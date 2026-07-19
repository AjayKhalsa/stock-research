"""Routes: watchlist CRUD, live prices, alerts, and the 30s pulse."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

import alert_store
import db
import price_service as price

router = APIRouter()


@router.get("/api/watchlist")
async def get_watchlist():
    return db.watchlist_all()


@router.post("/api/watchlist")
async def add_watchlist(item: dict):
    sym = item.get("symbol", "").upper()
    if not sym:
        return db.watchlist_all()
    return db.watchlist_add(sym, item.get("exchange", "NSE"), item.get("name", sym))


@router.delete("/api/watchlist/{symbol}")
async def remove_watchlist(symbol: str):
    return db.watchlist_remove(symbol)


@router.get("/api/watchlist/prices")
async def watchlist_prices():
    wl = db.watchlist_all()
    if not wl:
        return {}
    instruments = [f"{w['exchange']}:{w['symbol']}" for w in wl]
    return await price.get_ltp_multiple(instruments)


# ── alerts ────────────────────────────────────────────────────────────────────

@router.get("/api/alerts")
async def get_alerts(symbol: Optional[str] = None):
    alerts = alert_store.load_alerts()
    if symbol:
        alerts = [a for a in alerts if a["symbol"] == symbol.upper()]
    return alerts


@router.post("/api/alerts")
async def create_alert(item: dict):
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
async def create_alerts_from_plan(item: dict):
    sym = item.get("symbol", "").upper().strip()
    horizon = item.get("horizon")
    plan = item.get("plan")
    if not sym or horizon not in ("swing", "positional") or not isinstance(plan, dict):
        raise HTTPException(status_code=400,
                            detail="symbol, horizon ('swing'|'positional') and plan required")
    return alert_store.create_from_plan(sym, item.get("exchange", "NSE"), horizon, plan)


@router.delete("/api/alerts/{alert_id}")
async def remove_alert(alert_id: str):
    if not alert_store.delete_alert(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}


@router.post("/api/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str):
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
    wl = db.watchlist_all()
    instruments = {f"{w['exchange']}:{w['symbol']}" for w in wl}
    instruments |= {f"{exc}:{sym}" for sym, exc in alert_store.symbols_with_active_alerts()}

    prices = await price.get_ltp_multiple(sorted(instruments)) if instruments else {}
    newly_triggered = alert_store.check_alerts(prices)

    return {
        "prices": prices,
        "newly_triggered": newly_triggered,
        "alerts_by_symbol": alert_store.summary_by_symbol(),
    }


# ── named watchlists (persistent screener universes) ──────────────────────────

@router.get("/api/watchlists")
async def list_watchlists():
    """All saved universes (id, name, count) — symbol arrays omitted for size."""
    return db.watchlists_all()


@router.post("/api/watchlists")
async def save_watchlist(item: dict):
    """
    Create or replace a named universe.
    Body: {"name": "Swing Universe", "symbols": ["RELIANCE", ...]}.
    Upserts on name; returns the stored record with its id.
    """
    name = (item.get("name") or "").strip()
    symbols = item.get("symbols")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not isinstance(symbols, list) or not symbols:
        raise HTTPException(status_code=400, detail="symbols (non-empty array) is required")
    return db.watchlist_save(name, symbols[:500])


@router.get("/api/watchlists/{list_id}")
async def get_watchlist_by_id(list_id: int):
    """Load a saved universe (with its full symbol array) on app start."""
    wl = db.watchlist_get(list_id)
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return wl


@router.delete("/api/watchlists/{list_id}")
async def delete_watchlist(list_id: int):
    if not db.watchlist_delete(list_id):
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return {"ok": True}


@router.get("/api/watchlists/{list_id}/quotes")
async def watchlist_quotes(list_id: int):
    """
    Lightweight top-level refresh for a saved universe: latest prices only,
    no deep analysis. Backs the frontend's "Refresh List" button so a 400-name
    universe can be price-refreshed without re-running the full screen.
    """
    wl = db.watchlist_get(list_id)
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    syms = wl.get("symbols", [])
    if not syms:
        return {"id": list_id, "prices": {}}
    instruments = [f"NSE:{s}" for s in syms]
    prices = await price.get_ltp_multiple(instruments)
    return {"id": list_id, "name": wl["name"], "count": len(syms), "prices": prices}
