Type: research
Status: resolved
Blocked by:

## Question

What can the current local and deployed StockLens app truthfully claim today about universe coverage, point-in-time data, fundamental and technical completeness, recommendation safety, explainability, scan reliability and forward outcome evidence—and where do code, documentation and production behavior disagree?

## Answer

Reviewed on 2026-09-06 against the current worktree, the deployed API, the rendered CFO workspace, automated tests, [Plan.md](D:/iCloudDrive/iCloud~md~obsidian/Obsidian_icloud/StockScreener/Plan.md), [ARCHITECTURE.md](../../../ARCHITECTURE.md), and [README.md](../../../README.md).

### Resolution

StockLens may truthfully present itself as an automated, deterministic **research and paper-trading workspace**. It may not yet present its ranked names as proven “best stocks to invest in” or imply demonstrated trading edge. The current system is strong enough to generate hypotheses and preserve them for forward testing, but its financial/event evidence and its outcome history are not yet strong enough to authorize real-money reliance.

### What is already credible

| Area | Evidence | Truthful claim |
|---|---|---|
| Universe | Latest production snapshot covers 2,288 active NSE equities, 932 eligible names, 151 deeply enriched names and 100 published candidates. Official raw close coverage is 2,284/2,288 (99.83%). | The app performs a broad automated NSE end-of-day scan rather than screening a tiny hand-picked list. |
| Technical analysis | Deterministic engines calculate trend, relative strength, relative volume, volatility contraction, overhead supply, tradeability, move potential and separate breakout/pullback/trend-continuation scorecards. | The technical layer is substantially aligned with the plan and is reproducible from stored candles. |
| Trade geometry | 85/100 current candidates have structural reward/risk, with entry zones, trigger, stop, target and invalidation. Hard gates reject missing targets, sub-1.5 R/R, impractical stops, severe supply, extreme extension and very erratic price paths. | The app generates auditable trade structures rather than repeating an arbitrary target multiple. |
| Fail-safe behavior | The 2026-09-04 snapshot is `risk_off` and correctly publishes 0 Ready Now, 0 Near Entry, 33 Watch, 60 Avoid and 7 Data Insufficient. | “No trade today” works in production. The current dashboard is not forcing a recommendation. |
| Point-in-time scaffolding | Security identities, immutable snapshot candidates, raw latest-session exchange bars, adjusted history, feature snapshots, recommendation versions and forward outcome rows are durable in Postgres. | New recommendations can be frozen and evaluated without rewriting their original model state. |
| User surface | The Morning page makes regime, shortlist, events and integrity visible; the dossier exposes trade levels, bull/bear sections, trust checks, paper tracking and human review. | The primary workflow is usable and materially more selective than the legacy 100-row terminal. |
| Verification | Current local worktree: 72 backend tests pass, 22 frontend tests pass, and the optimized frontend build succeeds. | The implemented deterministic behaviors have a meaningful automated regression suite. |

### Trust gaps that prevent an investment-grade claim

1. **Financial data is complete-looking, not filing-grade point-in-time evidence.** Production has 6,042 financial report observations, but the archive audit reports that 6,042/6,042 lack both provider filing dates and source documents. Candidate explanations retain only a provider label and fetch timestamp. This means the system can replay when it first observed a value, but generally cannot prove when the market first knew it or show the underlying filing. Financial values still influence business quality and earnings momentum.

2. **Event confidence contradicts event coverage.** In the current Top 100, 96 candidates say event coverage is `unverified`, yet 32 receive an event-data score of 100; 28 candidates therefore display 100% event data while simultaneously saying coverage is unverified. The top-ranked WSTCSTPAPR dossier visibly shows `Event data 100%` and `Event risk unknown · coverage unverified`. The cause is that `assess_data_confidence` rewards any stored `earnings_date`, including a date that is no longer upcoming, while `assess_event_risk` correctly finds no verifiable future event.

3. **The overall completeness percentage overstates trust.** Twenty-six candidates display 100% overall data completeness even though filing provenance is absent and most event calendars are unverified. The score currently measures populated fields, not source quality. It therefore cannot safely act as the hard recommendation gate intended by Plan phases 15, 33 and 65.

4. **The insight layer omits known negatives.** Fifteen current candidates have deterministic penalties but an empty `what_holds_it_back` list; the rendered UI says “No material deterministic concern was found.” WSTCSTPAPR omits the risk-off penalty, weak 0.7 RVOL, weak breakout candle-quality score and merely moderate tradeability from its bear case. One of the eight “Best setups this morning” has setup type `none`. The ranking math may be defensible, but the explanation does not yet fully explain the decision.

5. **There is no evidence of trading edge yet.** The automatic actionable ledger has 0 rows because the latest fail-safe snapshot produced no actionable names. It has 25 observational rows and 0 resolved outcomes. The point-in-time backtest is correctly `no_data` with sample 0. One manually selected paper trade has closed, which is operational evidence only—not performance evidence. No win rate, expectancy, rank quality or calibrated probability claim is currently supported.

6. **Historical coverage cannot support the full planned backtest.** The archive currently has one official raw session for almost the full universe and 54,458 adjusted revisions for the bounded enriched bench. It does not have historical constituent masters, delisted names, complete corporate-action classifications, limit-circuit history or filing-time financial history. The app correctly discloses most of these limitations, but a survivorship-free all-NSE historical backtest is not presently possible.

7. **Operational history contains misleading state.** Production is API 2.18.0. Recent scans show five consecutive successful publications in roughly 292–381 seconds, but the retained history also has three records still marked `running` after more than 117 hours, plus prior coverage failures and a serialization failure. The System page claims each row retains coverage/action/failure details but renders zeros for older rows whose payload predates that schema. It also shows “Awaiting first audit” although the on-demand archive audit returns `attention` with two provenance warnings.

8. **Personal data and costly mutations are publicly exposed.** The deployed API has no access control on watchlist, alerts, portfolio settings, human reviews, paper trades, manual backtests or the resource-heavy manual NSE scan. Even for a personal app, an internet-accessible backend permits outside mutation or workload abuse. Full multi-user authentication is unnecessary, but a minimal private-access boundary is required before the system is trusted as a personal operating tool.

9. **Tests do not prove provider truth or end-to-end production behavior.** The automated suite strongly covers deterministic functions, API contracts, lifecycle rules and UI rendering, but most external providers are mocked. There are no golden comparisons against exchange filings, no provider-drift contract test, and no browser-level test that fails on contradictory evidence states. Frontend tests also pass while emitting several unwrapped React state-update warnings.

### Local API 2.19 assessment

The uncommitted 2.19 slice adds immutable numeric `financial_metrics`, point-in-time queries, Screener/Yahoo provider-page retention and UI/archive counts. Its tests pass and it is directionally correct. It does **not** supply the missing filing dates or original exchange filing documents, and it does not fix event-confidence inflation, incomplete bear explanations, stale job states or access control. It should therefore be reviewed as an enabling archive improvement, not described as completion of the financial trust layer.

### Product status

- **Appropriate now:** automated research, shortlisting, paper tracking, model observation, and “no trade” decisions.
- **Not appropriate now:** presenting rankings as proven investment recommendations, displaying success probabilities, promoting V2, or relying on the system for unattended real-money decisions.
- **Next decisions:** define the minimum data-source standard and the evidence policy for recommendation states before choosing the safe release sequence.
