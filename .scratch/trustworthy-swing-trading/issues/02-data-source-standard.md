Type: grilling
Status: resolved
Blocked by: 01

## Question

Given the concrete gaps found in the current trust baseline, what minimum source quality, freshness, point-in-time provenance and acceptable recurring cost should each data domain meet before it may influence an actionable recommendation?

## Answer

Resolved on 2026-09-06 from the existing product constraint and primary-source research. [ARCHITECTURE.md](../../../ARCHITECTURE.md) explicitly defines the present stack as deliberately zero-cost, and the user supplied no authorization to add a subscription. Therefore the acceptable recurring data fee remains **₹0 for the current production model**. A paid or licensed feed is a later opt-in decision, not an assumed dependency.

Official exchange evidence is available without inventing provenance: NSE exposes financial-result and integrated-filing records with period, consolidated/standalone state, broadcast time, revision time, attachment and XBRL links; BSE exposes filing timestamps, revisions, XBRL, announcements, board meetings and corporate actions. Relevant primary sources include [NSE financial results](https://www.nseindia.com/companies-listing/corporate-filings-financial-results), [NSE integrated financial filings](https://www.nseindia.com/companies-listing/corporate-integrated-filing), [NSE announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements), [NSE XBRL information](https://www.nseindia.com/static/companies-listing/xbrl-information), [BSE financial results](https://www.bseindia.com/corporates/comp_results.aspx), and [BSE corporate actions](https://www.bseindia.com/corporates/corporates_act.html).

NSE also offers a supported EOD corporate-announcement product, but its published domestic price is ₹5,00,000 per year. That is outside the current zero-cost constraint and therefore not a hidden requirement for V1.

### Source hierarchy and minimum standard

| Data domain | Authoritative source | Permitted supporting source | Minimum evidence before it may support an actionable state |
|---|---|---|---|
| Security identity | NSE official equity master, keyed by ISIN | BSE code directory for cross-reference | Active NSE equity, stable `security_id`, symbol, ISIN and observation date. A missing ISIN or ambiguous symbol may be searchable but not actionable. |
| Latest OHLCV, delivery and turnover | NSE cash-market bhavcopy | None for the official close | Latest completed NSE session, internally valid OHLC, positive volume where trading occurred, and at least 95% universe coverage. A stale or missing official session holds publication. |
| Adjusted price history | Yahoo adjusted EOD | NSE close and official corporate-action records | At least 252 completed sessions; latest adjusted close reconciled to the same-session NSE close within 1%; no unexplained recent adjustment boundary or multi-session gap. Yahoo alone may calculate research features but cannot authorize an entry. |
| Corporate actions | NSE/BSE corporate-action records and company filing attachment | Yahoo adjustment factor as a detector | Event type, ex/record/effective date, source URL and observation time. A detected factor without an official matching event remains `unverified`; a material unexplained boundary blocks the affected recommendation. |
| Financial statements | NSE/BSE result filing, attachment or XBRL | Screener.in and Yahoo only for discovery, normalization and cross-checking | Every score-affecting period must retain period end, exact exchange broadcast timestamp, consolidated/standalone basis, original/revised status, source exchange, original attachment/XBRL URL, observation time and content/revision hash. Aggregator-only values cannot receive full financial trust. |
| Fundamental ratios | Deterministically calculated from sourced filing metrics where possible | Screener/Yahoo reported ratio as a labelled fallback | Formula, input report IDs and units retained. An aggregator ratio must be marked derived/unverified and cannot independently pass a safety gate. |
| Earnings calendar | NSE/BSE board-meeting/results filing | Yahoo calendar only as an unverified hint | Latest successful exchange-calendar poll and a future event date tied to its source. A past date never earns event completeness. Unknown coverage remains unknown. |
| Corporate catalysts and risks | NSE/BSE announcement metadata plus original attachment | Company investor-relations document; news only as a discovery hint | Broadcast date/time, event type, source, document URL, structured severity and extraction confidence. News or an LLM assertion without an original source cannot affect the score. |
| Market and sector regime | NSE index/session data plus breadth calculated from the same frozen universe | Yahoo history only after official-session reconciliation | Same completed session as candidates, frozen universe denominator and explicit unavailable fields. Missing VIX cannot be silently converted to neutral evidence. |
| AI extraction | Original exchange/company documents already archived above | None | Structured, versioned output containing source document and evidence location. AI may explain or downgrade only; missing AI coverage contributes no positive confidence. |

### Freshness rules

- Price, liquidity, breadth, market regime and technical features must all use the latest completed NSE session and the same `as_of` date.
- Corporate announcements, board meetings and action calendars must complete a successful official-source refresh after the preceding market close and before snapshot publication. A failed refresh makes event coverage unverified for affected candidates.
- Financial records refresh when a new exchange filing/revision arrives. A seven-day aggregator cache may remain a performance optimization, but it is not proof of filing freshness.
- Every record keeps both `observed_at` and the provider’s `broadcast_at`/`filing_date`. Point-in-time consumers use the later availability boundary and never infer an earlier filing date from the reporting period.
- Revisions append; they never replace the earlier value. Backtests choose the latest revision whose availability timestamp was known at historical time T.

### Trust and failure behavior

- “Complete” means sourced and current, not merely populated.
- The financial score cannot be 100 when the score-driving numbers lack original filing provenance.
- The event score cannot be 100 unless official event coverage is verified through the snapshot time.
- Overall evidence completeness cannot be 100 if any mandatory domain is unverified.
- Provider conflict, stale official price, missing critical financial evidence, failed event refresh or unexplained corporate action never falls back to optimism. The candidate becomes `DATA_INSUFFICIENT`, `WATCH`, or `AVOID` according to the recommendation policy resolved separately.
- Free-source instability is handled with bounded retries, caching, last-known evidence and explicit downgrades. It is not handled by increasing scrape intensity or presenting stale data as current.

### Consequence for local API 2.19

Keep the normalized `financial_metrics` table and dual-provider provenance work, but treat the Screener/Yahoo URL as a **provider page**, not an original `source_document`. The schema is ready to receive exchange filing timestamps and attachments; the current payload is not yet sufficient to pass the financial standard above.
