import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("STOCKLENS_DATA_DIR", tempfile.mkdtemp())

from fastapi.testclient import TestClient  # noqa: E402
import cfo_engine  # noqa: E402
import ai_committee  # noqa: E402
import backtest_engine  # noqa: E402
import data_cache  # noqa: E402
import db  # noqa: E402
import price_service  # noqa: E402
import market_pipeline  # noqa: E402
import nse_bhavcopy  # noqa: E402
import recommendation_outcome_service  # noqa: E402
import trade_lifecycle  # noqa: E402
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
    def test_point_in_time_backtest_applies_costs_and_segments_results(self):
        rows = [
            {"id": 1, "status": "WIN_T1", "outcome_date": "2026-05-10",
             "entry_price": 100, "stop_price": 95, "pnl_r": 2,
             "mfe_r": 2.2, "mae_r": .2, "active_sessions": 4,
             "global_rank": 3, "setup_type": "pullback",
             "market_regime": "risk_on", "market_cap_bucket": "large_proxy",
             "sector": "IT", "action": "BUY_NOW"},
            {"id": 2, "status": "STOPPED_OUT", "outcome_date": "2026-05-11",
             "entry_price": 50, "stop_price": 45, "pnl_r": -1,
             "mfe_r": .3, "mae_r": 1, "active_sessions": 2,
             "global_rank": 17, "setup_type": "breakout",
             "market_regime": "neutral", "market_cap_bucket": "mid_proxy",
             "sector": "Industrials", "action": "WAIT_FOR_ENTRY"},
        ]
        with patch("backtest_engine.db.recommendation_outcomes_resolved",
                   return_value=rows):
            result = backtest_engine.run_snapshot_backtest(persist=False)
        self.assertTrue(result["point_in_time"])
        self.assertEqual(result["overall"]["sample"], 2)
        self.assertLess(result["overall"]["net_expectancy_r"],
                        result["overall"]["gross_expectancy_r"])
        self.assertEqual({item["group"] for item in result["by_setup"]},
                         {"breakout", "pullback"})
        self.assertEqual({item["group"] for item in result["by_rank_decile"]},
                         {"1", "2"})
        self.assertEqual({item["group"] for item in result["by_sector"]},
                         {"IT", "Industrials"})
        self.assertEqual({item["group"] for item in result["by_market_cap_bucket"]},
                         {"large_proxy", "mid_proxy"})
        self.assertGreater(result["ranking_quality"]["top_minus_bottom_expectancy_r"], 0)
        self.assertIn("net_median_r", result["overall"])
        self.assertIn("net_volatility_r", result["overall"])
        self.assertEqual(result["overall"]["target_hit_rate_pct"], 50.0)
        self.assertEqual(result["overall"]["stop_hit_rate_pct"], 50.0)
        self.assertIsNone(result["portfolio_metrics"]["cagr_pct"])
        self.assertEqual(len(result["overall"]["win_rate_95ci_pct"]), 2)
        self.assertGreater(result["overall"]["max_drawdown_r"], 0)
        self.assertEqual(result["shadow_test"]["challenger"]["status"],
                         "awaiting_evidence")
        self.assertEqual(result["shadow_test"]["promotion_policy"]["remaining"], 98)

    def test_point_in_time_backtest_rejects_unknown_or_extreme_costs(self):
        with self.assertRaises(ValueError):
            backtest_engine.run_snapshot_backtest(
                costs={"mystery_bps": 1}, persist=False,
            )
        with self.assertRaises(ValueError):
            backtest_engine.run_snapshot_backtest(
                costs={"entry_slippage_bps": 101}, persist=False,
            )

    def test_daily_lifecycle_never_replays_candles_before_numeric_open_time(self):
        record = {
            "status": "ACTIVE", "opened_at": datetime(
                2026, 5, 1, tzinfo=timezone.utc,
            ).timestamp(),
            "entry_price": 100, "entry_low": 99, "entry_high": 101,
            "stop_price": 95, "target_t1": 108, "target_t2": 112,
        }
        result = trade_lifecycle.evaluate_daily(record, [
            {"date": "2026-04-30", "high": 101, "low": 90, "close": 94},
            {"date": "2026-05-04", "high": 109, "low": 99, "close": 108},
        ], now=1)
        self.assertEqual(result["status"], "WIN_T1")
        self.assertEqual(result["updates"]["active_sessions"], 1)

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
        self.assertEqual(result[0]["raw_close"], 100)
        self.assertEqual(result[0]["adjustment_factor"], 0.5)
        self.assertEqual(result[0]["volume"], 12345)

    def test_daily_lifecycle_rescales_levels_after_corporate_action(self):
        record = {
            "status": "ARMED", "signal_date": "2026-05-01",
            "signal_adjustment_factor": 1.0,
            "entry_price": 101, "entry_low": 100, "entry_high": 102,
            "stop_price": 95, "target_t1": 110, "target_t2": 118,
        }
        result = trade_lifecycle.evaluate_daily(record, [
            {"date": "2026-05-01", "high": 51, "low": 49, "close": 50,
             "adjustment_factor": 0.5},
            {"date": "2026-05-04", "high": 50.5, "low": 49.5, "close": 50,
             "adjustment_factor": 1.0},
            {"date": "2026-05-05", "high": 56, "low": 52, "close": 55,
             "adjustment_factor": 1.0},
        ], now=1)
        self.assertEqual(result["status"], "WIN_T1")
        self.assertEqual(result["updates"]["level_adjustment_factor"], 0.5)
        self.assertEqual(result["updates"]["exit_price"], 55.0)

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
        self.assertEqual(cfo_engine.market_cap_bucket(50_000), "large_proxy")
        self.assertEqual(cfo_engine.market_cap_bucket(10_000), "mid_proxy")
        self.assertEqual(cfo_engine.market_cap_bucket(2_000), "small_proxy")
        self.assertEqual(cfo_engine.market_cap_bucket(None), "unknown")

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

    def test_event_risk_distinguishes_unknown_upcoming_and_blocked(self):
        unknown = cfo_engine.assess_event_risk({}, "2026-09-01")
        self.assertEqual(unknown["level"], "unknown")
        self.assertEqual(unknown["coverage"], "unverified")
        imminent = cfo_engine.assess_event_risk(
            {"earnings_date": "2026-09-03"}, "2026-09-01",
        )
        self.assertEqual(imminent["level"], "high")
        self.assertTrue(imminent["entry_blocked"])
        later = cfo_engine.assess_event_risk(
            {"earnings_date": "2026-09-25"}, "2026-09-01",
        )
        self.assertEqual(later["level"], "low")
        self.assertFalse(later["entry_blocked"])

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

    def test_daily_pipeline_excludes_in_progress_bar_after_official_close(self):
        history = [
            {"date": "2026-09-03", "close": 100},
            {"date": "2026-09-04", "close": 105},
        ]
        self.assertEqual(
            market_pipeline._completed_history(history, "2026-09-03"),
            [history[0]],
        )
        self.assertEqual(market_pipeline._completed_history(history, None), history)

    def test_official_bhavcopy_bar_fills_one_session_provider_lag(self):
        csv_body = (
            "SYMBOL,SERIES,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,CLOSE_PRICE,TTL_TRD_QNTY\n"
            "TCS,EQ,101,104,100,103,250000\n"
        ).encode()
        parsed = nse_bhavcopy._parse_market(csv_body)
        self.assertEqual(parsed["closes"]["TCS"], 103)
        self.assertEqual(parsed["bars"]["TCS"]["volume"], 250000)
        history = [{"date": "2026-09-03", "close": 100}]
        aligned = market_pipeline._align_completed_history(
            history, "2026-09-04", parsed["bars"]["TCS"],
        )
        self.assertEqual(aligned[-1]["date"], "2026-09-04")
        self.assertEqual(aligned[-1]["source"], "NSE bhavcopy")

    def test_official_bar_does_not_bridge_missing_sessions_or_split_gap(self):
        history = [{"date": "2026-09-01", "close": 100}]
        bar = {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}
        self.assertEqual(
            market_pipeline._align_completed_history(history, "2026-09-04", bar),
            history,
        )
        split_bar = {**bar, "close": 50}
        self.assertEqual(
            market_pipeline._align_completed_history(
                [{"date": "2026-09-03", "close": 100}], "2026-09-04", split_bar,
            ),
            [{"date": "2026-09-03", "close": 100}],
        )

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

    def test_backtest_endpoints_expose_point_in_time_report_and_validate_costs(self):
        report = backtest_engine.run_snapshot_backtest(persist=False)
        with patch("routers.cfo_workspace.db.latest_backtest_run", return_value=None), \
             patch("routers.cfo_workspace.backtest_engine.run_snapshot_backtest",
                   return_value=report):
            response = self.client.get("/api/backtests/latest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["method"], "out_of_sample_snapshot_replay")
        invalid = self.client.post("/api/backtests/run", json={
            "entry_slippage_bps": 101,
            "exit_slippage_bps": 10,
            "fees_and_taxes_bps": 15,
        })
        self.assertEqual(invalid.status_code, 422)

    def test_shadow_model_endpoint_exposes_evidence_gate(self):
        report = {
            "status": "awaiting_evidence", "production_model": "test-v1",
            "usable_sample": 25, "remaining": 75,
            "automatic_promotion": False, "challenger": None,
        }
        with patch("routers.cfo_workspace.db.get_setting", return_value=None), \
             patch("routers.cfo_workspace.db.latest_analysis_snapshot",
                   return_value={"model_version": "test-v1"}), \
             patch("routers.cfo_workspace.calibration_engine.build_v2_shadow",
                   return_value=report) as build:
            response = self.client.get("/api/shadow-model")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), report)
        build.assert_called_once_with(model_version="test-v1", persist=False)

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
        review = self.client.post("/api/human-reviews", json={
            "snapshot_id": snapshot_id, "symbol": "TCS",
            "assessment": "TOO_OPTIMISTIC",
            "tags": ["HEAVY_SUPPLY", "NON_LINEAR"],
            "notes": "Supply above the entry looks heavier than the score suggests",
        })
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()["model_version"], "test-v1")
        self.assertEqual(review.json()["recommendation_action"], "WATCH")
        self.assertEqual(review.json()["score_at_review"], 70.0)
        self.assertEqual(review.json()["tags"], ["HEAVY_SUPPLY", "NON_LINEAR"])
        morning = self.client.get("/api/morning-brief")
        self.assertEqual(morning.status_code, 200)
        self.assertEqual(morning.json()["snapshot_id"], snapshot_id)
        with patch("routers.cfo_workspace.price_service.get_historical",
                   new=AsyncMock(return_value=candles(8))):
            detail = self.client.get("/api/candidates/TCS")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["snapshot_id"], snapshot_id)
        self.assertNotIn("position_size", detail.json())
        self.assertEqual(len(detail.json()["daily_history"]), 8)
        self.assertIn("trust", detail.json())
        self.assertIn("external_research", detail.json())
        self.assertEqual(detail.json()["human_reviews"][0]["assessment"], "TOO_OPTIMISTIC")
        self.assertEqual(detail.json()["human_reviews"][0]["tags"],
                         ["HEAVY_SUPPLY", "NON_LINEAR"])
        self.assertGreaterEqual(morning.json()["external_enrichment"]["covered"], 3)
        self.assertEqual(self.client.get("/api/sectors/IT").status_code, 200)
        history = self.client.get(
            "/api/human-reviews/TCS", params={"snapshot_id": snapshot_id},
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()[0]["snapshot_id"], snapshot_id)

    def test_actionable_snapshot_creates_and_resolves_automatic_outcome(self):
        candidate = {
            "symbol": "AUTOTEST", "company": "Automatic Test", "sector": "IT",
            "global_rank": 2, "sector_rank": 2, "action": "WAIT_FOR_ENTRY",
            "classification": "B", "score": 74, "confidence": 80,
            "market_cap_cr": 25_000, "market_cap_bucket": "large_proxy",
            "setup_type": "pullback", "trade_plan": {
                "entry": {"low": 100, "high": 102}, "stop": {"price": 95},
                "targets": [{"label": "T1", "price": 110},
                            {"label": "T2", "price": 118}],
                "invalidation": "Close below 95",
            },
        }
        snapshot_id = db.publish_analysis_snapshot(
            {"candidates": [candidate], "sectors": []}, [candidate], [],
            model_version="outcome-test-v1", trading_date="2026-05-01",
        )
        row = next(item for item in db.recommendation_outcomes_open()
                   if item["snapshot_id"] == snapshot_id)
        self.assertEqual(row["status"], "ARMED")
        self.assertEqual(row["model_version"], "outcome-test-v1")
        self.assertEqual(row["tracking_role"], "actionable")
        self.assertEqual(row["market_cap_cr"], 25_000)
        self.assertEqual(row["market_cap_bucket"], "large_proxy")

        evaluated = asyncio.run(
            recommendation_outcome_service.evaluate_open_outcomes({
                "AUTOTEST": [
                    {"date": "2026-05-04", "high": 101, "low": 99, "close": 100},
                    {"date": "2026-05-05", "high": 111, "low": 103, "close": 109},
                ],
            })
        )
        result = next(item for item in evaluated["results"]
                      if item["snapshot_id"] == snapshot_id)
        self.assertEqual(result["status"], "WIN_T1")
        self.assertEqual(result["outcome"]["pnl_r"], 1.14)
        self.assertEqual(result["outcome"]["mfe_r"], 1.29)
        self.assertEqual(evaluated["provider_requests"], 0)
        stats = self.client.get("/api/recommendation-outcomes/stats").json()
        self.assertGreaterEqual(stats["resolved"], 1)
        self.assertIn("expectancy_r", stats)
        history = self.client.get("/api/recommendation-outcomes", params={"limit": 10})
        self.assertEqual(history.status_code, 200)
        self.assertTrue(any(item["snapshot_id"] == snapshot_id for item in history.json()))

    def test_watch_outcome_is_observational_and_does_not_change_live_scorecard(self):
        candidate = {
            "symbol": "SHADOWTEST", "company": "Shadow Test", "sector": "IT",
            "global_rank": 8, "sector_rank": 3, "action": "WATCH",
            "score": 66, "setup_type": "breakout", "trade_plan": {
                "entry": {"low": 100, "high": 102}, "stop": {"price": 95},
                "targets": [{"price": 110}, {"price": 118}],
            },
        }
        before = db.recommendation_outcome_stats()
        snapshot_id = db.publish_analysis_snapshot(
            {"candidates": [candidate], "sectors": []}, [candidate], [],
            model_version="shadow-test-v1", trading_date="2026-06-01",
        )
        row = next(item for item in db.recommendation_outcomes_open()
                   if item["snapshot_id"] == snapshot_id)
        after = db.recommendation_outcome_stats()
        self.assertEqual(row["tracking_role"], "observational")
        self.assertEqual(after["total"], before["total"])
        self.assertEqual(after["observational"], before["observational"] + 1)

        second_snapshot = db.publish_analysis_snapshot(
            {"candidates": [candidate], "sectors": []}, [candidate], [],
            model_version="shadow-test-v1", trading_date="2026-06-01",
        )
        matching = [item for item in db.recommendation_outcomes_recent(500)
                    if item["symbol"] == "SHADOWTEST"
                    and item["model_version"] == "shadow-test-v1"]
        self.assertNotEqual(second_snapshot, snapshot_id)
        self.assertEqual(len(matching), 1)

    def test_human_review_rejects_unknown_recommendation_snapshot(self):
        response = self.client.post("/api/human-reviews", json={
            "snapshot_id": "missing-snapshot", "symbol": "TCS",
            "assessment": "AGREE", "notes": "",
        })
        self.assertEqual(response.status_code, 404)

    def test_human_experiment_and_model_error_endpoints_are_not_symbol_routes(self):
        experiment = {"status": "early", "linked_outcomes": 0, "cohorts": {}}
        errors = {"status": "early", "resolved_sample": 0}
        with patch("routers.cfo_workspace.evaluation_engine.human_model_experiment",
                   return_value=experiment), \
             patch("routers.cfo_workspace.evaluation_engine.model_error_dashboard",
                   return_value=errors):
            experiment_response = self.client.get("/api/human-reviews/experiments")
            errors_response = self.client.get("/api/model-errors")
        self.assertEqual(experiment_response.status_code, 200)
        self.assertEqual(experiment_response.json(), experiment)
        self.assertEqual(errors_response.status_code, 200)
        self.assertEqual(errors_response.json(), errors)

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
