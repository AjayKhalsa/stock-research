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
