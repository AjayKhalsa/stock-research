## Destination

StockLens can reliably rank the complete qualified NSE universe and separately publish zero to five long-only swing-trade candidates for a days-to-weeks holding period, with point-in-time data, deterministic fundamental and technical analysis, executable trade geometry, explicit evidence and failure-safe “no trade” behavior. The route is complete when the app is demonstrably ready for sustained paper trading and has a clear evidence gate for any later V2 promotion.

## Notes

- Product authority: [Plan.md](D:/iCloudDrive/iCloud~md~obsidian/Obsidian_icloud/StockScreener/Plan.md).
- Current system authority: [ARCHITECTURE.md](../../ARCHITECTURE.md) and [README.md](../../README.md).
- The user’s priority is good data and good insights, not more features or more recommendations.
- Treat the app as decision support, not a broker or promise of returns. “No trade today” is a correct result.
- Numerical indicators, scores, gates and trade geometry remain deterministic. AI may structure sourced qualitative evidence, explain and downgrade, but never invent calculations or upgrade a gated trade.
- This effort explicitly carries confirmed decisions into implementation, verification and deployment because the user asked that the existing plan be pursued phase by phase to completion. Wayfinding still resolves only one non-research decision ticket per session.
- Use the `wayfinder` skill for this effort. Install no additional skills for it.
- Release `f968533` (API 2.20) contains the reviewed financial-provenance and durable daily-job ownership baseline. The next release adds a complete qualified-universe ranking with explicit screen-only versus full-analysis depth.

## Decisions so far

- [What can the current app truthfully claim today?](issues/01-current-trust-baseline.md): StockLens is credible as a fail-closed automated research and paper-trading workspace, but filing/event provenance, explanation honesty, operational hygiene, access control and forward outcomes are insufficient for an investment-grade claim.
- [What data-source standard must actionable recommendations meet?](issues/02-data-source-standard.md): Preserve the current ₹0 recurring-cost constraint; use NSE/BSE records as authority, aggregators only as labelled support, and fail closed unless price, filing and event evidence is current, point-in-time and linked to its original source.
- [What evidence separates action from research?](issues/03-actionable-evidence-policy.md): Apply mandatory price, filing, event, freshness and geometry gates before scoring; publish at most five paper-ready ideas, preserve explicit research/insufficient/rejected states, and require at least 100 leakage-controlled forward outcomes before promotion can even be reviewed.
- [Can official filings be ingested within the zero-cost runtime?](issues/10-official-filings-ingestion-feasibility.md): Yes—use market-wide NSE metadata plus selective XBRL parsing with immutable revisions and coverage manifests; use BSE only as a bounded fallback, and do not mirror every PDF or pretend the undocumented public APIs are guaranteed.
- [What is the smallest daily user workflow?](issues/04-daily-decision-workflow.md): Keep the full qualified-universe ranking as a primary searchable surface, while Today filters it to zero-to-five evidence-gated decisions and Paper book records forward outcomes.
- [What daily operating standard must the pipeline meet?](issues/08-daily-operating-standard.md): Use trading-session-aware freshness, durable single-run ownership, explicit coverage/runtime thresholds and fail-closed publication classes that suppress stale action labels.

## Not yet specified

- The exact V2 feature weights and penalties; these remain unknowable until enough forward outcomes exist.
- The later ML target, calibration method and learning-to-rank design; these remain beyond the deterministic/paper-trading evidence frontier.

## Out of scope

- Intraday scanning or execution; the initial product is end-of-day swing research.
- Automated order placement, broker integration or unattended real-money trading.
- Short selling, derivatives, cryptocurrency and non-Indian universes.
- Claiming calibrated win probabilities before sufficient chronological evidence exists.
- Training directly on subjective human opinions or allowing an LLM to control numerical scoring.
- Multi-user SaaS, billing and broad authentication work while this remains a personal research tool.
