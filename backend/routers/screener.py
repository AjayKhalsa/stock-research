"""Route: SSE batch screener stream (chunked async, progressive results)."""

from __future__ import annotations

import asyncio
import hmac
import json
import time
import re
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import config
import db
import chartink_scraper
import quant_engine
import swing_engine
import decision_engine
import price_service as price
import data_cache
from stock_service import _plan_summary, _screen_row

router = APIRouter()
SYMBOL_RE = re.compile(r"^[A-Z0-9&.-]{1,30}$")

AUTO_SCREEN_NAME = "Daily Chartink Auto-Run"

# Stocks per streamed batch. Each batch is fetched concurrently (bounded by
# the semaphore below) and its rows are pushed to the client as soon as the
# batch completes, so a 400-stock run populates the table progressively.
BATCH_SIZE = 25
# Concurrency within a batch. Kept well under the batch size so Screener.in
# is not hammered on cold runs; cached symbols skip scraping entirely.
FETCH_CONCURRENCY = 6
# Chartink can return hundreds of stocks. The broad universe pass is
# deliberately price-first: Yahoo history is enough to rank swing setups,
# while scraping fundamentals for every match quickly trips Screener.in's
# rate limit. Full fundamentals are still fetched when a user opens a stock.
AUTO_SCREEN_FETCH_CONCURRENCY = 12

AUTO_SCREEN_STATUS_KEY = "auto_screen_last_run"
AUTO_SCREEN_LOCK = asyncio.Lock()


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
        if SYMBOL_RE.fullmatch(s) and s not in seen:
            seen.add(s)
            syms.append(s)
    syms = syms[:500]

    if not syms:
        raise HTTPException(status_code=400, detail="No symbols provided")

    async def _gen():
        total = len(syms)
        yield _sse({"type": "log", "text": f"Building swing-trade evidence for "
                    f"{total} stock{'s' if total != 1 else ''}..."})

        sem = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def fetch_one(sym: str):
            async with sem:
                started = time.perf_counter()
                try:
                    # Fundamentals and price history are independent. Fetching
                    # them sequentially made even a seven-symbol cold run wait
                    # for two network round trips per stock.
                    (sdata, _meta), hist = await asyncio.gather(
                        data_cache.get_fundamentals(sym),
                        price.get_historical(f"NSE:{sym}", days=450),
                    )
                    elapsed_ms = round((time.perf_counter() - started) * 1000)
                    return sym, sdata, hist, None, elapsed_ms
                except Exception as e:                       # noqa: BLE001
                    elapsed_ms = round((time.perf_counter() - started) * 1000)
                    return sym, {}, [], str(e), elapsed_ms

        rows, done, skipped = [], 0, 0
        for batch in _chunks(syms, BATCH_SIZE):
            tasks = [asyncio.create_task(fetch_one(s)) for s in batch]
            try:
                # Emit each symbol as soon as it finishes. asyncio.gather made
                # the progress indicator sit at 0/N until the slowest stock in
                # a 25-symbol batch completed, which looked like a frozen app.
                for completed in asyncio.as_completed(tasks):
                    sym, sdata, hist, err, elapsed_ms = await completed
                    done += 1
                    completed_rows = []
                    if err:
                        skipped += 1
                        yield _sse({"type": "log",
                                    "text": f"Could not analyze {sym}: {err}"})
                    else:
                        row = _build_row(sym, sdata, hist)
                        if row is None:
                            skipped += 1
                            yield _sse({"type": "log",
                                        "text": f"No usable data for {sym}"})
                        else:
                            rows.append(row)
                            completed_rows.append(row)

                    yield _sse({"type": "batch", "rows": completed_rows,
                                "symbol": sym, "elapsed_ms": elapsed_ms,
                                "done": done, "total": total,
                                "kept": len(rows), "skipped": skipped})
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()

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


# ── Chartink auto-fetcher: URL setting + daily cron endpoint ───────────────────

class ChartinkUrlBody(BaseModel):
    url: str


class ChartinkScanClauseBody(BaseModel):
    scan_clause: str


class ChartinkFetchBody(BaseModel):
    url: str = ""


def _clean_chartink_url(value: str) -> str:
    url = value.strip()
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in {"chartink.com", "www.chartink.com"}
            or not parsed.path.startswith("/screener/")):
        raise HTTPException(
            status_code=400,
            detail="Enter a valid https://chartink.com/screener/... URL",
        )
    return url


