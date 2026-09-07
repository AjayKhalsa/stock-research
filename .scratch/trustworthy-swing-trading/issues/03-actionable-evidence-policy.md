Type: grilling
Status: resolved
Blocked by: 01

## Question

What explicit evidence policy should separate “Actionable today,” “Near trigger,” “Research only,” and “No trade,” including the minimum data completeness, trade geometry, event coverage and forward-validation requirements for each state?

## Answer

### Governing rule

Evidence gates are evaluated before the weighted score. A high score cannot compensate for a missing or stale mandatory evidence domain. Known safety failures take precedence as `AVOID`; otherwise, an unknown or incomplete mandatory domain produces `DATA_INSUFFICIENT`. The app may retain and display the calculated score for audit, but it must not use that score to imply actionability.

Until chronological outcomes support promotion, the strongest user-facing claim is **paper-ready today**, not “best stock to invest in” or a calibrated probability of success.

### Investable-universe gate

Every ranked security must be an active NSE equity with a stable symbol and ISIN, at least 252 usable adjusted daily sessions, a latest close above ₹20, and a median 20-session traded value of at least ₹5 crore. All market inputs used in a snapshot must refer to the same completed trading session. Securities that fail these rules do not enter the candidate ranking.

### Mandatory evidence gate for actionable states

`BUY_NOW` and `WAIT_FOR_ENTRY` require all of the following:

1. **Price integrity:** the latest Yahoo adjusted close is reconciled against the official NSE close for the same session and differs by no more than 1%. Corporate-action adjustments and their effective dates are archived.
2. **Financial integrity:** every score-driving reported value is traceable to an original NSE/BSE filing or XBRL document, its exchange broadcast timestamp, period, consolidated/standalone basis and revision status. Comparable periods must exist and conflicts must be resolved or explicitly block action.
3. **Event integrity:** official NSE/BSE announcement and financial-results coverage completed successfully through the snapshot cutoff. Unknown event coverage means unknown risk, not “no event.” Aggregator calendars may support but cannot satisfy this gate alone.
4. **Freshness:** prices, filings, announcements, benchmark and sector context carry explicit as-of times and meet their domain-specific freshness rules. A stale mandatory domain fails the gate.
5. **Trade geometry:** a named active setup exists; entry/trigger, stop, structural target and invalidation are present; stop is below entry and target above entry; structural reward/risk is at least 1.50; stop risk is no more than 10%; overhead clear air is at least 1.25 ATR; tradeability score is at least 30; and the price is less than 2 ATR beyond the trigger.
6. **Risk gates:** no unresolved critical adverse event, severe accounting/financial-quality hard block, or imminent scheduled result inside five completed trading sessions. Six to ten sessions before a scheduled result caps the idea at `WAIT_FOR_ENTRY`; eleven to fifteen sessions carries a visible caution. A severe risk-off market blocks all new long actions.
7. **Explanation integrity:** every positive claim names its raw fact and source. Every penalty, hard block, near-threshold condition, stale/unknown domain and disagreement between fundamentals and chart appears under “What holds it back.” The app must never say “no concern” while any penalty or caution exists.

### State contract

| Product state | Deterministic action | Required evidence and behavior |
|---|---|---|
| **Actionable today** | `BUY_NOW` | All mandatory evidence gates pass; active supported setup; score at least 72; reward/risk at least 1.50; current price is inside the entry zone with its trigger condition confirmed; no hard block. Publish at most five. Before model promotion, label this “Paper-ready today.” |
| **Near trigger** | `WAIT_FOR_ENTRY` | All mandatory evidence gates pass; active supported setup; score at least 68; valid geometry; price is in or within 3% of the entry zone, or a named price/volume trigger remains unmet; no hard block. Publish at most ten including overflow from the actionable list. |
| **Research only** | `WATCH` | Investable-universe data is adequate, score is at least 52, but the setup is missing, developing, too far from entry, or evidence is adequate for analysis but not action. It must state the exact missing trigger or disagreement and must not display an executable recommendation. |
| **Insufficient evidence** | `DATA_INSUFFICIENT` | No known hard safety failure, but at least one mandatory price, filing, event, freshness or geometry input needed to assess actionability is missing, stale, conflicting or unverified. Show the missing evidence and preserve the partial analysis only for research/audit. |
| **No trade / rejected** | `AVOID` | Evidence is sufficient to identify a hard safety failure, invalid geometry, an explicit adverse condition, or score below 52. Show every rejection reason. Zero `BUY_NOW` and zero `WAIT_FOR_ENTRY` is a valid daily outcome and must be presented plainly as “No trade today.” |

Action grades (`A+`, `A`, `B`) apply only to candidates that first pass all actionable evidence gates. Non-actionable candidates use descriptive labels such as `Developing`, `Good Stock / Bad Entry`, `Good Chart / Weak Fundamentals`, `Data insufficient` or `Avoid`.

### Market-regime overlay

The existing deterministic risk-off penalty remains visible. In ordinary risk-on/neutral conditions, the thresholds above apply. In `risk_off`, `BUY_NOW` requires score at least 80 and `WAIT_FOR_ENTRY` at least 75; an idea below those thresholds is research-only even if its setup is otherwise valid. `severe_risk_off` publishes no new long action. These stricter thresholds are an initial risk-control rule and must be re-evaluated only from chronological outcome evidence, not tuned to a favourable backtest.

### Forward-validation maturity

- **0–29 resolved actionable outcomes:** research and paper trading only; show that the model is unproven and do not use real-money action language.
- **30–99 resolved actionable outcomes:** early forward evidence; continue paper trading and display observed expectancy, hit rate, drawdown and confidence intervals with sample size, but make no promotion claim.
- **100 or more resolved actionable outcomes:** the model becomes eligible for a separate promotion review; it is not automatically approved. The review must use chronological, leakage-controlled results across market regimes and market-cap buckets.

Never display a win probability unless it has been calibrated and validated on held-out chronological outcomes. Observational `WATCH` outcomes remain diagnostically useful but do not count as actionable outcomes for promotion.

### Immediate consequence for the current app

The current production snapshot cannot truthfully emit `BUY_NOW` or `WAIT_FOR_ENTRY` under this policy because exchange-filing source documents are absent and official event coverage is unverified. The local API 2.19 normalized-metric work improves auditability but provider-page links do not satisfy the original-filing gate. Until official ingestion is complete, those rows must remain research-only or data-insufficient. That fail-closed result is correct, even when the ranking score is high.
