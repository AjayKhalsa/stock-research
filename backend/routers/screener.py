"""Route: SSE batch screener stream (chunked async, progressive results)."""

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

# Stocks per streamed batch. Each batch is fetched concurrently (bounded by
# the semaphore below) and its rows are pushed to the client as soon as the
# batch completes, so a 400-stock run populates the table progressively.
BATCH_SIZE = 25
# Concurrency within a batch. Kept well under the batch size so Screener.in
# is not hammered on cold runs; cached symbols skip scraping entirely.
FETCH_CONCURRENCY = 6


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


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _build_row(sym: str, sdata: dict, hist: list) -> dict | None:
    """
    Build one screener row. Never drops a stock that has price history:
      - full/partial fundamentals -> quant-scored row
      - price history only        -> technicals-only row flagged price_only
    Returns None only when there is neither fundamentals nor price data.
    """
    has_fund = bool(sdata)
    has_price = bool(hist)
    if not has_fund and not has_price:
        return None

    pf = swing_engine.compute_price_factors(hist) if has_price else {}
    quant = quant_engine.compute_all(sdata) if has_fund else {}
    plans = decision_engine.build_trade_plans(hist, sdata or None, quant or None)

    row = {**_screen_row(sym, sdata or {}, quant or {}, pf),
           **_plan_summary(plans)}

    if not has_fund:
        completeness = "price_only"
    else:
        completeness = sdata.get("data_completeness", "full")
    row["data_completeness"] = completeness
    row["partial_data"] = completeness != "full"
    return row


@router.get("/api/screen-stream")
async def screen_stream(symbols: str):
    """
    SSE batch screener. Pass symbols comma/space/newline separated.
    Event stream:
      log     progress lines
      batch   rows for a just-completed chunk (progressive table population)
      result  the full cross-sectionally ranked list (final, authoritative)
      done    completion
      error   fatal
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
        total = len(syms)
        yield _sse({"type": "log", "text": f"Screening {total} stocks in "
                    f"batches of {BATCH_SIZE}..."})

        sem = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def fetch_one(sym: str):
            async with sem:
                try:
                    sdata, _meta = await data_cache.get_fundamentals(sym)
                    hist = await price.get_historical(f"NSE:{sym}", days=450)
                    return sym, sdata, hist, None
                except Exception as e:                       # noqa: BLE001
                    return sym, {}, [], str(e)

        rows, done, skipped = [], 0, 0
        for batch in _chunks(syms, BATCH_SIZE):
            results = await asyncio.gather(*(fetch_one(s) for s in batch))
            batch_rows = []
            for sym, sdata, hist, err in results:
                done += 1
                if err:
                    skipped += 1
                    yield _sse({"type": "log",
                                "text": f"ERR {sym}: {err} ({done}/{total})"})
                    continue
                row = _build_row(sym, sdata, hist)
                if row is None:
                    skipped += 1
                    yield _sse({"type": "log",
                                "text": f"SKIP {sym} - no data ({done}/{total})"})
                    continue
                rows.append(row)
                batch_rows.append(row)

            # Progressive push: the client appends these immediately (unranked).
            yield _sse({"type": "batch", "rows": batch_rows,
                        "done": done, "total": total, "kept": len(rows),
                        "skipped": skipped})

        if not rows:
            yield _sse({"type": "error",
                        "text": "No stocks could be fetched - check symbols "
                                "or try again (source may be rate-limited)."})
            return

        yield _sse({"type": "log",
                    "text": f"Ranking {len(rows)} stocks cross-sectionally"
                            f"{f' ({skipped} skipped)' if skipped else ''}..."})
        ranked = swing_engine.cross_sectional_rank(rows)
        yield _sse({"type": "result", "data": ranked,
                    "technicals_available": True, "skipped": skipped})
        yield _sse({"type": "done", "text": "Screen complete"})

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
