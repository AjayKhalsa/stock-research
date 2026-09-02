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
import data_cache  # noqa: E402
import db  # noqa: E402
import price_service  # noqa: E402
import market_pipeline  # noqa: E402
import screener_scraper  # noqa: E402
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
            "setup", "relative_strength", "volume", "business_quality",
            "earnings_momentum", "overhead_supply", "tradeability",
            "move_potential", "sector_regime", "market_regime",
        })

    def test_earnings_momentum_uses_yoy_qoq_margins_and_acceleration(self):
        fundamentals = {
            "sector": "Industrials", "debt_to_equity": 0.4,
            "quarterly_results": [
                {"quarter": "Q-5", "revenue": 80, "ebitda": 8, "net_profit": 4, "opm": 10},
                {"quarter": "Q-4", "revenue": 100, "ebitda": 10, "net_profit": 5, "opm": 10},
                {"quarter": "Q-3", "revenue": 102, "ebitda": 10.2, "net_profit": 5.1, "opm": 10},
                {"quarter": "Q-2", "revenue": 105, "ebitda": 10.5, "net_profit": 5.2, "opm": 10},
                {"quarter": "Q-1", "revenue": 110, "ebitda": 11, "net_profit": 5.5, "opm": 10},
                {"quarter": "Q0", "revenue": 140, "ebitda": 21, "net_profit": 11.2, "opm": 15},
            ],
            "annual_pl": [{"net_profit": 100}], "annual_cf": [{"cfo": 110}],
        }
        result = cfo_engine.assess_earnings_momentum(fundamentals)
        self.assertEqual(result["status"], "full")
        self.assertEqual(result["margin_direction"], "strong expansion")
        self.assertAlmostEqual(result["metrics"]["revenue_growth_yoy"], 40.0)
        self.assertAlmostEqual(result["metrics"]["ebitda_margin_change_yoy"], 5.0)
        self.assertGreater(result["score"], 75)

    def test_targets_are_structural_then_rr_is_calculated(self):
        targets = cfo_engine.decision_engine._structural_targets(
            entry_mid=100, entry_high=101, risk=5, atr=2,
            pivots={"supports": [{"price": 94, "touches": 2}],
                    "resistances": [{"price": 112, "touches": 3}]},
            setup_kind="pullback",
        )
        self.assertEqual(targets[0]["price"], 112)
        self.assertEqual(targets[0]["rr"], 2.4)
        self.assertIn("historical resistance", targets[0]["basis"])

    def test_overhead_supply_measures_clear_air_in_pct_and_atr(self):
        highs = [95, 96, 97, 98, 102, 99, 98, 97, 96]
        history = [
            {"date": f"2026-01-{index + 1:02d}", "open": high - 2,
             "high": high, "low": high - 3, "close": high - 2, "volume": 1000}
            for index, high in enumerate(highs)
        ]
        result = cfo_engine.swing_features.assess_overhead_supply(history, 100, 2)
        self.assertEqual(result["clear_air_pct"], 2.0)
        self.assertEqual(result["clear_air_atr"], 1.0)
        self.assertEqual(result["severity"], "severe")

    def test_tradeability_rewards_linear_price_paths(self):
        history = [
            {"date": str(index), "open": 100 + index - .2, "high": 100 + index + .4,
             "low": 100 + index - .4, "close": 100 + index, "volume": 1000}
            for index in range(100)
        ]
        result = cfo_engine.swing_features.assess_tradeability(history)
        self.assertIn(result["label"], {"Very clean", "Clean"})
        self.assertGreater(result["metrics"]["r2_50"], .99)

    def test_relative_strength_has_multiple_market_horizons(self):
        stock = candles(close=100)
        benchmark = candles(close=100)
        for index, row in enumerate(stock):
            row["close"] += index * .15
        result = cfo_engine.swing_features.assess_relative_strength(stock, benchmark)
        self.assertGreater(result["score"], 50)
        self.assertEqual(set(result["horizons_pct_points"]), {"5d", "20d", "60d", "120d"})

    def test_volume_and_contraction_are_explicit_features(self):
        history = candles()
        for index, row in enumerate(history):
            row["volume"] = 2_000_000 if index == len(history) - 1 else 1_000_000
        volume = cfo_engine.swing_features.assess_volume(history)
        contraction = cfo_engine.swing_features.assess_volatility_contraction(history)
        self.assertGreater(volume["metrics"]["rvol"], 1)
        self.assertIn(contraction["status"], {"contracting", "mild", "not_contracting"})

    def test_setup_types_have_independent_auditable_scorecards(self):
        history = candles()
        engines = cfo_engine.swing_features.assess_setup_engines(
            history, "pullback", {"price": history[-1]["close"], "atr": 2,
                                  "rsi": 49, "trend_score": 2},
            {"signals": {"close_range": {"last": .75},
                         "pullback_volume": {"state": "dry_up"}}},
            {"score": 75}, {"score": 70, "metrics": {"rvol": 1.4}},
            {"score": 80, "severity": "acceptable"},
            {"score": 72, "label": "Clean"},
            {"score": 65, "status": "contracting"}, 85,
        )
        self.assertEqual(engines["selected"]["name"], "pullback")
        self.assertEqual(set(engines) - {"selected"},
                         {"breakout", "pullback", "trend_continuation"})
        for name in ("breakout", "pullback", "trend_continuation"):
            self.assertAlmostEqual(sum(item["weight"] for item in engines[name]["criteria"]), 1.0)

    def test_data_confidence_is_explicitly_not_win_probability(self):
        cfo = {"completeness": "full", "metrics": {
            "roe": 18, "roce": 20, "cfo_pat": 1.1, "debt_to_equity": 0.3,
        }}
        earnings = {"coverage": 100}
        result = cfo_engine.assess_data_confidence(
            candles(), {"annual_pl": [{}], "annual_cf": [{}], "earnings_date": "2026-09-20"},
            {"stale": False}, cfo, earnings, {"status": "matched"},
        )
        self.assertEqual(result["overall"], 100)
        self.assertIn("not win probability", result["meaning"])

    def test_ready_and_near_entry_states_are_not_hidden_by_early_validation(self):
        swing = {"entry": {"low": 98, "high": 102}, "risk_reward": 1.5,
                 "verdict": "Wait"}
        ready, ready_reason = cfo_engine.classify_action(
            score=74, setup_name="pullback", swing=swing, current=100,
            actionable_data=True, hard_blocks=[],
        )
        near, _ = cfo_engine.classify_action(
            score=70, setup_name="pullback", swing=swing, current=104,
            actionable_data=True, hard_blocks=[],
        )
        self.assertEqual(ready, "BUY_NOW")
        self.assertIn("entry zone", ready_reason)
        self.assertEqual(near, "WAIT_FOR_ENTRY")

    def test_screener_classification_is_parsed_for_sector_dashboard(self):
        parsed = screener_scraper.parse_screener("""
            <h1 class="h2">Computer Age Management Services Ltd</h1>
            <a title="Broad Sector">Financial Services</a>
            <a title="Sector">Financial Services</a>
            <a title="Broad Industry">Capital Markets</a>
            <a title="Industry">Depositories and Other Intermediaries</a>
        """)
        self.assertEqual(parsed["sector"], "Financial Services")
        self.assertEqual(parsed["industry"], "Depositories and Other Intermediaries")
        self.assertEqual(parsed["classification_source"], "screener")
        self.assertEqual(parsed["classification_version"], 2)

    def test_screener_sector_is_not_overwritten_by_yahoo_taxonomy(self):
        result = data_cache.enrich_with_yf_fundamentals(
            {"sector": "Financial Services", "industry": "Capital Markets",
             "classification_source": "screener", "classification_version": 2},
            {"sector": "Technology", "industry": "Software Infrastructure",
             "bs_by_year": {}, "pl_by_year": {}, "cf_by_year": {}},
        )
        self.assertEqual(result["sector"], "Financial Services")
        self.assertEqual(result["industry"], "Capital Markets")

    def test_daily_pipeline_requires_majority_price_history_coverage(self):
        self.assertEqual(market_pipeline.MINIMUM_USABLE_HISTORY_RATIO, 0.50)
        self.assertEqual(market_pipeline.PUBLISHED_CANDIDATES, 100)

    def test_market_regime_includes_breadth_and_risk_score(self):
        regime = market_pipeline._market_regime(
            candles(), [{"factors": {"trend_score": 2}} for _ in range(8)]
            + [{"factors": {"trend_score": -1}} for _ in range(2)],
        )
        self.assertEqual(regime["state"], "risk_on")
        self.assertEqual(regime["breadth_pct"], 80)
        self.assertEqual(regime["score"], 85)

    def test_daily_shortlists_are_intentionally_capped(self):
        candidates = [
            {"symbol": f"READY{i}", "action": "BUY_NOW", "score": 90 - i,
             "rank_value": 90 - i, "classification": "A"}
            for i in range(8)
        ] + [
            {"symbol": f"NEAR{i}", "action": "WAIT_FOR_ENTRY", "score": 70 - i,
             "rank_value": 70 - i, "classification": "Developing"}
            for i in range(12)
        ]
        market_pipeline._enforce_shortlist_caps(candidates)
        self.assertEqual(sum(row["action"] == "BUY_NOW" for row in candidates), 5)
        self.assertEqual(sum(row["action"] == "WAIT_FOR_ENTRY" for row in candidates), 10)
        self.assertTrue(any(row.get("shortlist_limiter") == "near_trigger_cap"
                            for row in candidates))

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

    def test_health_exposes_deployed_model_version(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model_version"], cfo_engine.MODEL_VERSION)

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

    def test_any_eligible_nse_stock_can_be_analysed_on_demand(self):
        history = candles()
        fundamentals = {
            "company_name": "Computer Age Management Services Limited",
            "sector": "Financial Services", "industry": "Capital Markets",
            "data_completeness": "full", "roe": 32,
            "annual_pl": [{"year": "2024", "net_profit": 300},
                          {"year": "2025", "net_profit": 380}],
        }
        with patch("routers.cfo_workspace.db.candidate_analysis", return_value=None), \
             patch("routers.cfo_workspace.symbol_resolver.resolve_one",
                   new=AsyncMock(return_value={"symbol": "CAMS", "name": fundamentals["company_name"]})), \
             patch("routers.cfo_workspace.price_service.get_historical",
                   new=AsyncMock(return_value=history)), \
             patch("routers.cfo_workspace.price_service.get_index_historical",
                   new=AsyncMock(return_value=history)), \
             patch("routers.cfo_workspace.data_cache.get_fundamentals",
                   new=AsyncMock(return_value=(fundamentals, {"source": "cache", "stale": False}))), \
             patch("routers.cfo_workspace.nse_bhavcopy.fetch_latest_bhavcopy",
                   new=AsyncMock(return_value={"as_of": history[-1]["date"],
                                               "closes": {"CAMS": history[-1]["close"]}})):
            response = self.client.get("/api/candidates/CAMS")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["symbol"], "CAMS")
        self.assertFalse(response.json()["universe_membership"]["ranked"])
        self.assertEqual(response.json()["sector"], "Financial Services")
        self.assertEqual(len(response.json()["daily_history"]), 252)

    def test_bull_ai_seed_is_source_labelled_and_score_neutral(self):
        evidence = db.candidate_enrichments("STOVEKRAFT")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["provider"], "Bull AI")
        self.assertEqual(evidence[0]["score_effect"], "none")
        self.assertTrue(evidence[0]["cards"][0]["sources"][0]["url"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
