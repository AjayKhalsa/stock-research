"""Evidence-gated deterministic V2 calibration with chronological holdout."""

from __future__ import annotations

import hashlib
import math
import statistics
from typing import Optional

import cfo_engine
import db

MIN_CALIBRATION_SAMPLE = 100
MIN_TRAIN_SELECTION = 20
MIN_HOLDOUT_SELECTION = 10
HOLDOUT_SHARE = 0.30
ROUND_TRIP_COST_BPS = 35.0


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values()) or 1.0
    return {key: round(value / total, 6) for key, value in weights.items()}


def _candidate_configs() -> list[dict]:
    base = dict(cfo_engine.SCORE_WEIGHTS)
    weight_sets = [("baseline", _normalize(base))]
    for feature in base:
        for multiplier in (0.8, 1.2):
            changed = dict(base)
            changed[feature] *= multiplier
            weight_sets.append((f"{feature}_{multiplier:.1f}x", _normalize(changed)))
    configs = []
    for name, weights in weight_sets:
        for wait_threshold in (60, 64, 68, 72):
            for penalty_strength in (0.75, 1.0, 1.25):
                configs.append({
                    "name": name,
                    "weights": weights,
                    "wait_threshold": wait_threshold,
                    "buy_threshold": wait_threshold + 4,
                    "penalty_strength": penalty_strength,
                })
    return configs


def _net_r(row: dict) -> Optional[float]:
    try:
        entry = float(row.get("entry_price") or 0)
        stop = float(row.get("stop_price") or 0)
        risk = entry - stop
        if entry <= 0 or risk <= 0:
            return None
        return float(row.get("pnl_r") or 0) - entry * ROUND_TRIP_COST_BPS / 10_000 / risk
    except (TypeError, ValueError):
        return None


def _prepared(rows: list[dict]) -> list[dict]:
    prepared = []
    required = set(cfo_engine.SCORE_WEIGHTS)
    for row in rows:
        candidate = row.get("candidate") or {}
        components = candidate.get("components") or {}
        if not required.issubset(components):
            continue
        try:
            numeric = {key: float(components[key]) for key in required}
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in numeric.values()):
            continue
        net_r = _net_r(row)
        if net_r is None:
            continue
        plan = candidate.get("trade_plan") or {}
        prepared.append({
            **row,
            "components": numeric,
            "penalties": candidate.get("penalties") or [],
            "hard_blocks": candidate.get("hard_blocks") or [],
            "entry_state": plan.get("entry_state") or "unknown",
            "actionable_data": candidate.get("action") != "DATA_INSUFFICIENT",
            "supported_verdict": plan.get("verdict") in {"Buy", "Buy on Dip", "Wait"},
            "risk_reward": plan.get("risk_reward"),
            "setup_type": candidate.get("setup_type") or row.get("setup_type"),
            "net_r": net_r,
        })
    return prepared


def _score(row: dict, config: dict) -> float:
    score = sum(row["components"][key] * weight
                for key, weight in config["weights"].items())
    strength = config["penalty_strength"]
    for penalty in row["penalties"]:
        try:
            multiplier = float(penalty.get("multiplier"))
        except (TypeError, ValueError, AttributeError):
            continue
        adjusted = 1 - (1 - multiplier) * strength
        score *= max(0.5, min(1.0, adjusted))
    return score


def _selected(row: dict, config: dict) -> bool:
    try:
        reward_risk = float(row["risk_reward"])
    except (TypeError, ValueError):
        return False
    if (row["hard_blocks"] or not row["actionable_data"]
            or not row["supported_verdict"] or reward_risk < 1.5
            or row["setup_type"] in {None, "", "none"}):
        return False
    state = row["entry_state"]
    # Production emits WAIT_FOR_ENTRY from 68 for both near and in-zone ideas;
    # 72 only distinguishes BUY_NOW while already in-zone. Calibration targets
    # whether an idea should be selected, so both states use the wait threshold.
    return state in {"in_zone", "near"} and _score(row, config) >= config["wait_threshold"]


