"""Outcome-linked human experiments and model-error audits."""

from __future__ import annotations

import statistics

import db

ROUND_TRIP_COST_BPS = 35.0
COHORTS = (
    "model_accepted_human_accepted",
    "model_accepted_human_rejected",
    "model_rejected_human_accepted",
    "both_rejected",
)


def _net_r(row: dict) -> float | None:
    try:
        entry = float(row.get("entry_price") or 0)
        stop = float(row.get("stop_price") or 0)
        risk = entry - stop
        if entry <= 0 or risk <= 0:
            return None
        return float(row.get("pnl_r") or 0) - entry * ROUND_TRIP_COST_BPS / 10_000 / risk
    except (TypeError, ValueError):
        return None


def _summary(rows: list[dict]) -> dict:
    values = [value for row in rows if (value := _net_r(row)) is not None]
    if not values:
        return {"sample": 0, "net_expectancy_r": None, "win_rate_pct": None,
                "avg_mfe_r": None, "avg_mae_r": None}
    return {
        "sample": len(values),
        "net_expectancy_r": round(statistics.fmean(values), 3),
        "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 1),
        "avg_mfe_r": round(statistics.fmean(float(row.get("mfe_r") or 0)
                                             for row in rows), 2),
        "avg_mae_r": round(statistics.fmean(float(row.get("mae_r") or 0)
                                             for row in rows), 2),
    }


def _cohort(row: dict) -> str | None:
    if row.get("assessment") == "DATA_ISSUE":
        return None
    model_accepted = row.get("recommendation_action") in {"BUY_NOW", "WAIT_FOR_ENTRY"}
    if model_accepted:
        return ("model_accepted_human_rejected"
                if row.get("assessment") == "TOO_OPTIMISTIC"
                else "model_accepted_human_accepted")
    return ("model_rejected_human_accepted"
            if row.get("assessment") == "TOO_CONSERVATIVE"
            else "both_rejected")


def human_model_experiment() -> dict:
    source = db.human_reviews_with_resolved_outcomes()
    # An append-only review history may contain multiple judgments for one
    # snapshot. The newest judgment is the one measured, never all duplicates.
    latest = []
    seen = set()
    for row in source:
        key = (row.get("snapshot_id"), row.get("symbol"))
        if key in seen:
            continue
        seen.add(key)
        latest.append(row)
    grouped = {name: [] for name in COHORTS}
    excluded_data_issues = 0
    for row in latest:
        cohort = _cohort(row)
        if cohort is None:
            excluded_data_issues += 1
            continue
        grouped[cohort].append(row)
    return {
        "status": "reportable" if len(latest) >= 30 else "early",
        "linked_outcomes": len(latest),
        "excluded_data_issues": excluded_data_issues,
        "cohorts": {name: _summary(grouped[name]) for name in COHORTS},
        "cost_bps": ROUND_TRIP_COST_BPS,
        "training_use": "none_human_opinions_are_measurement_only",
    }


def _example(row: dict) -> dict:
    return {
        "symbol": row.get("symbol"), "action": row.get("action"),
        "rank": row.get("global_rank"), "status": row.get("status"),
        "signal_date": row.get("signal_date"),
        "net_pnl_r": round(_net_r(row), 3) if _net_r(row) is not None else None,
    }


def model_error_dashboard() -> dict:
    source = db.recommendation_outcomes_resolved(include_observational=True)
    rows = [row for row in source if _net_r(row) is not None]
    accepted = [row for row in rows if row.get("tracking_role") == "actionable"]
    rejected = [row for row in rows if row.get("tracking_role") == "observational"]
    false_positives = sorted(
        (row for row in accepted if _net_r(row) <= 0),
        key=lambda row: (row.get("global_rank") is None, row.get("global_rank") or 10_000),
    )
    false_negatives = sorted(
        (row for row in rejected if _net_r(row) > 0),
        key=lambda row: _net_r(row), reverse=True,
    )
    highest_ranked_losers = sorted(
        (row for row in rows if _net_r(row) <= 0),
        key=lambda row: (row.get("global_rank") is None, row.get("global_rank") or 10_000),
    )
    lowest_ranked_winners = sorted(
        (row for row in rows if _net_r(row) > 0),
        key=lambda row: row.get("global_rank") or 0, reverse=True,
    )
    return {
        "status": "reportable" if len(rows) >= 30 else "early",
        "resolved_sample": len(rows),
        "false_positives": {"count": len(false_positives),
                            "examples": [_example(row) for row in false_positives[:10]]},
        "false_negatives": {"count": len(false_negatives),
                            "examples": [_example(row) for row in false_negatives[:10]]},
        "highest_ranked_losers": [_example(row) for row in highest_ranked_losers[:10]],
        "lowest_ranked_winners": [_example(row) for row in lowest_ranked_winners[:10]],
        "missed_opportunities": {
            "status": "unavailable",
            "reason": "Names outside the frozen Top 100 were not outcome-tracked.",
        },
        "definitions": {
            "false_positive": "Actionable recommendation with non-positive net R after 35 bps.",
            "false_negative": "Observationally rejected recommendation with positive net R after 35 bps.",
        },
    }
