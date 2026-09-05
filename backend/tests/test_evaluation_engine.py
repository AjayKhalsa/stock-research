import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("STOCKLENS_DATA_DIR", tempfile.mkdtemp())

import evaluation_engine  # noqa: E402


def outcome(**changes):
    row = {
        "snapshot_id": "snapshot-1", "symbol": "TEST",
        "recommendation_action": "BUY_NOW", "action": "BUY_NOW",
        "assessment": "AGREE", "entry_price": 100, "stop_price": 95,
        "pnl_r": 1, "mfe_r": 1.4, "mae_r": .4,
        "status": "WIN_T1", "tracking_role": "actionable",
        "global_rank": 5, "signal_date": "2026-05-01",
    }
    return {**row, **changes}


class EvaluationEngineTests(unittest.TestCase):
    def test_human_model_experiment_uses_latest_review_and_four_cohorts(self):
        rows = [
            outcome(snapshot_id="a", symbol="A", assessment="TOO_OPTIMISTIC",
                    pnl_r=-1, status="STOPPED_OUT"),
            # Older duplicate judgment for A must not inflate the sample.
            outcome(snapshot_id="a", symbol="A", assessment="AGREE"),
            outcome(snapshot_id="b", symbol="B", assessment="AGREE"),
            outcome(snapshot_id="c", symbol="C", recommendation_action="WATCH",
                    assessment="TOO_CONSERVATIVE", tracking_role="observational"),
            outcome(snapshot_id="d", symbol="D", recommendation_action="AVOID",
                    assessment="AGREE", tracking_role="observational", pnl_r=-1),
            outcome(snapshot_id="e", symbol="E", assessment="DATA_ISSUE"),
        ]
        with patch("evaluation_engine.db.human_reviews_with_resolved_outcomes",
                   return_value=rows):
            result = evaluation_engine.human_model_experiment()
        self.assertEqual(result["linked_outcomes"], 5)
        self.assertEqual(result["excluded_data_issues"], 1)
        self.assertEqual(
            {name: metrics["sample"] for name, metrics in result["cohorts"].items()},
            {
                "model_accepted_human_accepted": 1,
                "model_accepted_human_rejected": 1,
                "model_rejected_human_accepted": 1,
                "both_rejected": 1,
            },
        )
        self.assertEqual(result["training_use"], "none_human_opinions_are_measurement_only")

    def test_model_error_dashboard_separates_observed_false_negatives(self):
        rows = [
            outcome(symbol="TOPLOSS", pnl_r=-1, status="STOPPED_OUT", global_rank=2),
            outcome(symbol="MODELWIN", pnl_r=2, global_rank=5),
            outcome(symbol="MISSEDWIN", action="WATCH", tracking_role="observational",
                    pnl_r=2.5, global_rank=90),
            outcome(symbol="LOWLOSS", action="AVOID", tracking_role="observational",
                    pnl_r=-1, status="STOPPED_OUT", global_rank=95),
        ]
        with patch("evaluation_engine.db.recommendation_outcomes_resolved",
                   return_value=rows) as resolved:
            result = evaluation_engine.model_error_dashboard()
        resolved.assert_called_once_with(include_observational=True)
        self.assertEqual(result["false_positives"]["count"], 1)
        self.assertEqual(result["false_negatives"]["count"], 1)
        self.assertEqual(result["false_positives"]["examples"][0]["symbol"], "TOPLOSS")
        self.assertEqual(result["false_negatives"]["examples"][0]["symbol"], "MISSEDWIN")
        self.assertEqual(result["highest_ranked_losers"][0]["symbol"], "TOPLOSS")
        self.assertEqual(result["lowest_ranked_winners"][0]["symbol"], "MISSEDWIN")
        self.assertEqual(result["missed_opportunities"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
