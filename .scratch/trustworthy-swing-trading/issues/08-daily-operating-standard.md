Type: grilling
Status: resolved
Blocked by: 01

## Question

What freshness, coverage, duration, consecutive-failure and stale-run thresholds must the daily pipeline meet, and which failures should hold publication versus publish the previous valid snapshot with an explicit warning?

## Production evidence reviewed

- Revalidated against production on 2026-09-06: API version 2.18.0 and model `swing-v1.5.0` were healthy on durable PostgreSQL, while the latest valid market session remained Friday 2026-09-04 as expected for the weekend.
- The current official universe is 2,288 equities; recent valid runs produced about 927-934 eligible stocks and published 100.
- Successful runs recently took about 5-15 minutes. Three database rows have remained `running` for roughly 118 hours (425,000+ seconds), showing that the in-process lock does not survive restarts.
- The current usable-history hard floor is only 50% of the universe. Two recent runs failed at 648/2,301 and 480/2,302 usable histories.
- More than one successful run can publish the same target trading session. The job history also reports some unavailable counts as zero, which can make missing telemetry look like a genuine zero.
- The latest snapshot is marked `attention`, with seven ranked candidates carrying partial or missing financial evidence. It is correctly explicit about those gaps, but it needs a deterministic rule for whether they merely downgrade individual stocks or invalidate the whole daily decision set.

## Approved operating standard

These rules treat freshness in **completed NSE trading sessions**, not calendar days. A Friday snapshot remains current over a weekend or exchange holiday.

### 1. Target session, scheduling, and single ownership

- Each run targets the latest completed official NSE EQ trading session.
- There may be only one published snapshot for `(target trading session, model version)`. A later correction must be stored as an explicit repair revision, never as an indistinguishable duplicate.
- Attempt the daily run at 02:00, 04:00, and 06:00 IST. Later attempts are no-ops when a decision-valid snapshot already exists.
- The morning decision-ready deadline is 07:00 IST. At 07:00 the app must show a visible warning if the target session is not ready; at 07:30 it becomes a hard daily miss.
- Use a database-backed lease with a heartbeat. A run with no heartbeat for 30 minutes is abandoned, and the next attempt may safely take ownership. Old `running` rows are finalized as abandoned during startup and before a new attempt.

### 2. Runtime and retries

- Healthy runtime objective: no more than 15 minutes.
- Attention threshold: 20 minutes.
- Lost/stale run threshold: 30 minutes without a successful heartbeat.
- Retry transient provider failures up to three times with bounded exponential backoff and jitter.
- Retry the whole job only when there is no current valid snapshot and no live lease.
- One failed target session produces a warning and automatic retry; two consecutive failed sessions produce a high alert; three produce a critical alert and suspend all new action recommendations pending manual review. One fully valid current-session success resets the streak.

### 3. Required freshness

| Dataset | Requirement |
| --- | --- |
| NSE EQ bhavcopy | Must match the target trading session exactly. |
| Nifty and sector benchmarks | Must match the target trading session exactly. |
| Adjusted price history | Must include the target session, or receive a documented one-session official-bar patch; patched values must reconcile within 1%, otherwise that symbol is downgraded. |
| NSE equity master | Refresh daily; a holiday-aware cached copy may be used only if it is at most 72 hours old and passes the rolling-count coverage test. |
| NSE announcements and corporate actions | Incremental coverage through 06:30 IST, with a seven-day overlap on every run and a 35-day reconciliation weekly. |
| Candidate financials | Must contain the latest report that should reasonably be available for the issuer. A candidate is warned at 120 days since the latest period and becomes non-actionable at 150 days or when an expected due period is missing. |

### 4. Required coverage

- Official universe: at least 95% of the median of the last 20 valid runs and at least 2,000 symbols.
- Raw official bhavcopy: at least 99% of the accepted official universe.
- Usable price histories: healthy at 80% or more; attention at 70-79.9%; hold publication below `max(1,500, 70% of the official universe)`.
- Eligible scan output: at least 500 symbols and at least 70% of the median of the last 20 valid runs.
- Every published candidate must pass the required evidence invariants. Missing evidence may downgrade one symbol to `DATA_INSUFFICIENT`; it must never be silently replaced by a neutral or zero value.
- The deep-analysis bench may contain up to 150 names, but every `BUY`, `WAIT`, and portfolio-management instruction must have complete mandatory evidence.

### 5. Publication classes

**Decision-valid current snapshot**

Publish current recommendations only when price, universe, benchmark, archive/audit, events-manifest, coverage, and per-candidate evidence gates all pass.

**Research-only current snapshot**

If current-session market data passes but the filings/events feed or candidate-wide fundamental evidence is incomplete, publish current technical research with a prominent warning. Force affected `BUY` and `WAIT` labels to `DATA_INSUFFICIENT`; do not create new paper trades or investment actions from them.

**Previous valid snapshot only**

Do not publish a new snapshot when any core truth check fails: durable storage, target-session identity, official universe, bhavcopy, benchmark, minimum usable/eligible coverage, transactional archive, schema validation, or audit integrity. Continue displaying the previous valid snapshot with its trading date and stale state; never present its old action labels as current recommendations.

**Warning-only supplementary failures**

AI commentary, secondary BSE fallback when primary NSE evidence is healthy, news, VIX, backtest summaries, or paper-performance statistics may fail without blocking the deterministic snapshot. Show the missing component explicitly and omit claims that depend on it.

### 6. Stale-snapshot behavior

- Lag of zero completed trading sessions: current.
- Lag of one completed trading session: stale warning; research and existing-position context remain visible, but suppress `BUY`, `WAIT`, and new paper-trade actions.
- Lag of two or more completed trading sessions: unavailable for daily decisions; hide the actionable shortlist and show `No current decision snapshot`.
- Recompute lag whenever the API is read. Keep the originally published record immutable for audit, while the presentation and action endpoints enforce current staleness.

### 7. Required observability and acceptance checks

- Status endpoints must expose target session, latest valid session, trading-session lag, lease owner/heartbeat age, attempt number, consecutive failure count, per-source freshness and coverage, and current capability (`decision-valid`, `research-only`, or `unavailable`).
- A missing metric is `null/unavailable`, never `0`.
- Job history must distinguish completed, failed, abandoned, and superseded runs, and link each run to its target session and snapshot revision.
- Automated tests must cover duplicate triggers, restart recovery, 30-minute lease expiry, holiday/weekend freshness, each publication class, per-symbol downgrade, whole-run hold, and one-/two-session staleness.

## Resolution

The user instructed implementation to start on 2026-09-07 after reviewing the proposed workflow and operating checkpoint. These thresholds are therefore approved as the implementation and release gate for the daily pipeline. Changes discovered during implementation must be recorded as an explicit revision here rather than silently weakening a gate.
