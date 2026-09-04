"""Point-in-time validation over immutable, forward-observed recommendations."""

from __future__ import annotations

import hashlib
import math
import statistics
from collections import defaultdict
from typing import Optional

import db

MIN_MATURE_SAMPLE = 100
MIN_REPORTABLE_SAMPLE = 30
DEFAULT_COSTS = {
    "entry_slippage_bps": 10.0,
    "exit_slippage_bps": 10.0,
    "fees_and_taxes_bps": 15.0,
}


def _wilson_interval(wins: int, total: int) -> list[float]:
    if total <= 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    p = wins / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [round(max(0.0, centre - margin) * 100, 1),
            round(min(1.0, centre + margin) * 100, 1)]


def _maximum_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return round(drawdown, 2)


def _costed_rows(rows: list[dict], costs: dict[str, float]) -> list[dict]:
    total_bps = sum(costs.values())
    output = []
    for row in rows:
        entry = float(row.get("entry_price") or 0)
        stop = float(row.get("stop_price") or 0)
        risk = entry - stop
        if entry <= 0 or risk <= 0:
            continue
        gross_r = float(row.get("pnl_r") or 0)
        cost_r = entry * total_bps / 10_000 / risk
        output.append({
            **row, "gross_pnl_r": round(gross_r, 4),
            "cost_r": round(cost_r, 4),
            "net_pnl_r": round(gross_r - cost_r, 4),
            "rank_decile": (math.ceil(int(row["global_rank"]) / 10)
                            if row.get("global_rank") else None),
        })
    return output


def _summary(rows: list[dict]) -> dict:
    count = len(rows)
    if not count:
        return {"sample": 0, "status": "no_data", "wins": 0,
                "win_rate_pct": 0.0, "win_rate_95ci_pct": [0.0, 0.0],
                "gross_expectancy_r": 0.0, "net_expectancy_r": 0.0,
                "net_total_r": 0.0, "profit_factor": None,
                "max_drawdown_r": 0.0, "avg_mfe_r": 0.0, "avg_mae_r": 0.0,
                "median_holding_sessions": 0.0}
    net = [float(row["net_pnl_r"]) for row in rows]
    gross = [float(row["gross_pnl_r"]) for row in rows]
    wins = sum(value > 0 for value in net)
    gains = sum(value for value in net if value > 0)
    losses = -sum(value for value in net if value < 0)
    return {
        "sample": count,
        "status": "mature" if count >= MIN_MATURE_SAMPLE
                  else "reportable" if count >= MIN_REPORTABLE_SAMPLE else "early",
        "wins": wins,
        "win_rate_pct": round(wins / count * 100, 1),
        "win_rate_95ci_pct": _wilson_interval(wins, count),
        "gross_expectancy_r": round(statistics.fmean(gross), 3),
        "net_expectancy_r": round(statistics.fmean(net), 3),
        "net_total_r": round(sum(net), 2),
        "profit_factor": round(gains / losses, 2) if losses else None,
        "max_drawdown_r": _maximum_drawdown(net),
        "avg_mfe_r": round(statistics.fmean(float(row.get("mfe_r") or 0)
                                             for row in rows), 2),
        "avg_mae_r": round(statistics.fmean(float(row.get("mae_r") or 0)
                                             for row in rows), 2),
        "median_holding_sessions": round(statistics.median(
            int(row.get("active_sessions") or 0) for row in rows
        ), 1),
    }


def _grouped(rows: list[dict], field: str, fallback: str = "unknown") -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        value = row.get(field)
        label = str(value) if value not in (None, "") else fallback
        groups[label].append(row)
    return [{"group": label, **_summary(group_rows)}
            for label, group_rows in sorted(groups.items())]


def run_snapshot_backtest(*, model_version: Optional[str] = None,
                          costs: Optional[dict[str, float]] = None,
                          persist: bool = True) -> dict:
    """Aggregate only outcomes whose features/recommendations were frozen first."""
    unknown_costs = set(costs or {}) - set(DEFAULT_COSTS)
    if unknown_costs:
        raise ValueError(f"Unsupported cost inputs: {', '.join(sorted(unknown_costs))}")
    cost_model = {**DEFAULT_COSTS, **(costs or {})}
    for key, value in cost_model.items():
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0 or numeric > 100:
            raise ValueError(f"{key} must be between 0 and 100 basis points")
        cost_model[key] = numeric
    source = db.recommendation_outcomes_resolved(model_version)
    rows = _costed_rows(source, cost_model)
    signature_material = "|".join(
        f"{row['id']}:{row.get('status')}:{row.get('pnl_r')}:{row.get('outcome_date')}"
        for row in rows
    )
    report = {
        "method": "out_of_sample_snapshot_replay",
        "point_in_time": True,
        "source_signature": hashlib.sha256(signature_material.encode()).hexdigest(),
        "data_cutoff": max((row.get("outcome_date") or "" for row in rows), default=None),
        "overall": _summary(rows),
        "by_setup": _grouped(rows, "setup_type"),
        "by_market_regime": _grouped(rows, "market_regime"),
        "by_rank_decile": _grouped(rows, "rank_decile", "unranked"),
        "by_action": _grouped(rows, "action"),
        "cost_model": {**cost_model, "round_trip_bps": round(sum(cost_model.values()), 2)},
        "controls": {
            "recommendations": "immutable snapshot payloads only",
            "lookahead": "candles strictly after signal date",
            "universe": "the published Top 100 selection is frozen at each signal date",
            "survivorship": "prior selections are never rewritten using today's universe",
            "corporate_actions": "levels rescaled to the current adjusted-price basis",
            "execution": "entry-high fill; entry-bar conflicts excluded; later conflicts stop-first",
            "selection": "all BUY_NOW and WAIT_FOR_ENTRY rows with valid geometry",
        },
        "limitations": [
            "The ledger begins when immutable daily snapshots were enabled; no current fundamentals are backfilled into earlier dates.",
            "The full historical NSE constituent master was not archived, so delisted and non-selected names cannot be reconstructed.",
            "Daily OHLC cannot reveal intraday order, so ambiguous entry bars are excluded.",
            "This is research validation, not broker execution or a promise of future returns.",
        ],
    }
    status = ("no_data" if not rows else "complete"
              if report["overall"]["sample"] >= MIN_REPORTABLE_SAMPLE
              else "insufficient_data")
    report["status"] = status
    report["model_version_filter"] = model_version
    mature = report["overall"]["sample"] >= MIN_MATURE_SAMPLE
    report["shadow_test"] = {
        "current": {
            "model_version": model_version or "all_versions",
            "role": "production_champion",
            "sample": report["overall"]["sample"],
        },
        "challenger": {
            "model_version": None,
            "role": "v2_challenger",
            "status": "eligible_for_calibration" if mature else "awaiting_evidence",
        },
        "promotion_policy": {
            "automatic_promotion": False,
            "minimum_resolved_outcomes": MIN_MATURE_SAMPLE,
            "observed_resolved_outcomes": report["overall"]["sample"],
            "remaining": max(0, MIN_MATURE_SAMPLE - report["overall"]["sample"]),
            "next_step": (
                "calibrate V2 on chronological train data, then compare on a held-out period"
                if mature else "continue forward collection without changing live weights"
            ),
        },
    }
    if persist and rows:
        stored_version = model_version or "ALL"
        latest = db.latest_backtest_run(stored_version)
        if (latest and latest.get("source_signature") == report["source_signature"]
                and latest.get("cost_model") == report["cost_model"]):
            return {**latest, "reused": True}
        return db.backtest_run_add(stored_version, status, report)
    return report
