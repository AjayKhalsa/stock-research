import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("STOCKLENS_DATA_DIR", tempfile.mkdtemp())

import calibration_engine  # noqa: E402
import cfo_engine  # noqa: E402


def resolved_rows(count: int, *, training_pnl: float = 2.0,
                  holdout_pnl: float = -1.0) -> list[dict]:
    rows = []
    training_cutoff = count - max(10, int(count * .30 + .999))
    for index in range(count):
        pnl_r = training_pnl if index < training_cutoff else holdout_pnl
        rows.append({
            "id": index + 1,
            "outcome_date": f"2026-{index // 28 + 1:02d}-{index % 28 + 1:02d}",
            "entry_price": 100,
            "stop_price": 95,
            "pnl_r": pnl_r,
            "setup_type": "pullback",
            "candidate": {
                "action": "WATCH",
                "setup_type": "pullback",
                "components": {key: 75 for key in cfo_engine.SCORE_WEIGHTS},
                "penalties": [],
                "hard_blocks": [],
                "trade_plan": {
                    "entry_state": "near",
                    "verdict": "Wait",
                    "risk_reward": 2.0,
                },
            },
        })
    return rows


class CalibrationEngineTests(unittest.TestCase):
    def test_waits_for_pre_registered_sample_and_never_auto_promotes(self):
        with patch(
            "calibration_engine.db.recommendation_outcomes_for_calibration",
            return_value=resolved_rows(25),
        ):
            result = calibration_engine.build_v2_shadow(
                model_version="test-v1", persist=False,
            )
        self.assertEqual(result["status"], "awaiting_evidence")
        self.assertEqual(result["usable_sample"], 25)
        self.assertEqual(result["remaining"], 75)
        self.assertFalse(result["automatic_promotion"])
        self.assertIsNone(result["challenger"])

    def test_uses_older_training_and_newest_chronological_holdout(self):
        with patch(
            "calibration_engine.db.recommendation_outcomes_for_calibration",
            return_value=resolved_rows(100),
        ):
            result = calibration_engine.build_v2_shadow(
                model_version="test-v1", persist=False,
            )
        self.assertEqual(result["split"], {"training": 70, "holdout": 30})
        self.assertGreater(result["challenger"]["training"]["net_expectancy_r"], 0)
        self.assertLess(result["challenger"]["holdout"]["net_expectancy_r"], 0)
        self.assertEqual(result["status"], "holdout_not_improved")
        self.assertFalse(result["challenger"]["promotion_eligible"])

    def test_grid_is_bounded_and_preserves_live_safety_eligibility(self):
        configs = calibration_engine._candidate_configs()
        self.assertTrue(configs)
        for config in configs:
            self.assertAlmostEqual(sum(config["weights"].values()), 1.0, places=5)
            self.assertIn(config["wait_threshold"], {60, 64, 68, 72})
            self.assertEqual(config["buy_threshold"], config["wait_threshold"] + 4)
            self.assertIn(config["penalty_strength"], {.75, 1.0, 1.25})

        row = calibration_engine._prepared(resolved_rows(1))[0]
        baseline = next(
            item for item in configs
            if item["name"] == "baseline"
            and item["wait_threshold"] == 68
            and item["penalty_strength"] == 1.0
        )
        self.assertTrue(calibration_engine._selected(row, baseline))
        for safety_change in (
            {"hard_blocks": ["Required safety check failed"]},
            {"actionable_data": False},
            {"supported_verdict": False},
            {"risk_reward": 1.49},
        ):
            self.assertFalse(calibration_engine._selected({**row, **safety_change}, baseline))


if __name__ == "__main__":
    unittest.main()