@router.get("/api/settings/chartink-url")
def get_chartink_url():
    return {"url": db.get_setting("chartink_url", config.DEFAULT_CHARTINK_URL)}


@router.post("/api/settings/chartink-url")
def set_chartink_url(body: ChartinkUrlBody):
    url = _clean_chartink_url(body.url) if body.url.strip() else ""
    db.set_setting("chartink_url", url)
    return {"url": url}


@router.get("/api/settings/chartink-scan-clause")
def get_chartink_scan_clause():
    return {"scan_clause": db.get_setting("chartink_scan_clause", "")}


@router.post("/api/settings/chartink-scan-clause")
def set_chartink_scan_clause(body: ChartinkScanClauseBody):
    """
    Optional override: most Chartink screener pages build the scan_clause
    with client-side JS right before submission, so chartink_scraper's
    HTML-based extraction never finds it. Storing the real clause here (grab
    it once from the browser — e.g. DevTools' Network tab on the "Run Scan"
    request, or the page's rendered condition text) skips that fragile step
    entirely for this screener from then on.
    """
    db.set_setting("chartink_scan_clause", body.scan_clause.strip())
    return {"scan_clause": body.scan_clause.strip()}


@router.post("/api/chartink/fetch")
async def fetch_chartink_matches(body: ChartinkFetchBody):
    """Fetch the current NSE matches for a public Chartink screener.

    The broad-universe pass is calculated in the backend from price history
    and saved with ranked rows. The frontend can therefore render the result
    immediately instead of opening a second 400+-stock stream and attempting
    a fundamentals scrape for every symbol.
    """
    requested = body.url.strip() or await run_in_threadpool(
        db.get_setting, "chartink_url", config.DEFAULT_CHARTINK_URL
    )
    if not requested:
        raise HTTPException(status_code=400, detail="Save a Chartink screener URL first")
    url = _clean_chartink_url(requested)
    await run_in_threadpool(db.set_setting, "chartink_url", url)

    # Prefer the query embedded in the live page so edits to the Chartink
    # screener are picked up automatically. Retain the stored manual clause
    # only as a fallback for older pages that do not expose atlas_query.
    tickers = await chartink_scraper.fetch_screener_tickers(url)
    scan_clause = await run_in_threadpool(db.get_setting, "chartink_scan_clause", "") or None
    if not tickers and scan_clause:
        tickers = await chartink_scraper.fetch_screener_tickers(url, scan_clause)
    if not tickers:
        raise HTTPException(
            status_code=502,
            detail="Chartink returned no symbols. The screener may have no current matches or may be rate-limited.",
        )

    clean_tickers = list(dict.fromkeys(tickers))[:500]
    ranked = await _fetch_and_rank(clean_tickers, concurrency=AUTO_SCREEN_FETCH_CONCURRENCY)
    if not ranked:
        raise HTTPException(
            status_code=502,
            detail="Chartink returned symbols, but market history was unavailable for all of them.",
        )
    ranked_symbols = [row["symbol"] for row in ranked]
    screen = await run_in_threadpool(
        db.screen_save, AUTO_SCREEN_NAME, ranked_symbols, ranked
    )
    return {**screen, "url": url}


async def _set_auto_screen_status(**fields) -> None:
    """Merge-update the persisted last-run record for the daily cron job —
    read via GET /api/auto-screen/status. Backed by the existing generic
    settings table (db.get_setting/set_setting), no new schema needed."""
    current = await run_in_threadpool(db.get_setting, AUTO_SCREEN_STATUS_KEY, {}) or {}
    current.update(fields)
    await run_in_threadpool(db.set_setting, AUTO_SCREEN_STATUS_KEY, current)


