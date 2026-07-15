"""
ai_engine.py
Gemini API orchestration for generating structured alpha thesis.

Uses direct REST calls via httpx — no google-generativeai SDK needed.
Set the GEMINI_API_KEY environment variable before starting the server.

Model : gemini-2.5-flash  (default; override with GEMINI_MODEL env var)
"""

from __future__ import annotations
import os
import json
import re
import asyncio
import httpx
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────

GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL:   str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

def _gemini_url() -> str:
    """Build URL at call time so GEMINI_MODEL overrides are respected."""
    model = os.environ.get("GEMINI_MODEL", GEMINI_MODEL)
    return (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an elite quantitative equity analyst with 20 years of experience in \
Indian capital markets (NSE / BSE). You combine rigorous fundamental analysis, \
quantitative factor models, and keen awareness of Indian regulatory, macro, \
and sectoral dynamics.

Your analysis is contrarian when the data warrants it, brutally honest about \
hidden risks, and always grounded in numbers rather than narratives.

You surface non-obvious risks that consensus sell-side analysts miss — \
promoter behaviour, off-balance-sheet exposures, working-capital traps, \
sector-specific landmines.

You output ONLY valid JSON — no markdown fences, no prose outside the JSON \
object. Every field in the schema must be present.\
"""

# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(
    ticker:        str,
    company_name:  str,
    raw:           dict,
    quant_scores:  dict,
    sentiment:     dict,
    trade_plans:   Optional[dict] = None,
) -> str:
    """Assemble the rich analysis prompt from all data layers."""

    # ── Key ratios block ──────────────────────────────────────────────────────
    fins = {
        "market_cap":        raw.get("market_cap"),
        "pe_ratio":          raw.get("pe_ratio"),
        "pb_ratio":          raw.get("pb_ratio"),
        "roe_pct":           raw.get("roe"),
        "roce_pct":          raw.get("roce"),
        "debt_to_equity":    raw.get("debt_to_equity"),
        "dividend_yield_pct":raw.get("dividend_yield"),
        "book_value":        raw.get("book_value"),
        "promoter_holding_pct": raw.get("shareholding", {}).get("promoter"),
        "promoter_pledge_pct":  raw.get("shareholding", {}).get("promoter_pledge"),
        "fii_holding_pct":      raw.get("shareholding", {}).get("fii"),
        "dii_holding_pct":      raw.get("shareholding", {}).get("dii"),
        "fii_change_pct_pts":   (
            round(
                (raw.get("shareholding", {}).get("fii") or 0)
                - (raw.get("shareholding", {}).get("fii_prev") or 0),
                2,
            )
            if raw.get("shareholding", {}).get("fii") is not None
               and raw.get("shareholding", {}).get("fii_prev") is not None
            else None
        ),
    }

    # ── Quarterly trend (last 4Q, chronological) ──────────────────────────────
    qtrs = raw.get("quarterly_results", [])[-4:]
    q_trend = [
        {"q": q.get("quarter"), "rev_cr": q.get("revenue"),
         "pat_cr": q.get("net_profit"), "ebitda_cr": q.get("ebitda")}
        for q in qtrs
    ]

    # ── Annual trend (last 3 years, chronological) ────────────────────────────
    a_trend = [
        {"yr": a.get("year"), "rev_cr": a.get("revenue"),
         "pat_cr": a.get("net_profit"), "ebitda_cr": a.get("ebitda")}
        for a in raw.get("annual_pl", [])[-3:]
    ]

    # ── Annual cash flow ──────────────────────────────────────────────────────
    cf_trend = [
        {"yr": c.get("year"), "cfo": c.get("cfo"),
         "cfi": c.get("cfi"), "cff": c.get("cff")}
        for c in raw.get("annual_cf", [])[-3:]
    ]

    # ── Quant summary ─────────────────────────────────────────────────────────
    p = quant_scores.get("piotroski", {})
    a = quant_scores.get("altman",    {})
    d = quant_scores.get("dupont",    {})

    quant_block = {
        "piotroski_score":      f"{p.get('score')}/9 — {p.get('interpretation')}",
        "piotroski_signals":    {
            k: v.get("score") for k, v in p.get("signals", {}).items()
        },
        "altman_z":             a.get("z_score"),
        "altman_zone":          a.get("zone"),
        "altman_interpretation":a.get("interpretation"),
        "dupont_npm_pct":       d.get("net_profit_margin_pct"),
        "dupont_asset_turnover":d.get("asset_turnover"),
        "dupont_eq_multiplier": d.get("equity_multiplier"),
        "dupont_roe_driver":    d.get("primary_roe_driver"),
        "composite_quality":    f"{quant_scores.get('composite_quality_score')}/100",
    }

    # ── Sentiment summary ─────────────────────────────────────────────────────
    top_headlines = [
        item.get("title") or item.get("headline", "")
        for item in sentiment.get("items", [])[:8]
        if item.get("title") or item.get("headline")
    ]
    sentiment_block = {
        "composite_score":  sentiment.get("composite_score"),
        "label":            sentiment.get("composite_label"),
        "positive_count":   sentiment.get("positive"),
        "negative_count":   sentiment.get("negative"),
        "red_flag_count":   sentiment.get("red_flags"),
        "recent_headlines": top_headlines,
    }

    # ── Computed trade plans (compact: verdicts + levels only) ────────────────
    plans_block = None
    if trade_plans and "error" not in trade_plans:
        def _plan_brief(p: dict) -> dict:
            if not p:
                return {}
            return {
                "verdict":      p.get("verdict"),
                "setup":        p.get("setup_label"),
                "entry_zone":   p.get("entry"),
                "stop":         (p.get("stop") or {}).get("price"),
                "targets":      [{t.get("label"): t.get("price")} for t in p.get("targets", [])],
                "risk_reward":  p.get("risk_reward"),
                "confidence":   p.get("confidence"),
            }
        plans_block = {
            "price":      trade_plans.get("price"),
            "swing":      _plan_brief(trade_plans.get("swing")),
            "positional": _plan_brief(trade_plans.get("positional")),
        }
        dossier = trade_plans.get("dossier")
        if dossier:
            case = dossier.get("case", {})
            pa_sig = dossier.get("price_action") or {}
            plans_block["evidence"] = {
                "price_action": {
                    "market_structure": (pa_sig.get("structure") or {}).get("state"),
                    "obv": (pa_sig.get("obv") or {}).get("state"),
                    "distribution_days_25d": pa_sig.get("distribution_days"),
                    "up_down_volume_ratio_50d": pa_sig.get("up_down_volume_ratio"),
                    "recent_pocket_pivots": len(pa_sig.get("pocket_pivots") or []),
                    "pullback_volume": (pa_sig.get("pullback_volume") or {}).get("state"),
                },
                "market_regime":   (dossier.get("regime") or {}).get("label"),
                "regime_guidance": (dossier.get("regime") or {}).get("guidance"),
                "relative_strength": (dossier.get("relative_strength") or {}).get("label"),
                "trend_template":  f"{(dossier.get('trend_template') or {}).get('score')}"
                                   f"/{(dossier.get('trend_template') or {}).get('max_score')}",
                "setup_base_rates": (dossier.get("base_rates") or {}).get("note"),
                "conviction":      case.get("conviction"),
                "final_call":      case.get("final_call"),
                "top_evidence":    [f"[{e['side']}] {e['text']}"
                                    for e in case.get("ledger", [])[:6]],
            }

    prompt = f"""Analyse {ticker} ({company_name}) for an Indian equity investor today.

=== KEY RATIOS ===
{json.dumps(fins, indent=2)}

=== QUARTERLY TREND (oldest → newest, last 4Q) ===
{json.dumps(q_trend, indent=2)}

=== ANNUAL TREND (oldest → newest, last 3Y) ===
{json.dumps(a_trend, indent=2)}

=== ANNUAL CASH FLOW (last 3Y) ===
{json.dumps(cf_trend, indent=2)}

=== QUANTITATIVE SCORES ===
{json.dumps(quant_block, indent=2)}

=== NEWS & ANNOUNCEMENT SENTIMENT ===
{json.dumps(sentiment_block, indent=2)}

=== COMPUTED TRADE PLANS (rule-based technical levels) ===
{json.dumps(plans_block, indent=2) if plans_block else "unavailable"}

=== INSTRUCTIONS ===
1. Synthesise ALL layers above into a comprehensive, data-driven investment thesis.
2. Be brutally honest — surface risks the numbers hide (channel stuffing, \
working-capital deterioration, promoter behaviour, sector headwinds, valuation traps).
3. Consider Indian regulatory context (SEBI rules, GST, RBI policy) \
and sectoral dynamics where relevant.
4. Confidence interval: flag if data is too thin for high conviction.

Return EXACTLY this JSON object (no markdown, no extra keys):
{{
  "conviction_score": <integer 1–100; 1=strong sell, 50=neutral, 100=strong buy>,
  "conviction_label": "<Strong Buy|Buy|Neutral|Sell|Strong Sell>",
  "thesis_summary": "<3 sentences: current situation | bull case | bear case>",
  "bull_case": "<2–3 specific, data-backed reasons to be long>",
  "bear_case": "<2–3 specific, data-backed reasons to be short or avoid>",
  "red_flags": [
    "<concrete hidden warning sign 1>",
    "<concrete hidden warning sign 2>",
    "<concrete hidden warning sign 3>"
  ],
  "key_catalysts": [
    "<specific future event to watch — include timeline if inferrable>",
    "<specific future event 2>",
    "<specific future event 3>"
  ],
  "valuation_view": "<cheap | fair | expensive vs historical/peers — 1–2 sentences>",
  "risk_reward": "<asymmetric upside vs downside assessment — 1 sentence>",
  "suggested_action": "<Buy on dips | Accumulate | Hold | Reduce | Avoid — with a specific condition>",
  "plan_commentary": "<1-2 sentences: do you agree or disagree with the computed trade plans and evidence stack above (base rates, regime, relative strength)? Cite the single strongest piece of evidence for or against. If plans are unavailable, say so.>",
  "data_confidence": "<high|medium|low — based on completeness of data provided>"
}}"""

    return prompt


# ── Gemini caller ─────────────────────────────────────────────────────────────

def _no_key_response() -> dict:
    return {
        "error":            "GEMINI_API_KEY not configured",
        "conviction_score": None,
        "conviction_label": "N/A",
        "thesis_summary": (
            "AI analysis is disabled. "
            "Set the GEMINI_API_KEY environment variable and restart the server."
        ),
        "bull_case":        None,
        "bear_case":        None,
        "red_flags":        [],
        "key_catalysts":    [],
        "valuation_view":   None,
        "risk_reward":      None,
        "suggested_action": None,
        "plan_commentary":  None,
        "data_confidence":  "n/a",
    }


def _error_response(msg: str, raw: str = "") -> dict:
    resp = _no_key_response()
    resp["error"]          = msg
    resp["thesis_summary"] = f"AI analysis failed: {msg}"
    if raw:
        resp["raw_response"] = raw[:600]
    return resp


async def generate_alpha_thesis(
    ticker:       str,
    raw_financials: dict,
    quant_scores: dict,
    sentiment_data: dict,
    trade_plans:  Optional[dict] = None,
) -> dict:
    """
    Call Gemini and return a structured alpha thesis dict.
    Always returns a valid dict — never raises an exception.
    """
    if not GEMINI_API_KEY:
        return _no_key_response()

    company_name = raw_financials.get("company_name", ticker)

    prompt = _build_prompt(
        ticker, company_name, raw_financials, quant_scores, sentiment_data,
        trade_plans,
    )

    payload = {
        "system_instruction": {
            "parts": [{"text": _SYSTEM_PROMPT}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "temperature":       0.15,   # low temperature → consistent, factual
            "topP":              0.85,
            "maxOutputTokens":   8192,
            "responseMimeType":  "application/json",  # force JSON output
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    }

    raw_text = ""
    try:
        # Retry up to 3 times for transient 429 / 503 errors
        r = None
        last_status = 0
        async with httpx.AsyncClient(timeout=60) as client:
            for attempt in range(3):
                r = await client.post(
                    _gemini_url(),
                    params={"key": GEMINI_API_KEY},
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                last_status = r.status_code
                if r.status_code not in (429, 503, 500):
                    break
                wait = 2 ** attempt          # 1s, 2s, 4s
                print(f"[gemini] HTTP {r.status_code} — retrying in {wait}s (attempt {attempt+1}/3)")
                await asyncio.sleep(wait)

        if r is None or r.status_code != 200:
            body = (r.text if r else "no response")[:400]
            print(f"[gemini] HTTP {last_status}: {body}")
            return _error_response(f"Gemini API returned HTTP {last_status}", body)

        resp_json = r.json()

        # Extract generated text — handle thinking-model parts (thought=True)
        try:
            candidates = resp_json.get("candidates", [])
            if not candidates:
                fb = resp_json.get("promptFeedback", {})
                return _error_response(
                    f"No candidates returned. Feedback: {fb.get('blockReason','unknown')}"
                )
            parts = candidates[0]["content"]["parts"]
            # Thinking models (gemini-2.5-*) may prefix a thought part;
            # grab the first non-thought text part.
            raw_text = ""
            for part in parts:
                if not part.get("thought") and part.get("text"):
                    raw_text = part["text"].strip()
                    break
            if not raw_text and parts:
                raw_text = (parts[-1].get("text") or "").strip()
        except (KeyError, IndexError) as e:
            return _error_response(f"Unexpected Gemini response shape: {e}",
                                   str(resp_json)[:400])

        if not raw_text:
            return _error_response("Empty text in Gemini response")

        # Strip markdown fences in case the model ignores responseMimeType
        raw_text = re.sub(r"^```[a-zA-Z]*\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text).strip()

        thesis: dict = json.loads(raw_text)

        # ── Sanitise / fill defaults ──────────────────────────────────────────
        thesis.setdefault("conviction_score",  50)
        thesis.setdefault("conviction_label",  "Neutral")
        thesis.setdefault("thesis_summary",    "Analysis generated.")
        thesis.setdefault("bull_case",         "")
        thesis.setdefault("bear_case",         "")
        thesis.setdefault("red_flags",         [])
        thesis.setdefault("key_catalysts",     [])
        thesis.setdefault("valuation_view",    "")
        thesis.setdefault("risk_reward",       "")
        thesis.setdefault("suggested_action",  "Hold")
        thesis.setdefault("plan_commentary",   "")
        thesis.setdefault("data_confidence",   "medium")

        # Clamp conviction score
        if isinstance(thesis.get("conviction_score"), (int, float)):
            thesis["conviction_score"] = max(1, min(100, int(thesis["conviction_score"])))

        # Ensure list fields are actually lists
        for list_key in ("red_flags", "key_catalysts"):
            if not isinstance(thesis.get(list_key), list):
                thesis[list_key] = [str(thesis[list_key])] if thesis.get(list_key) else []

        thesis["error"] = None   # explicit null — no error
        return thesis

    except json.JSONDecodeError as e:
        print(f"[gemini] JSON parse error: {e}\nRaw text: {raw_text[:300]}")
        return _error_response(f"JSON parse error: {e}", raw_text)

    except httpx.TimeoutException:
        return _error_response("Gemini API request timed out (>45s)")

    except Exception as e:
        print(f"[gemini] Unexpected error: {e}")
        return _error_response(str(e))
