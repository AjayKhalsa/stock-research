"""
Routes: saved screens — named, persistent, re-loadable screener universes.

A saved screen maps a custom name to an array of tickers so a screened set can
be reloaded later with fresh data. Distinct from /api/watchlist (the sidebar's
single active list of individually-tracked stocks).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

import db

router = APIRouter()
SYMBOL_RE = re.compile(r"^[A-Z0-9&.-]{1,30}$")


class ScreenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    tickers: list[str] = Field(min_length=2, max_length=500)
    ranked_data: list[dict] | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("name is required")
        return cleaned

    @field_validator("tickers")
    @classmethod
    def clean_tickers(cls, values: list[str]) -> list[str]:
        seen, cleaned = set(), []
        for raw in values:
            symbol = str(raw).strip().upper()
            if symbol and not SYMBOL_RE.fullmatch(symbol):
                raise ValueError(f"invalid NSE ticker: {symbol}")
            if symbol and symbol not in seen:
                seen.add(symbol)
                cleaned.append(symbol)
        if len(cleaned) < 2:
            raise ValueError("at least 2 unique tickers are required")
        return cleaned


@router.get("/api/screens")
async def list_screens():
    """All saved screens (id, name, count) — ticker arrays omitted, for a dropdown."""
    return db.screens_all()


@router.post("/api/screens")
async def save_screen(item: ScreenCreate):
    """
    Persist a saved screen.
    Body: {"name": "My Top Picks", "tickers": ["JUSTDIAL", "PAYTM", "OFSS"],
           "ranked_data": [...]}  (ranked_data optional).
    Upserts on name (re-saving a name replaces its tickers/ranked_data);
    returns the stored record including its id. Including the already-computed
    ranked rows (the frontend already has them at save time) means loading
    this screen later renders instantly instead of re-running a live fetch.
    """
    return db.screen_save(item.name, item.tickers, ranked_data=item.ranked_data)


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
