"""Read APIs and protected orchestration for the CFO workspace."""

from __future__ import annotations

import hmac
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

import config
import db
import market_pipeline
import price_service

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
    item = db.candidate_analysis(symbol)
    if not item:
        raise HTTPException(status_code=404, detail="Candidate is not present in the latest snapshot")
    item["daily_history"] = (await price_service.get_historical(f"NSE:{symbol}", days=520))[-252:]
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
async def run_daily_job(authorization: Optional[str] = Header(default=None)):
    _feature_enabled()
    expected = config.CRON_SECRET_KEY.strip()
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not expected or not hmac.compare_digest(supplied, expected):
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
