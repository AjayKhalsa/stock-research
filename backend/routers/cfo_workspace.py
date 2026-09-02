"""Read APIs and protected orchestration for the CFO workspace."""

from __future__ import annotations

import asyncio
import hmac
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

import config
import cfo_engine
import data_cache
import db
import market_pipeline
import nse_bhavcopy
import price_service
import symbol_resolver

router = APIRouter()


class PortfolioSettingsUpdate(BaseModel):
    risk_per_trade_pct: Optional[float] = Field(None, gt=0, le=2)
    max_portfolio_heat_pct: Optional[float] = Field(None, gt=0, le=12)
    max_open_positions: Optional[int] = Field(None, ge=1, le=30)
    max_positions_per_sector: Optional[int] = Field(None, ge=1, le=10)
    max_sector_exposure_pct: Optional[float] = Field(None, gt=0, le=50)
    minimum_reward_risk: Optional[float] = Field(None, ge=1, le=5)
    t1_r: Optional[float] = Field(None, ge=1, le=5)
    t2_r: Optional[float] = Field(None, ge=1, le=8)
    time_stop_sessions: Optional[int] = Field(None, ge=5, le=120)


def _feature_enabled() -> None:
    if not config.CFO_WORKSPACE_V1:
        raise HTTPException(status_code=404, detail="CFO workspace is disabled")


async def _verify_github_job_token(token: str, run_id: str) -> bool:
    """Accept a live GitHub installation token for an approved main run.

    The run must still be queued/in progress, which prevents replay after the
    workflow-scoped token has completed its only intended job.
    """
    if not token or not run_id.isdigit():
        return False
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "StockLens-Daily-Runner",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            installation_response = await client.get(
                "https://api.github.com/installation/repositories?per_page=100",
                headers=headers,
            )
            installation_response.raise_for_status()
            repositories = installation_response.json().get("repositories") or []
            if not any(repo.get("full_name") == config.GITHUB_ACTIONS_REPOSITORY
                       for repo in repositories):
                return False
            run_response = await client.get(
                f"https://api.github.com/repos/{config.GITHUB_ACTIONS_REPOSITORY}/actions/runs/{run_id}",
                headers=headers,
            )
            run_response.raise_for_status()
            run = run_response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return False
    return (
        (run.get("repository") or {}).get("full_name") == config.GITHUB_ACTIONS_REPOSITORY
        and run.get("head_branch") == "main"
        and run.get("event") in {"schedule", "workflow_dispatch"}
        and run.get("status") in {"queued", "in_progress"}
    )


async def _daily_job_authorized(token: str, run_id: str) -> bool:
    expected = config.CRON_SECRET_KEY.strip()
    if expected and hmac.compare_digest(token, expected):
        return True
    return await _verify_github_job_token(token, run_id)


@router.get("/api/morning-brief")
def morning_brief():
    _feature_enabled()
    snapshot = db.latest_analysis_snapshot()
    if snapshot:
        snapshot["external_enrichment"] = db.enrichment_coverage("Bull AI")
        return snapshot
    return {
        "status": "setup_required", "snapshot_id": None, "published_at": None,
        "snapshot_time_ist": "Waiting for the first validated daily run",
        "market_regime": {"state": "unknown", "posture": "No valid snapshot yet"},
        "universe": {"official_equities": 0, "eligible": 0, "deeply_enriched": 0, "published": 0},
        "data_health": {"status": "attention", "exceptions": ["First CFO snapshot has not been published"]},
        "portfolio": {"open_positions": 0, "heat_pct": 0, "max_heat_pct": db.portfolio_settings()["max_portfolio_heat_pct"], "actions": []},
        "changes": {"new": [], "upgraded": [], "downgraded": []},
        "results_calendar": [], "validation": {"status": "early", "closed_paper_trades": 0,
                                                 "required_for_mature_confidence": 100},
        "candidates": [], "sectors": [],
        "external_enrichment": db.enrichment_coverage("Bull AI"),
    }


@router.get("/api/sectors/{sector}")
def sector_detail(sector: str):
    _feature_enabled()
    item = db.sector_snapshot(sector)
    if not item:
        raise HTTPException(status_code=404, detail="Sector is not present in the latest snapshot")
    snapshot = db.latest_analysis_snapshot() or {}
    item["candidates"] = [c for c in db.snapshot_candidates(snapshot.get("snapshot_id"), 150)
                          if (c.get("sector") or "Unclassified").lower() == sector.lower()]
    return item


