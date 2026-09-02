"""Staged, failure-safe daily all-NSE analysis pipeline."""

from __future__ import annotations

import asyncio
import heapq
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

import cfo_engine
import ai_committee
import data_cache
import db
import nse_bhavcopy
import price_service as price
import swing_engine
import symbol_resolver

IST = ZoneInfo("Asia/Kolkata")
HISTORY_BATCH = 75
DEEP_CANDIDATES = 150
PUBLISHED_CANDIDATES = 100
FUNDAMENTAL_CONCURRENCY = 4
MINIMUM_USABLE_HISTORY_RATIO = 0.50

_RUN_LOCK = asyncio.Lock()
_ACTIVE_TASK: asyncio.Task | None = None


def _is_mainboard_cash_equity(row: dict) -> bool:
    """Defensive ETF/other-series filter on top of NSE's equity master."""
    symbol = str(row.get("symbol") or "").upper()
    name = str(row.get("name") or "").upper()
    series = str(row.get("series") or "EQ").upper()
    if series != "EQ":
        return False
    if symbol.endswith(("BEES", "ETF")):
        return False
    return not any(term in name for term in ("EXCHANGE TRADED FUND", " ETF", "MUTUAL FUND"))


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _market_regime(nifty: list[dict]) -> dict:
    factors = swing_engine.compute_price_factors(nifty)
    trend = factors.get("trend_score", 0)
    if trend >= 2:
        state, posture = "constructive", "Normal risk; favour sector leaders"
    elif trend >= 0:
        state, posture = "mixed", "Selective entries; demand cleaner setups"
    else:
        state, posture = "defensive", "Reduce new risk and protect open positions"
    return {"state": state, "posture": posture, "nifty": factors,
            "as_of": nifty[-1].get("date") if nifty else None}


def _sector_scores(items: list[tuple[dict, dict, dict]]) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for preliminary, fundamentals, _meta in items:
        sector = fundamentals.get("sector") or "Unclassified"
        grouped[sector].append(preliminary.get("preliminary_score", 0))
    if not grouped:
        return {}
    raw = {sector: median(scores) for sector, scores in grouped.items()}
    low, high = min(raw.values()), max(raw.values())
    if high == low:
        return {sector: 50.0 for sector in raw}
    return {sector: round(30 + (value - low) / (high - low) * 55, 1)
            for sector, value in raw.items()}


