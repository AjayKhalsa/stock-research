import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("STOCKLENS_DATA_DIR", tempfile.mkdtemp())

from fastapi.testclient import TestClient  # noqa: E402
import cfo_engine  # noqa: E402
import ai_committee  # noqa: E402
import db  # noqa: E402
import price_service  # noqa: E402
import market_pipeline  # noqa: E402
from routers import cfo_workspace as cfo_router  # noqa: E402
from main import app  # noqa: E402


def candles(count=300, close=100.0, volume=1_000_000):
    return [
        {"date": f"2025-01-{(i % 28) + 1:02d}", "open": close + i * .05,
         "high": close + i * .05 + 1, "low": close + i * .05 - 1,
         "close": close + i * .05, "volume": volume}
        for i in range(count)
    ]


class CfoEngineTests(unittest.TestCase):
    def test_bulk_history_timeout_falls_back_to_persisted_candles(self):
        fallback = candles(3)
        with patch.object(price_service, "_read_persisted_history",
                          return_value=(fallback, 1)), \
             patch.object(price_service, "_fetch_chart_history",
                          new=AsyncMock(return_value=("NSE:TIMEOUTTEST", []))):
            result = asyncio.run(price_service.get_historical_multiple(
                ["NSE:TIMEOUTTEST"], days=520,
            ))
        self.assertEqual(result["NSE:TIMEOUTTEST"], fallback)

    def test_chart_payload_adjusts_ohlc_and_keeps_volume(self):
        payload = {"chart": {"result": [{
            "timestamp": [1_725_000_000],
            "indicators": {
                "quote": [{"open": [100], "high": [110], "low": [90],
                           "close": [100], "volume": [12345]}],
                "adjclose": [{"adjclose": [50]}],
            },
        }]}}
        result = price_service._chart_payload_to_candles(payload)
        self.assertEqual(result[0]["open"], 50)
        self.assertEqual(result[0]["high"], 55)
        self.assertEqual(result[0]["volume"], 12345)

    def test_eligibility_enforces_history_price_and_traded_value(self):
        accepted = cfo_engine.eligibility(candles())
        self.assertTrue(accepted["eligible"])
        self.assertGreater(accepted["median_traded_value"], 5_00_00_000)

        rejected = cfo_engine.eligibility(candles(count=120, close=10, volume=1_000))
        self.assertFalse(rejected["eligible"])
        self.assertEqual(len(rejected["reasons"]), 3)

    def test_price_conflict_blocks_recommendations(self):
        self.assertTrue(cfo_engine.price_reconciliation(100, 100.5)["recommendations_allowed"])
        conflict = cfo_engine.price_reconciliation(100, 102)
        self.assertEqual(conflict["status"], "conflict")
        self.assertFalse(conflict["recommendations_allowed"])
        mismatch = cfo_engine.price_reconciliation(100, 100, "2026-08-27", "2026-08-28")
        self.assertEqual(mismatch["status"], "session_mismatch")
        self.assertFalse(mismatch["recommendations_allowed"])

    def test_financial_model_does_not_apply_industrial_diagnostics(self):
        assessment = cfo_engine.assess_cfo_health({
            "sector": "Financial Services", "industry": "Private Bank",
            "data_completeness": "full", "roe": 18,
            "annual_pl": [{"net_profit": 100}, {"net_profit": 125}],
        }, quant={"altman": {"z_score": -5}, "beneish": {"m_score": 4}})
        self.assertEqual(assessment["sector_model"], "financial")
        self.assertFalse(assessment["diagnostics_applicable"]["altman"])
        self.assertNotEqual(assessment["gate"], "hard_block")

    def test_distress_requires_confirmation_and_severe_pledge_blocks(self):
        fundamentals = {
            "sector": "Industrials", "data_completeness": "full", "roe": 5, "roce": 4,
            "debt_to_equity": 2.1, "promoter_pledge": 62,
            "annual_pl": [{"net_profit": 100}], "annual_cf": [{"cfo": 20}],
        }
        quant = {"altman": {"z_score": .7}, "beneish": {"m_score": -2},
                 "piotroski": {"score": 2}}
        result = cfo_engine.assess_cfo_health(fundamentals, quant)
        self.assertEqual(result["gate"], "hard_block")
        self.assertTrue(any("Confirmed distress" in item for item in result["hard_blocks"]))
        self.assertTrue(any("promoter pledge" in item for item in result["hard_blocks"]))

    def test_score_weights_are_complete_and_deterministic(self):
        self.assertAlmostEqual(sum(cfo_engine.SCORE_WEIGHTS.values()), 1.0)
        self.assertEqual(set(cfo_engine.SCORE_WEIGHTS), {
            "setup", "relative_strength", "trend_volume", "cfo_health",
            "sector_regime", "liquidity", "valuation",
        })

    def test_daily_pipeline_requires_majority_price_history_coverage(self):
        self.assertEqual(market_pipeline.MINIMUM_USABLE_HISTORY_RATIO, 0.50)
        self.assertEqual(market_pipeline.PUBLISHED_CANDIDATES, 100)

    def test_ai_committee_cannot_upgrade_and_can_downgrade(self):
        candidate = {"symbol": "TCS", "action": "WATCH", "price": 100,
                     "setup_label": "Pullback", "trade_plan": {}}
        bullish = {"conviction_score": 95, "suggested_action": "Buy on dips",
                   "thesis_summary": "Strong", "bear_case_ledger": []}
        with patch("ai_committee.ai_engine.generate_alpha_thesis",
                   new=AsyncMock(return_value=bullish)):
            result = asyncio.run(ai_committee.review(candidate, {}))
        self.assertEqual(result["final_action"], "WATCH")

        weak_candidate = {**candidate, "action": "BUY_NOW"}
        bearish = {"conviction_score": 20, "suggested_action": "Avoid",
                   "thesis_summary": "Weak", "bear_case_ledger": []}
        with patch("ai_committee.ai_engine.generate_alpha_thesis",
                   new=AsyncMock(return_value=bearish)):
            result = asyncio.run(ai_committee.review(weak_candidate, {}))
        self.assertEqual(result["final_action"], "AVOID")


class CfoWorkspaceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_portfolio_settings_validate_and_persist(self):
        invalid = self.client.put("/api/portfolio/settings", json={"risk_per_trade_pct": 5})
        self.assertEqual(invalid.status_code, 422)
        saved = self.client.put("/api/portfolio/settings", json={"risk_per_trade_pct": 0.6})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["risk_per_trade_pct"], 0.6)
        self.assertNotIn("account_value", saved.json())
        self.assertEqual(self.client.get("/api/portfolio/settings").json()["max_open_positions"], 8)

    def test_daily_job_is_protected(self):
        response = self.client.post("/api/jobs/daily/run")
        self.assertEqual(response.status_code, 401)

    def test_daily_job_accepts_verified_github_oidc(self):
        with patch("routers.cfo_workspace._daily_job_authorized",
                   new=AsyncMock(return_value=True)), \
             patch("routers.cfo_workspace.market_pipeline.start_daily_pipeline",
                   return_value={"status": "queued", "id": "job-1"}):
            response = self.client.post(
                "/api/jobs/daily/run",
                headers={"Authorization": "Bearer signed-github-token"},
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["id"], "job-1")

    def test_github_job_token_is_restricted_to_repo_main_and_live_run(self):
        installation = MagicMock()
        installation.json.return_value = {
            "repositories": [{"full_name": "AjayKhalsa/stock-research"}],
        }
        run = MagicMock()
        run.json.return_value = {
            "repository": {"full_name": "AjayKhalsa/stock-research"},
            "head_branch": "main", "event": "workflow_dispatch",
            "status": "in_progress",
        }
        client = AsyncMock()
        client.get.side_effect = [installation, run]
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)
        with patch("routers.cfo_workspace.httpx.AsyncClient", return_value=context):
            self.assertTrue(asyncio.run(
                cfo_router._verify_github_job_token("github-job-token", "123")
            ))

            run.json.return_value["status"] = "completed"
            client.get.side_effect = [installation, run]
            self.assertFalse(asyncio.run(
                cfo_router._verify_github_job_token("github-job-token", "123")
            ))

    def test_snapshot_publish_is_readable_through_new_apis(self):
        candidate = {"symbol": "TCS", "company": "Tata Consultancy Services", "sector": "IT",
                     "global_rank": 1, "sector_rank": 1, "action": "WATCH", "score": 70,
                     "confidence": 60, "trade_plan": {}}
        sector = {"sector": "IT", "rank": 1, "score": 70}
        snapshot_id = db.publish_analysis_snapshot(
            {"published_at": "now", "candidates": [candidate], "sectors": [sector]},
            [candidate], [sector], model_version="test-v1", trading_date="2026-08-29",
        )
        morning = self.client.get("/api/morning-brief")
        self.assertEqual(morning.status_code, 200)
        self.assertEqual(morning.json()["snapshot_id"], snapshot_id)
        with patch("routers.cfo_workspace.price_service.get_historical",
                   new=AsyncMock(return_value=candles(8))):
            detail = self.client.get("/api/candidates/TCS")
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn("position_size", detail.json())
        self.assertEqual(len(detail.json()["daily_history"]), 8)
        self.assertIn("trust", detail.json())
        self.assertIn("external_research", detail.json())
        self.assertGreaterEqual(morning.json()["external_enrichment"]["covered"], 3)
        self.assertEqual(self.client.get("/api/sectors/IT").status_code, 200)

    def test_bull_ai_seed_is_source_labelled_and_score_neutral(self):
        evidence = db.candidate_enrichments("STOVEKRAFT")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["provider"], "Bull AI")
        self.assertEqual(evidence[0]["score_effect"], "none")
        self.assertTrue(evidence[0]["cards"][0]["sources"][0]["url"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
