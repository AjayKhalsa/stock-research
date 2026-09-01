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

Set `CRON_SECRET_KEY` and call the protected `POST /api/jobs/daily/run` from a
scheduler. The included GitHub workflow starts it at 07:00 IST on weekdays.
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