def _metrics(rows: list[dict], config: dict) -> dict:
    selected = [row for row in rows if _selected(row, config)]
    values = [row["net_r"] for row in selected]
    if not values:
        return {"sample": 0, "net_expectancy_r": 0.0, "net_total_r": 0.0,
                "wins": 0, "win_rate_pct": 0.0, "objective": -1_000_000.0}
    wins = sum(value > 0 for value in values)
    expectancy = statistics.fmean(values)
    # Rewards expectancy while penalizing configurations supported by only a
    # handful of examples. It is used only for training-set ordering.
    objective = expectancy * math.sqrt(len(values))
    return {
        "sample": len(values), "net_expectancy_r": round(expectancy, 3),
        "net_total_r": round(sum(values), 2), "wins": wins,
        "win_rate_pct": round(wins / len(values) * 100, 1),
        "objective": round(objective, 4),
    }


def _gate_audit(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        for block in row["hard_blocks"]:
            label = str(block).split(":", 1)[0]
            grouped.setdefault(label, []).append(row["net_r"])
    return [
        {"gate": gate, "sample": len(values),
         "counterfactual_expectancy_r": round(statistics.fmean(values), 3)}
        for gate, values in sorted(grouped.items())
    ]


def build_v2_shadow(*, model_version: Optional[str] = None,
                    persist: bool = True) -> dict:
    source = db.recommendation_outcomes_for_calibration(model_version)
    rows = _prepared(source)
    base = {
        "method": "chronological_rule_grid_with_holdout",
        "production_model": model_version or "all_versions",
        "minimum_sample": MIN_CALIBRATION_SAMPLE,
        "usable_sample": len(rows),
        "remaining": max(0, MIN_CALIBRATION_SAMPLE - len(rows)),
        "automatic_promotion": False,
        "cost_bps": ROUND_TRIP_COST_BPS,
    }
    if len(rows) < MIN_CALIBRATION_SAMPLE:
        result = {**base, "status": "awaiting_evidence", "challenger": None,
                  "gate_audit": _gate_audit(rows)}
        if persist:
            db.set_setting("v2_shadow_calibration", result)
        return result

    holdout_size = max(MIN_HOLDOUT_SELECTION, math.ceil(len(rows) * HOLDOUT_SHARE))
    training, holdout = rows[:-holdout_size], rows[-holdout_size:]
    configs = _candidate_configs()
    baseline_config = next(config for config in configs
                           if config["name"] == "baseline"
                           and config["wait_threshold"] == 68
                           and config["penalty_strength"] == 1.0)
    eligible = []
    for config in configs:
        metrics = _metrics(training, config)
        if metrics["sample"] >= MIN_TRAIN_SELECTION:
            eligible.append((metrics["objective"], config, metrics))
    if not eligible:
        result = {
            **base, "status": "no_supported_challenger", "challenger": None,
            "split": {"training": len(training), "holdout": len(holdout)},
            "gate_audit": _gate_audit(rows),
        }
        if persist:
            db.set_setting("v2_shadow_calibration", result)
        return result

    _objective, challenger_config, training_metrics = max(
        eligible, key=lambda item: item[0]
    )
    baseline_holdout = _metrics(holdout, baseline_config)
    challenger_holdout = _metrics(holdout, challenger_config)
    supported = (
        challenger_config != baseline_config
        and challenger_holdout["sample"] >= MIN_HOLDOUT_SELECTION
        and challenger_holdout["net_expectancy_r"] > 0
        and challenger_holdout["net_expectancy_r"]
        > baseline_holdout["net_expectancy_r"]
    )
    signature = hashlib.sha256(repr(challenger_config).encode()).hexdigest()[:10]
    challenger = {
        "model_version": f"swing-v2-shadow-{signature}",
        "config": challenger_config,
        "training": training_metrics,
        "holdout": challenger_holdout,
        "baseline_holdout": baseline_holdout,
        "promotion_eligible": False,
    }
    result = {
        **base,
        "status": "shadow_candidate_ready" if supported else "holdout_not_improved",
        "challenger": challenger,
        "split": {"training": len(training), "holdout": len(holdout)},
        "gate_audit": _gate_audit(rows),
        "limitations": [
            "Hard gates are audited but never relaxed automatically.",
            "A shadow candidate must accumulate new forward outcomes before promotion review.",
        ],
    }
    if persist:
        db.set_setting("v2_shadow_calibration", result)
    return result
