"""Route: SSE batch screener stream (chunked async, progressive results)."""

from __future__ import annotations

import asyncio
import json
import time
import re
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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
# Lower concurrency for the unattended daily cron run (_fetch_and_rank /
# /api/auto-screen): nobody is watching it, so trading some speed for a
# gentler footprint on Screener.in is the right call at 400+-symbol scale —
# kept as its own constant so tuning one path never silently affects the
# other.
AUTO_SCREEN_FETCH_CONCURRENCY = 3

AUTO_SCREEN_STATUS_KEY = "auto_screen_last_run"


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
async def get_chartink_url():
    return {"url": db.get_setting("chartink_url", config.DEFAULT_CHARTINK_URL)}


@router.post("/api/settings/chartink-url")
async def set_chartink_url(body: ChartinkUrlBody):
    url = _clean_chartink_url(body.url) if body.url.strip() else ""
    db.set_setting("chartink_url", url)
    return {"url": url}


@router.get("/api/settings/chartink-scan-clause")
async def get_chartink_scan_clause():
    return {"scan_clause": db.get_setting("chartink_scan_clause", "")}


@router.post("/api/settings/chartink-scan-clause")
async def set_chartink_scan_clause(body: ChartinkScanClauseBody):
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

    This is the interactive, ticker-only path: it returns quickly, persists
    the refreshed universe, and lets the frontend stream/rank those symbols.
    The slower unattended /api/auto-screen path remains available for cron.
    """
    requested = body.url.strip() or db.get_setting("chartink_url", config.DEFAULT_CHARTINK_URL)
    if not requested:
        raise HTTPException(status_code=400, detail="Save a Chartink screener URL first")
    url = _clean_chartink_url(requested)
    db.set_setting("chartink_url", url)

    # Prefer the query embedded in the live page so edits to the Chartink
    # screener are picked up automatically. Retain the stored manual clause
    # only as a fallback for older pages that do not expose atlas_query.
    tickers = await chartink_scraper.fetch_screener_tickers(url)
    scan_clause = db.get_setting("chartink_scan_clause", "") or None
    if not tickers and scan_clause:
        tickers = await chartink_scraper.fetch_screener_tickers(url, scan_clause)
    if not tickers:
        raise HTTPException(
            status_code=502,
            detail="Chartink returned no symbols. The screener may have no current matches or may be rate-limited.",
        )

    screen = db.screen_save(AUTO_SCREEN_NAME, tickers[:500])
    return {**screen, "url": url}


def _set_auto_screen_status(**fields) -> None:
    """Merge-update the persisted last-run record for the daily cron job —
    read via GET /api/auto-screen/status. Backed by the existing generic
    settings table (db.get_setting/set_setting), no new schema needed."""
    current = db.get_setting(AUTO_SCREEN_STATUS_KEY, {}) or {}
    current.update(fields)
    db.set_setting(AUTO_SCREEN_STATUS_KEY, current)


# Heuristic rate-limit backoff for the unattended cron path. There is no
# clean "was rate-limited" signal threaded up from screener_scraper.py's
# fetch_screener_full — doing so would mean changing the return shape of a
# function shared by every stock-detail endpoint in the app, not just this
# one nightly job, which is a lot of blast radius for one cron path's
# politeness. Instead: a batch that mostly comes back with no usable row is
# a reasonable proxy for scrape friction (rate limiting or similar), and is
# fully local to this function — no shared code touched. Not a general
# retry framework; Path A (the interactive /api/screen-stream) never uses
# this and always runs at full speed, since a human is actively waiting.
_BAD_BATCH_HIT_RATE = 0.5      # < 50% of a batch producing a row looks like friction
_BACKOFF_BASE_SECONDS = 5
_BACKOFF_STEP_SECONDS = 5
_BACKOFF_MAX_SECONDS = 30


async def _fetch_and_rank(syms: list[str], concurrency: int = FETCH_CONCURRENCY) -> list[dict]:
    """
    Same fetch-then-rank shape as /api/screen-stream, without the SSE
    progress events — used for the one-shot cron run. Unlike the interactive
    stream, this:
      - saves progress after every batch (db.screen_save is upsert-on-name,
        so a mid-run crash/restart leaves the saved screen at whatever the
        last completed batch produced, not empty)
      - updates the auto_screen_last_run status record after every batch
      - backs off between batches when a batch looks rate-limited
    """
    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(sym: str):
        async with sem:
            try:
                sdata, _meta = await data_cache.get_fundamentals(sym)
                hist = await price.get_historical(f"NSE:{sym}", days=450)
                return sym, sdata, hist, None
            except Exception as e:                            # noqa: BLE001
                return sym, {}, [], str(e)

    batches = list(_chunks(syms, BATCH_SIZE))
    total = len(syms)
    rows, done, ranked, consecutive_bad_batches = [], 0, [], 0

    for i, batch in enumerate(batches):
        results = await asyncio.gather(*(fetch_one(s) for s in batch))
        batch_hits = 0
        for sym, sdata, hist, err in results:
            done += 1
            if err:
                continue
            row = _build_row(sym, sdata, hist)
            if row is not None:
                rows.append(row)
                batch_hits += 1

        ranked = swing_engine.cross_sectional_rank(rows) if rows else []
        ranked_symbols = [r["symbol"] for r in ranked]
        if ranked_symbols:
            # Save the full computed rows, not just symbols — this is what
            # lets loading "Daily Chartink Auto-Run" render instantly instead
            # of re-running a live fetch every time it's opened.
            db.screen_save(AUTO_SCREEN_NAME, ranked_symbols, ranked_data=ranked)
        _set_auto_screen_status(done=done, total=total, count=len(ranked_symbols))

        hit_rate = batch_hits / len(batch) if batch else 1.0
        if hit_rate < _BAD_BATCH_HIT_RATE:
            consecutive_bad_batches += 1
            if i < len(batches) - 1:   # no point backing off after the last batch
                delay = min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS
                            + _BACKOFF_STEP_SECONDS * (consecutive_bad_batches - 1))
                print(f"[auto-screen] batch {i + 1}/{len(batches)} hit rate "
                      f"{hit_rate:.0%} — backing off {delay}s before the next batch")
                await asyncio.sleep(delay)
        else:
            consecutive_bad_batches = 0

    return ranked


async def _run_auto_screen(url: str) -> None:
    """The actual scrape -> fetch/rank -> save sequence, run in the
    background (see auto_screen() below) so the HTTP request that triggers
    it returns immediately regardless of how long this takes."""
    _set_auto_screen_status(status="running", started_at=time.time(), finished_at=None,
                             done=0, total=0, count=0, error=None)
    try:
        scan_clause = db.get_setting("chartink_scan_clause", "") or None
        tickers = await chartink_scraper.fetch_screener_tickers(url, scan_clause)
        if not tickers:
            _set_auto_screen_status(status="done", finished_at=time.time(),
                                     count=0, error="Chartink returned no tickers")
            return

        tickers = tickers[:500]
        _set_auto_screen_status(total=len(tickers))
        await _fetch_and_rank(tickers, concurrency=AUTO_SCREEN_FETCH_CONCURRENCY)

        latest = db.get_setting(AUTO_SCREEN_STATUS_KEY, {}) or {}
        final_count = latest.get("count", 0)
        _set_auto_screen_status(
            status="done", finished_at=time.time(), count=final_count,
            error=None if final_count else "No usable data for any matched ticker",
        )
    except Exception as e:                                        # noqa: BLE001
        _set_auto_screen_status(status="error", finished_at=time.time(), error=str(e))


@router.post("/api/auto-screen")
async def auto_screen(background_tasks: BackgroundTasks, secret: str = ""):
    """
    Daily cron target: scrape the saved Chartink screener URL, cross-sectionally
    rank the matches, and upsert them as the "Daily Chartink Auto-Run" saved
    screen. Gated by CRON_SECRET_KEY — an unset key disables the endpoint
    entirely (an empty secret must never be accepted as valid).

    Runs in the background: a cold run over hundreds of symbols can take
    minutes, well past what Render's proxy, Cloudflare's edge, or a cron
    pinger's own timeout will tolerate on a held-open request. This endpoint
    validates the secret and the configured URL, schedules the real work,
    and returns immediately. Progress/outcome: GET /api/auto-screen/status.
    """
    if not config.CRON_SECRET_KEY or secret != config.CRON_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing secret")

    url = db.get_setting("chartink_url", "")
    if not url:
        raise HTTPException(
            status_code=400,
            detail="No Chartink URL configured — set one via POST /api/settings/chartink-url",
        )

    background_tasks.add_task(_run_auto_screen, url)
    return {"status": "started"}


@router.get("/api/auto-screen/status")
async def auto_screen_status():
    """Last (or in-progress) daily auto-fetch run: status/done/total/count/
    error, so the outcome is visible in the UI instead of only in server
    logs."""
    record = db.get_setting(AUTO_SCREEN_STATUS_KEY, {}) or {}
    if record.get("finished_at"):
        record["age_minutes"] = round(max(0.0, time.time() - record["finished_at"]) / 60, 1)
    return record
