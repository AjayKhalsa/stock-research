"""Bounded AI risk-committee adapter.

The model receives saved calculations and can only preserve or lower the
deterministic action.  Its prose and downgrade are stored in the audit ledger;
the numeric score, levels, hard gates, and portfolio rules remain untouched.
"""

from __future__ import annotations

import ai_engine
import decision_engine
import quant_engine

_PRIORITY = {"AVOID": 0, "DATA_INSUFFICIENT": 1, "WATCH": 2,
             "WAIT_FOR_ENTRY": 3, "BUY_NOW": 4}


def _lower(current: str, proposed: str) -> str:
    return proposed if _PRIORITY.get(proposed, 0) < _PRIORITY.get(current, 0) else current


async def review(candidate: dict, fundamentals: dict) -> dict:
    quant = quant_engine.compute_all(fundamentals) if fundamentals else {}
    compact_plans = {
        "price": candidate.get("price"),
        "swing": {
            "verdict": candidate.get("action"), "setup_label": candidate.get("setup_label"),
            **(candidate.get("trade_plan") or {}),
        },
    }
    response = await ai_engine.generate_alpha_thesis(
        candidate["symbol"], fundamentals, quant, {"items": []}, compact_plans,
    )
    if response.get("error"):
        return {"status": "unavailable", "authority": "downgrade_only",
                "error": response.get("error"), "original_action": candidate["action"],
                "final_action": candidate["action"]}

    final_action = candidate["action"]
    score = response.get("conviction_score")
    suggested = str(response.get("suggested_action") or "").lower()
    if score is not None and score < 30 or any(term in suggested for term in ("avoid", "reduce", "sell")):
        final_action = _lower(final_action, "AVOID")
    elif score is not None and score < 48:
        final_action = _lower(final_action, "WATCH")
    elif score is not None and score < 62:
        final_action = _lower(final_action, "WAIT_FOR_ENTRY")

    return {
        "status": "completed", "authority": "downgrade_only",
        "original_action": candidate["action"], "final_action": final_action,
        "conviction_score": score, "summary": response.get("thesis_summary"),
        "bear_case": response.get("bear_case"),
        "ledger": response.get("bear_case_ledger") or [],
        "data_confidence": response.get("data_confidence"),
    }