async def _fetch_and_rank(
    syms: list[str],
    concurrency: int = AUTO_SCREEN_FETCH_CONCURRENCY,
    track_status: bool = False,
) -> list[dict]:
    """
    Fast broad-universe pass used by both manual Chartink refresh and cron.

    Only price history is fetched here. Pulling Screener.in fundamentals for
    400+ symbols caused sustained HTTP 429s and turned a sub-minute market
    scan into an hour-long degraded run. A stock's full research view still
    fetches and displays fundamentals on demand.
    """
    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(sym: str):
        async with sem:
            try:
                hist = await price.get_historical(f"NSE:{sym}", days=450)
                return sym, hist, None
            except Exception as e:                            # noqa: BLE001
                return sym, [], str(e)

    total = len(syms)
    rows, done = [], 0
    tasks = [asyncio.create_task(fetch_one(sym)) for sym in syms]
    try:
        for completed in asyncio.as_completed(tasks):
            sym, hist, err = await completed
            done += 1
            row = None if err else _build_row(sym, {}, hist)
            if row is not None:
                rows.append(row)
            if track_status and (done % BATCH_SIZE == 0 or done == total):
                await _set_auto_screen_status(done=done, total=total, count=len(rows))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()

    return swing_engine.cross_sectional_rank(rows) if rows else []


async def _run_auto_screen(url: str) -> None:
    """The actual scrape -> fetch/rank -> save sequence, run in the
    background (see auto_screen() below) so the HTTP request that triggers
    it returns immediately regardless of how long this takes."""
    async with AUTO_SCREEN_LOCK:
        await _set_auto_screen_status(status="running", started_at=time.time(), finished_at=None,
                                      done=0, total=0, count=0, error=None)
        try:
            scan_clause = await run_in_threadpool(db.get_setting, "chartink_scan_clause", "") or None
            tickers = await chartink_scraper.fetch_screener_tickers(url, scan_clause)
            if not tickers:
                await _set_auto_screen_status(status="done", finished_at=time.time(),
                                               count=0, error="Chartink returned no tickers")
                return

            tickers = list(dict.fromkeys(tickers))[:500]
            await _set_auto_screen_status(total=len(tickers))
            ranked = await _fetch_and_rank(
                tickers,
                concurrency=AUTO_SCREEN_FETCH_CONCURRENCY,
                track_status=True,
            )
            ranked_symbols = [row["symbol"] for row in ranked]
            if ranked_symbols:
                await run_in_threadpool(
                    db.screen_save, AUTO_SCREEN_NAME, ranked_symbols, ranked
                )

            final_count = len(ranked_symbols)
            await _set_auto_screen_status(
                status="done", finished_at=time.time(), count=final_count,
                error=None if final_count else "No usable data for any matched ticker",
            )
        except Exception as e:                                    # noqa: BLE001
            await _set_auto_screen_status(status="error", finished_at=time.time(), error=str(e))


@router.post("/api/auto-screen")
async def auto_screen(
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
):
    """
    Daily cron target: scrape the saved Chartink screener URL, cross-sectionally
    rank the matches, and upsert them as the "Daily Chartink Auto-Run" saved
    screen. Gated by a Bearer token matching CRON_SECRET_KEY — an unset key
    disables the endpoint entirely. Keeping the secret in a header prevents
    it from leaking through URL and proxy logs.

    Runs in the background: a cold run over hundreds of symbols can take
    minutes, well past what Render's proxy, Cloudflare's edge, or a cron
    pinger's own timeout will tolerate on a held-open request. This endpoint
    validates the secret and the configured URL, schedules the real work,
    and returns immediately. Progress/outcome: GET /api/auto-screen/status.
    """
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if (not config.CRON_SECRET_KEY
            or not hmac.compare_digest(supplied, config.CRON_SECRET_KEY)):
        raise HTTPException(status_code=403, detail="Invalid or missing secret")

    if AUTO_SCREEN_LOCK.locked():
        return {"status": "already_running"}

    url = await run_in_threadpool(db.get_setting, "chartink_url", "")
    if not url:
        raise HTTPException(
            status_code=400,
            detail="No Chartink URL configured — set one via POST /api/settings/chartink-url",
        )

    background_tasks.add_task(_run_auto_screen, url)
    return {"status": "started"}


@router.get("/api/auto-screen/status")
def auto_screen_status():
    """Last (or in-progress) daily auto-fetch run: status/done/total/count/
    error, so the outcome is visible in the UI instead of only in server
    logs."""
    record = db.get_setting(AUTO_SCREEN_STATUS_KEY, {}) or {}
    if record.get("finished_at"):
        record["age_minutes"] = round(max(0.0, time.time() - record["finished_at"]) / 60, 1)
    return record