@router.get("/api/candidates/{symbol}")
async def candidate_detail(symbol: str):
    _feature_enabled()
    symbol = symbol.upper().strip()
    item = db.candidate_analysis(symbol)
    if not item:
        resolved = await symbol_resolver.resolve_one(symbol)
        if not resolved.get("symbol"):
            raise HTTPException(status_code=404, detail="NSE stock was not found")
        symbol = resolved["symbol"]
        candles, nifty, fund_result, bhavcopy = await asyncio.gather(
            price_service.get_historical(f"NSE:{symbol}", days=520),
            price_service.get_index_historical("^NSEI", days=500),
            data_cache.get_fundamentals(symbol, ttl_hours=168, require_classification=True),
            nse_bhavcopy.fetch_latest_bhavcopy(),
        )
        preliminary = cfo_engine.preliminary_analysis(
            symbol, resolved.get("name") or symbol, candles, nifty,
        )
        if not preliminary.get("eligible"):
            reasons = preliminary.get("eligibility", {}).get("reasons") or []
            raise HTTPException(
                status_code=422,
                detail="This stock is searchable, but is outside today's liquid swing universe: "
                       + "; ".join(reasons),
            )
        fundamentals, meta = fund_result
        earnings_sessions = market_pipeline._trading_sessions_until(
            fundamentals.get("earnings_date"),
            bhavcopy.get("as_of") or (candles[-1].get("date") if candles else None),
        )
        item = cfo_engine.analyze_candidate(
            preliminary, fundamentals, meta,
            official_close=(bhavcopy.get("closes") or {}).get(symbol),
            official_date=bhavcopy.get("as_of"),
            sector_regime_score=50,
            results_within_two_sessions=(earnings_sessions is not None and earnings_sessions <= 2),
        )
        item["global_rank"] = None
        item["sector_rank"] = None
        item["universe_membership"] = {
            "ranked": False,
            "label": "On-demand analysis — not in today's Top 100",
        }
        item["evidence"]["model"]["validation_status"] = db.get_setting(
            "cfo_historical_validation_status", "pending",
        )
        if earnings_sessions is not None:
            item["results_date"] = fundamentals.get("earnings_date")
    else:
        item["universe_membership"] = {
            "ranked": True,
            "label": f"Ranked #{item.get('global_rank')} in today's Top 100",
        }
        candles = await price_service.get_historical(f"NSE:{symbol}", days=520)
    latest_snapshot = db.latest_analysis_snapshot() or {}
    item["snapshot_id"] = latest_snapshot.get("snapshot_id") if item["universe_membership"]["ranked"] else None
    item["daily_history"] = candles[-252:]
    item["external_research"] = db.candidate_enrichments(symbol)
    price_status = item.get("evidence", {}).get("price", {}).get("status") or "unknown"
    completeness = item.get("data_completeness") or "missing"
    cfo_gate = item.get("cfo", {}).get("gate") or "data_insufficient"
    validation = db.get_setting("cfo_historical_validation_status", "pending")
    item["trust"] = {
        "price": "pass" if price_status == "matched" else "block",
        "financials": "pass" if completeness == "full" else "caution" if completeness == "partial" else "block",
        "cfo_gate": "pass" if cfo_gate == "pass" else "caution" if cfo_gate == "caution" else "block",
        "results": "block" if item.get("results_risk") == "blocked" else "pass" if item.get("results_date") else "caution",
        "historical_validation": "pass" if validation == "passed" else "early",
        "external_evidence": "pass" if item["external_research"] else "not_covered",
    }
    return item


@router.get("/api/jobs/daily/status")
def daily_status():
    _feature_enabled()
    return db.latest_job_run() or {"status": "never_run", "stage": "waiting", "progress": 0, "total": 0}


@router.post("/api/jobs/daily/run", status_code=202)
async def run_daily_job(
    authorization: Optional[str] = Header(default=None),
    x_github_run_id: Optional[str] = Header(default=None),
):
    _feature_enabled()
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not await _daily_job_authorized(supplied, (x_github_run_id or "").strip()):
        raise HTTPException(status_code=401, detail="Valid daily-job bearer token required")
    return market_pipeline.start_daily_pipeline()


@router.get("/api/portfolio/settings")
def get_portfolio_settings():
    _feature_enabled()
    return db.portfolio_settings()


@router.put("/api/portfolio/settings")
def update_portfolio_settings(body: PortfolioSettingsUpdate):
    _feature_enabled()
    value = body.model_dump(exclude_none=True)
    return db.set_portfolio_settings(value)
