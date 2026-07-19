"""Routes: search/resolve, single-stock research, plans, alpha, regime."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import conviction_engine
import price_service as price
import symbol_resolver
import stock_service

router = APIRouter()


@router.get("/api/search")
async def search(q: str, limit: int = 15):
    """
    Autocomplete: NSE directory matches first (fast, full company names),
    then Yahoo Finance results for anything the local list misses.
    """
    local, yahoo = await asyncio.gather(
        symbol_resolver.search_local(q, limit=8),
        price.search_instruments(q, limit),
    )
    seen = {item["symbol"] for item in local}
    merged = local + [y for y in yahoo if y["symbol"] not in seen]
    return merged[:limit]


@router.post("/api/resolve")
async def resolve_symbols(item: dict):
    """
    Resolve free-text queries (company names or symbols) to NSE symbols.
    Body: {"queries": ["Aegis Logistics Ltd", "DELHIVERY", ...]}
    Returns [{"query", "symbol"|null, "name", "exchange", "method"}].
    """
    queries = item.get("queries")
    if not isinstance(queries, list) or not queries:
        raise HTTPException(status_code=400, detail="queries (non-empty list) required")
    return await symbol_resolver.resolve_many([str(q) for q in queries[:500]])


@router.get("/api/stock/{symbol}")
async def get_stock(symbol: str, exchange: str = "NSE"):
    return await stock_service.build_stock_payload(symbol, exchange)


@router.get("/api/stock/{symbol}/plan")
async def get_stock_plan(symbol: str, exchange: str = "NSE"):
    """Trade Decision Engine plans + conviction dossier (see stock_service)."""
    return await stock_service.build_plan_payload(symbol, exchange)


@router.get("/api/stock/{symbol}/alpha")
async def get_stock_alpha(symbol: str, exchange: str = "NSE"):
    """Full research payload incl. quant scores + AI thesis (see stock_service)."""
    return await stock_service.build_alpha_payload(symbol, exchange)


@router.get("/api/market-regime")
async def get_market_regime():
    """NIFTY tape check: Risk-On / Neutral / Risk-Off with guidance (cached 30m)."""
    nifty = await price.get_index_historical("^NSEI", days=400)
    return conviction_engine.market_regime(nifty)


@router.get("/api/ltp/{symbol}")
async def ltp(symbol: str, exchange: str = "NSE"):
    return await price.get_ltp(f"{exchange}:{symbol.upper()}")
