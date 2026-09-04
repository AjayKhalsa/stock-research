# StockLens

Personal, long-only NSE swing-research workspace for a 4–8 week horizon. The
default experience is a precomputed 07:00 IST morning brief: market regime,
sector leadership, a controlled Top-100 candidate bench, paper-portfolio risk,
and decision dossiers. The original detailed research terminal remains under
**Research**.

## Run locally

Backend:

```powershell
cd backend
python -m uvicorn main:app --reload --port 8000
```

Frontend:

```powershell
cd frontend
npm start
```

The included GitHub workflow uses its short-lived job installation token to
call the protected `POST /api/jobs/daily/run` at 07:00 IST on weekdays. The
backend verifies both repository access and the live workflow run, so no shared
scheduler secret is required. `CRON_SECRET_KEY` remains available as an optional
fallback when using another scheduler.
The feature flag `CFO_WORKSPACE_V1=true` enables the new shell; set the frontend
build flag `REACT_APP_CFO_WORKSPACE_V1=false` to open the legacy workspace
directly.

Free providers are treated as replaceable adapters. A missing NSE bhavcopy,
price conflict over 1%, incomplete financial evidence, near-term results, or
pending historical validation prevents an actionable recommendation rather
than being treated as positive evidence.

StockLens does not recommend share counts or capital allocations. Candidate
dossiers show trade structure, risk-to-stop and explicit trust controls; the
Portfolio page manages exposure policy only.

## Bull AI evidence

The strongest morning candidates can include a bounded Bull AI research layer:
reported guidance and delivery, revenue segments, management-claimed moats,
listed peers, disclosed counterparties, and insider/corporate-action context.
Every item keeps its source label and limitations in the Evidence tab.

Bull AI is supplementary evidence only. It has no direct score effect, cannot
upgrade a gated recommendation, and missing Bull AI coverage is never treated
as positive evidence. The unattended daily scan remains independent of the
plugin, so an unavailable connector cannot prevent the last valid snapshot
from loading.

The all-NSE price pass is sized for Render's free memory limit: six bounded
Yahoo chart requests run at once, only one 75-symbol batch is resident, and
full candles are retained only for the top-150/owned/watched bench. A snapshot
is held back unless at least half the official universe has 252-session history
and at least 100 stocks pass the price/liquidity gates.

Swing model `swing-v1.5.0` separates business quality from quarterly earnings
momentum, labels margin expansion/contraction, measures overhead supply, clear
air, tradeability and move potential, and derives targets from chart structure
before calculating reward/risk. Data completeness is shown separately for
price, financial and event evidence and is never presented as win probability.
The published decision surface is intentionally limited to five ready-now and
ten near-trigger candidates; all other names remain searchable research.
Multi-horizon strength versus NIFTY, relative-volume participation, volatility
contraction, market breadth and risk-on/risk-off context feed the same auditable
snapshot. Severe risk-off conditions fail closed for new long entries.
Breakout, pullback and trend-continuation setups have independent, visible
scorecards; a strong developing score cannot manufacture a missing trigger.
Known earnings and corporate events receive an explicit low/medium/high risk
state while missing calendar coverage remains unverified. The dossier includes
an optional position-size calculator driven only by the user's portfolio value,
risk limit, and the model's structural entry/stop.

Paper tracking is point-in-time and rules-based. A selected setup is first
**armed** at its published entry zone, activates only when a later daily candle
touches that zone, and then closes at the structural stop, target, or 40-session
time stop. Untouched entries expire after 10 sessions. Ambiguous same-day bars
are excluded instead of inventing an intraday path. Each result retains its
snapshot/model version, realized R, exit price/date, and maximum favorable and
adverse excursion; the scorecard keeps exclusions separate from resolved
outcomes.

Ranked dossiers also accept a structured human review—looks right, too
optimistic, too conservative, or data issue—with an optional note. Reviews are
append-only and retain the exact snapshot, model version, action, and score;
they do not alter the live rank.

In parallel, every published `BUY_NOW` or `WAIT_FOR_ENTRY` candidate with valid
trade geometry enters an automatic recommendation-outcome ledger. Daily
evaluation reuses retained scan candles where possible, fetches each missing
symbol only once, and reports resolved/excluded counts, expectancy, MFE, and
MAE in System. This broader ledger is separate from the user's chosen paper
tests.

The System page also runs a point-in-time snapshot replay over resolved ledger
rows. It reports gross and cost-adjusted expectancy, Wilson win-rate ranges,
profit factor, drawdown, holding time, MFE/MAE, and breakdowns by setup, market
regime, original rank decile, and action. Stored signal adjustment factors keep
entry, stop, and target levels comparable across later splits and dividends.
The report does not backfill current fundamentals or pretend that the complete
historical NSE constituent master was archived; it remains explicitly early
below 30 outcomes and becomes mature only at 100.

V2 is explicitly evidence-gated. System compares the production algorithm,
the not-yet-calibrated challenger, and structured human reviews side by side;
the challenger remains locked until 100 resolved forward outcomes and can never
promote itself. The Candidates page supports in-snapshot symbol/company/sector
search and keeps safety-gated or data-held stocks in a separate rejected audit
section instead of silently dropping them.

If a delayed daily job starts after the market opens, the scanner trims Yahoo's
in-progress daily bar to the latest completed NSE bhavcopy session before any
features or price reconciliation are calculated. This keeps the snapshot
point-in-time and prevents a one-session mismatch from holding back the entire
ranking.

When Yahoo is exactly one completed session late, the scanner appends that
session's real NSE bhavcopy open, high, low, close, and volume before analysis.
It will not bridge multiple missing sessions, and it rejects gaps over 40% so a
split or bonus issue cannot masquerade as a normal price move while adjustment
data is still catching up.