def _build_sector_snapshots(candidates: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.get("sector") or "Unclassified"].append(candidate)
    sectors = []
    for sector, rows in grouped.items():
        ordered = sorted(rows, key=lambda r: (r.get("rank_value", -9), r.get("score", 0)), reverse=True)
        actionable = sum(r.get("action") in {"BUY_NOW", "WAIT_FOR_ENTRY"} for r in rows)
        avg_rs = median([r["components"]["relative_strength"] for r in rows])
        avg_trend = median([r["components"]["trend_volume"] for r in rows])
        sectors.append({
            "sector": sector, "score": round(median([r["score"] for r in rows]), 1),
            "breadth_pct": round(sum(r["technicals"].get("trend_score", 0) > 0 for r in rows) / len(rows) * 100, 1),
            "relative_strength": round(avg_rs, 1), "volume_participation": round(avg_trend, 1),
            "eligible_count": len(rows), "actionable_count": actionable,
            "top_candidates": [{k: r.get(k) for k in ("symbol", "company", "action", "score", "expected_r", "confidence")}
                               for r in ordered[:5]],
        })
    sectors.sort(key=lambda s: (s["actionable_count"], s["score"]), reverse=True)
    for rank, sector in enumerate(sectors, 1):
        sector["rank"] = rank
        sector["trend"] = "Leading" if rank <= max(2, len(sectors) // 4) else "Improving" if sector["score"] >= 55 else "Lagging"
    return sectors


def _changes(previous: dict | None, candidates: list[dict]) -> dict:
    if not previous:
        return {"new": [c["symbol"] for c in candidates[:10]], "upgraded": [], "downgraded": []}
    old = {c.get("symbol"): c for c in db.snapshot_candidates(previous.get("snapshot_id"), 150)}
    priority = {"BUY_NOW": 4, "WAIT_FOR_ENTRY": 3, "WATCH": 2, "DATA_INSUFFICIENT": 1, "AVOID": 0}
    new, upgraded, downgraded = [], [], []
    for current in candidates:
        prior = old.get(current["symbol"])
        if not prior:
            new.append(current["symbol"])
        elif priority.get(current["action"], 0) > priority.get(prior.get("action"), 0):
            upgraded.append(current["symbol"])
        elif priority.get(current["action"], 0) < priority.get(prior.get("action"), 0):
            downgraded.append(current["symbol"])
    return {"new": new[:20], "upgraded": upgraded[:20], "downgraded": downgraded[:20]}


def _trading_sessions_until(raw_date: str | None, as_of: str | None) -> int | None:
    try:
        event = date.fromisoformat(str(raw_date)[:10])
        start = date.fromisoformat(str(as_of)[:10]) if as_of else datetime.now(IST).date()
    except (TypeError, ValueError):
        return None
    if event < start:
        return None
    sessions, cursor = 0, start
    while cursor < event:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            sessions += 1
    return sessions


async def run_daily_pipeline(job_id: str) -> None:
    async with _RUN_LOCK:
        previous = db.latest_analysis_snapshot()
        try:
            db.update_job_run(job_id, stage="universe", progress=0, total=0)
            universe, nifty, bhavcopy = await asyncio.gather(
                symbol_resolver.get_nse_equity_universe(refresh=True),
                price.get_index_historical("^NSEI", days=500),
                nse_bhavcopy.fetch_latest_bhavcopy(),
            )
            universe = [row for row in universe if _is_mainboard_cash_equity(row)]
            if not universe:
                raise RuntimeError("Official NSE equity universe is unavailable")
            db.update_job_run(job_id, stage="technical_scan", total=len(universe),
                              payload={"universe": len(universe), "bhavcopy_as_of": bhavcopy.get("as_of")})

            preliminary: list[dict] = []
            usable_histories = 0
            retained_candles: dict[str, list[dict]] = {}
            top_candle_heap: list[tuple[float, str]] = []
            priority_symbols = {w["symbol"] for w in db.watchlist_all()}
            priority_symbols.update(t["symbol"] for t in db.paper_trades_active())
            names = {row["symbol"]: row.get("name") or row["symbol"] for row in universe}
            done = 0
            for batch in _chunks([row["symbol"] for row in universe], HISTORY_BATCH):
                histories = await price.get_historical_multiple(
                    [f"NSE:{s}" for s in batch], days=520, cache_results=False,
                )
                for symbol in batch:
                    candles = histories.get(f"NSE:{symbol}") or []
                    if len(candles) >= 252:
                        usable_histories += 1
                    row = cfo_engine.preliminary_analysis(symbol, names[symbol], candles, nifty)
                    if row.get("eligible"):
                        row.pop("candles", None)
                        preliminary.append(row)
                        heap_key = (float(row.get("preliminary_score") or 0), symbol)
                        if symbol in priority_symbols:
                            retained_candles[symbol] = candles
                        if len(top_candle_heap) < DEEP_CANDIDATES:
                            heapq.heappush(top_candle_heap, heap_key)
                            retained_candles[symbol] = candles
                        elif heap_key > top_candle_heap[0]:
                            _score, displaced = heapq.heapreplace(top_candle_heap, heap_key)
                            if displaced not in priority_symbols:
                                retained_candles.pop(displaced, None)
                            retained_candles[symbol] = candles
                del histories
                done += len(batch)
                db.update_job_run(job_id, stage="technical_scan", progress=done, total=len(universe),
                                  payload={"eligible": len(preliminary), "universe": len(universe),
                                           "usable_histories": usable_histories})

            minimum_usable = max(PUBLISHED_CANDIDATES, int(len(universe) * MINIMUM_USABLE_HISTORY_RATIO))
            if usable_histories < minimum_usable:
                raise RuntimeError(
                    f"Price-history coverage too low: {usable_histories}/{len(universe)} "
                    f"usable (minimum {minimum_usable})"
                )
            if len(preliminary) < PUBLISHED_CANDIDATES:
                raise RuntimeError(
                    f"Eligible universe too small: {len(preliminary)} "
                    f"(minimum {PUBLISHED_CANDIDATES})"
                )

            preliminary.sort(key=lambda item: item.get("preliminary_score", 0), reverse=True)
            deep = preliminary[:DEEP_CANDIDATES]
            seen = {item["symbol"] for item in deep}
            deep.extend(item for item in preliminary if item["symbol"] in priority_symbols and item["symbol"] not in seen)
            # Candidate dossiers must remain useful while Yahoo is delayed or
            # unreachable, so retain daily price/volume bars for the enriched
            # bench rather than fetching them only when a user opens a stock.
            for item in deep:
                item["candles"] = retained_candles.get(item["symbol"]) or []
                price.persist_history(f"NSE:{item['symbol']}", 520, item.get("candles") or [])
            db.update_job_run(job_id, stage="fundamental_enrichment", progress=0, total=len(deep),
                              payload={"eligible": len(preliminary), "deep_candidates": len(deep)})

            semaphore = asyncio.Semaphore(FUNDAMENTAL_CONCURRENCY)
            enriched: list[tuple[dict, dict, dict]] = []

            async def enrich(item: dict):
                async with semaphore:
                    fundamentals, meta = await data_cache.get_fundamentals(
                        item["symbol"], ttl_hours=168, require_classification=True,
                    )
                    return item, fundamentals, meta

            tasks = [asyncio.create_task(enrich(item)) for item in deep]
            for index, task in enumerate(asyncio.as_completed(tasks), 1):
                enriched.append(await task)
                if index == len(tasks) or index % 10 == 0:
                    db.update_job_run(job_id, stage="fundamental_enrichment", progress=index, total=len(tasks))

            regimes = _sector_scores(enriched)
            official = bhavcopy.get("closes") or {}
            event_calendar = []
            candidates = []
            fundamentals_by_symbol = {}
            event_as_of = bhavcopy.get("as_of") or (nifty[-1].get("date") if nifty else None)
            for item, fundamentals, meta in enriched:
                sessions_to_results = _trading_sessions_until(fundamentals.get("earnings_date"), event_as_of)
                blocked_for_results = sessions_to_results is not None and sessions_to_results <= 2
                candidate = cfo_engine.analyze_candidate(
                    item, fundamentals, meta, official_close=official.get(item["symbol"]),
                    official_date=bhavcopy.get("as_of"),
                    sector_regime_score=regimes.get(fundamentals.get("sector") or "Unclassified", 50),
                    results_within_two_sessions=blocked_for_results,
                )
                if sessions_to_results is not None:
                    candidate["results_date"] = fundamentals.get("earnings_date")
                    event_calendar.append({"symbol": item["symbol"], "date": fundamentals.get("earnings_date"),
                                           "sessions_away": sessions_to_results,
                                           "entry_blocked": blocked_for_results})
                candidates.append(candidate)
                fundamentals_by_symbol[item["symbol"]] = fundamentals

            # Review only the highest-consequence calls to stay inside free API
            # quotas. The full stock Research view can run the committee for
            # any other name on demand. Even here the model is downgrade-only.
            committee_pool = sorted(
                (candidate for candidate in candidates
                 if candidate["action"] in {"BUY_NOW", "WAIT_FOR_ENTRY"} and not candidate["hard_blocks"]),
                key=lambda row: row["rank_value"], reverse=True,
            )[:12]
            committee_sem = asyncio.Semaphore(2)

            async def committee_review(candidate: dict):
                async with committee_sem:
                    ledger = await ai_committee.review(candidate, fundamentals_by_symbol[candidate["symbol"]])
                    candidate["evidence"]["ai_committee"] = ledger
                    candidate["action"] = ledger.get("final_action", candidate["action"])

            if committee_pool:
                db.update_job_run(job_id, stage="ai_committee", progress=0, total=len(committee_pool))
                committee_tasks = [asyncio.create_task(committee_review(candidate)) for candidate in committee_pool]
                for index, task in enumerate(asyncio.as_completed(committee_tasks), 1):
                    await task
                    db.update_job_run(job_id, stage="ai_committee", progress=index, total=len(committee_pool))

            # Historical validation is shown as a separate trust signal.  It
            # does not erase today's observable setup state; READY/NEAR labels
            # remain research signals until the tracked sample matures.
            validation_status = db.get_setting("cfo_historical_validation_status", "pending")
            for candidate in candidates:
                candidate["evidence"]["model"]["validation_status"] = validation_status
            action_order = {"BUY_NOW": 5, "WAIT_FOR_ENTRY": 4, "WATCH": 3, "DATA_INSUFFICIENT": 2, "AVOID": 1}
            candidates.sort(key=lambda row: (action_order.get(row["action"], 0), row["rank_value"], row["score"]), reverse=True)
            candidates = candidates[:PUBLISHED_CANDIDATES]
            sector_counts: dict[str, int] = defaultdict(int)
            for rank, candidate in enumerate(candidates, 1):
                candidate["global_rank"] = rank
                sector_counts[candidate["sector"]] += 1
                candidate["sector_rank"] = sector_counts[candidate["sector"]]
            sectors = _build_sector_snapshots(candidates)

            active_trades = db.paper_trades_active()
            settings = db.portfolio_settings()
            # Legacy paper trades do not retain an executed share quantity, so
            # deriving heat from an arbitrary quantity would present false
            # precision. Treat each active position as one allocated risk unit
            # until quantity-aware trade records are available.
            estimated_heat = min(
                settings["max_portfolio_heat_pct"],
                len(active_trades) * settings["risk_per_trade_pct"],
            )
            now = datetime.now(IST)
            data_exceptions = []
            if not official:
                data_exceptions.append("NSE bhavcopy unavailable: actionable calls are held at DATA_INSUFFICIENT")
            missing_fund = sum(c["data_completeness"] != "full" for c in candidates)
            if missing_fund:
                data_exceptions.append(f"{missing_fund} ranked candidates have partial or missing financial evidence")
            summary = {
                "published_at": now.isoformat(), "snapshot_time_ist": now.strftime("%d %b %Y, %H:%M IST"),
                "market_regime": _market_regime(nifty), "universe": {
                    "official_equities": len(universe), "eligible": len(preliminary),
                    "deeply_enriched": len(enriched), "published": len(candidates),
                },
                "data_health": {"status": "attention" if data_exceptions else "healthy",
                                "exceptions": data_exceptions, "official_price_as_of": bhavcopy.get("as_of"),
                                "fundamentals_policy": "after results or every 7 days"},
                "portfolio": {"open_positions": len(active_trades), "heat_pct": round(estimated_heat, 2),
                              "heat_method": "allocated_risk_estimate",
                              "max_heat_pct": settings["max_portfolio_heat_pct"], "actions": []},
                "changes": _changes(previous, candidates),
                "results_calendar": sorted(event_calendar, key=lambda event: event["date"])[:30],
                "validation": {"status": "early", "closed_paper_trades": db.paper_trades_stats()["wins"] + db.paper_trades_stats()["losses"],
                               "required_for_mature_confidence": 100},
                "candidates": candidates, "sectors": sectors,
            }
            trading_date = bhavcopy.get("as_of") or (nifty[-1].get("date") if nifty else now.date().isoformat())
            snapshot_id = db.publish_analysis_snapshot(summary, candidates, sectors,
                                                       model_version=cfo_engine.MODEL_VERSION,
                                                       trading_date=trading_date)
            db.screen_save("CFO Morning Top 100", [c["symbol"] for c in candidates], candidates, time.time())
            db.update_job_run(job_id, status="completed", stage="published", progress=len(candidates), total=len(candidates),
                              payload={"snapshot_id": snapshot_id, "published": len(candidates), "eligible": len(preliminary)})
        except Exception as exc:  # failed runs never touch the last valid snapshot
            db.update_job_run(job_id, status="failed", stage="failed",
                              error=f"{type(exc).__name__}: {exc}")
            print(f"[market_pipeline] daily pipeline failed: {type(exc).__name__}: {exc}")


def start_daily_pipeline() -> dict:
    global _ACTIVE_TASK
    latest = db.latest_job_run()
    if _ACTIVE_TASK and not _ACTIVE_TASK.done():
        return latest or {"status": "running"}
    job = db.create_job_run()
    _ACTIVE_TASK = asyncio.create_task(run_daily_pipeline(job["id"]))
    return job
