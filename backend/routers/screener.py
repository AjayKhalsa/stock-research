"""Route: SSE batch screener stream."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import quant_engine
import swing_engine
import decision_engine
import price_service as price
import data_cache
from stock_service import _plan_summary, _screen_row

router = APIRouter()


def _json_clean(obj):
    """Replace NaN/Inf with None recursively — json.dumps emits bare NaN
    (invalid JSON) and the browser's JSON.parse rejects the whole payload."""
    if isinstance(obj, float):
        return None if (obj != obj or obj in (float("inf"), float("-inf"))) else obj
    if isinstance(obj, dict):
        return {k: _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_clean(v) for v in obj]
    return obj


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(_json_clean(obj))}\n\n"


@router.get("/api/screen-stream")
async def screen_stream(symbols: str):
    """
    SSE batch screener. Pass symbols as comma/space/newline separated list.
    Streams {type:'log'|'result'|'done'|'error'} events; the 'result' event
    carries the full cross-sectionally ranked list.
    """
    syms, seen = [], set()
    for s in symbols.replace("\n", ",").replace(" ", ",").split(","):
        s = s.strip().upper()
        if s and s not in seen:
            seen.add(s)
            syms.append(s)
    syms = syms[:500]

    if not syms:
        raise HTTPException(status_code=400, detail="No symbols provided")

    async def _gen():
        yield _sse({"type": "log", "text": f"Screening {len(syms)} stocks..."})

        # Concurrency 4: cached symbols skip scraping entirely, so large runs
        # mostly parallelize yfinance history fetches; kept modest to stay
        # under Screener.in's rate limits on cold batches.
        sem = asyncio.Semaphore(4)

        async def fetch_one(sym: str):
            async with sem:
                sdata, _meta = await data_cache.get_fundamentals(sym)
                hist  = await price.get_historical(f"NSE:{sym}", days=450)
                return sym, sdata, hist

        rows, done = [], 0
        for coro in asyncio.as_completed([fetch_one(s) for s in syms]):
            sym, sdata, hist = await coro
            done += 1
            if not sdata:
                yield _sse({"type": "log", "text": f"SKIP {sym} - no Screener data ({done}/{len(syms)})"})
                continue
            try:
                quant = quant_engine.compute_all(sdata)
                pf    = swing_engine.compute_price_factors(hist)
                plans = decision_engine.build_trade_plans(hist, sdata, quant)
                rows.append({**_screen_row(sym, sdata, quant, pf),
                             **_plan_summary(plans)})
                pio = quant["piotroski"].get("score")
                z   = quant["altman"].get("z_score")
                yield _sse({"type": "log",
                            "text": f"OK {sym:<14} Pio={pio}  Z={z}  "
                                    f"{'tech ok' if pf else 'no price data'}  ({done}/{len(syms)})"})
            except Exception as e:
                yield _sse({"type": "log", "text": f"ERR {sym}: {e} ({done}/{len(syms)})"})

        if not rows:
            yield _sse({"type": "error", "text": "No stocks could be fetched - check symbols."})
            return

        yield _sse({"type": "log", "text": f"Ranking {len(rows)} stocks cross-sectionally..."})
        ranked = swing_engine.cross_sectional_rank(rows)
        yield _sse({"type": "result", "data": ranked, "technicals_available": True})
        yield _sse({"type": "done", "text": "Screen complete"})

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
