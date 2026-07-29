"""
Routes: saved screens — named, persistent, re-loadable screener universes.

A saved screen maps a custom name to an array of tickers so a screened set can
be reloaded later with fresh data. Distinct from /api/watchlist (the sidebar's
single active list of individually-tracked stocks).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import db

router = APIRouter()


@router.get("/api/screens")
async def list_screens():
    """All saved screens (id, name, count) — ticker arrays omitted, for a dropdown."""
    return db.screens_all()


@router.post("/api/screens")
async def save_screen(item: dict):
    """
    Persist a saved screen.
    Body: {"name": "My Top Picks", "tickers": ["JUSTDIAL", "PAYTM", "OFSS"],
           "ranked_data": [...]}  (ranked_data optional).
    Upserts on name (re-saving a name replaces its tickers/ranked_data);
    returns the stored record including its id. Including the already-computed
    ranked rows (the frontend already has them at save time) means loading
    this screen later renders instantly instead of re-running a live fetch.
    """
    name = (item.get("name") or "").strip()
    tickers = item.get("tickers")
    ranked_data = item.get("ranked_data")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not isinstance(tickers, list) or not tickers:
        raise HTTPException(status_code=400, detail="tickers (non-empty array) is required")
    if ranked_data is not None and not isinstance(ranked_data, list):
        raise HTTPException(status_code=400, detail="ranked_data must be an array")
    return db.screen_save(name, tickers[:500], ranked_data=ranked_data)


@router.get("/api/screens/{screen_id}")
async def get_screen(screen_id: int):
    """Full payload of tickers for one saved screen (used by the load workflow)."""
    screen = db.screen_get(screen_id)
    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found")
    return screen


@router.delete("/api/screens/{screen_id}")
async def delete_screen(screen_id: int):
    if not db.screen_delete(screen_id):
        raise HTTPException(status_code=404, detail="Screen not found")
    return {"ok": True}
