# StockLens — Architecture & Feature Reference

StockLens is an institutional-style research terminal for Indian equities (NSE/BSE). It combines quantitative factor scoring, a structure-aware trade-decision engine, price-action/volume forensics, and an AI "devil's advocate" analyst into a single research and screening workspace — plus a persistent watchlist, alerting, and a batch screener that ranks hundreds of stocks cross-sectionally.

This document describes the system as it exists today: the deployed architecture, every backend engine and API endpoint, the full frontend feature set, the data model, and how it evolved.

---

## 1. System Architecture

Three independently-deployed tiers, each with exactly one job:

```
   Browser (user)
        │
        ▼
┌──────────────────────┐   HTTPS  /api/*  (axios)   ┌───────────────────────┐   SQL over TLS   ┌─────────────────┐
│   VERCEL              │ ─────────────────────────▶ │   RENDER               │ ────────────────▶ │   POSTGRES       │
│   React frontend       │                            │   FastAPI backend      │                    │   (Neon / Render │
│   (static, CDN)        │ ◀───────────────────────── │   (uvicorn)            │ ◀──────────────── │    managed DB)   │
└──────────────────────┘        JSON / SSE            └───────────────────────┘      rows           └─────────────────┘
                                                        also calls out to:
                                                        Screener.in, Yahoo Finance,
                                                        BSE India, Google News RSS,
                                                        Gemini API, NSE archives
```

| Tier | Role | Holds state? |
|---|---|---|
| **Vercel** | Serves the built React app (static assets on a CDN). No server logic. | No — pure presentation |
| **Render** | Runs the FastAPI backend (`uvicorn main:app`). All scraping, scoring, and AI calls happen here. | No — compute is stateless/ephemeral by design |
| **Postgres** (Neon or Render-managed) | Durable store for watchlist, saved screens, alerts, settings, and the fundamentals cache. | Yes — the only tier that must survive restarts |

**Why the split matters:** Render's free web plan has an *ephemeral* disk that is wiped on every restart/redeploy (and free instances spin down after ~15 min idle). Anything stored only on Render's local disk — including a local SQLite file — is lost on the next restart. Moving durable state into an external Postgres database means the backend can restart freely (free tier, frequent redeploys) without ever losing the watchlist or saved screens. Render's own managed Postgres free tier is *also* time-limited (~30 days), so a permanently-free external provider such as **Neon** (or Supabase) is the recommended `DATABASE_URL` target for a fully-free, fully-durable setup.

### Wiring between tiers

| Connection | Configured via | Notes |
|---|---|---|
| Vercel → Render | `REACT_APP_API_URL` (Vercel env var) | **Baked in at build time** by Create React App — changing it requires a Vercel rebuild, not just a config edit |
| Render → Postgres | `DATABASE_URL` (Render env var) | `db.py` auto-detects: Postgres if set, else falls back to local SQLite (dev default) |
| Browser → Render (CORS) | `main.py` CORS middleware | Explicitly allows `localhost:3000`/LAN IPs and any `https://*.vercel.app` origin |

### Request lifecycle (example: opening the watchlist)

1. Browser loads the static React bundle from Vercel's CDN.
2. `Watchlist.js` calls `getWatchlist()` → `GET https://<render-host>/api/watchlist`.
3. Render's FastAPI handles it → `db.watchlist_all()`.
4. `db.py` sees `DATABASE_URL` is set → runs `SELECT ... FROM watchlist` against Postgres.
5. Rows come back → serialized to JSON → rendered in the sidebar.

Running a screen follows the same shape but additionally fans out to Screener.in/Yahoo Finance per symbol and streams results back incrementally over Server-Sent Events (`/api/screen-stream`).

---

## 2. Tech Stack

**Backend** — Python, FastAPI, uvicorn. No ORM (raw SQL via `sqlite3`/`psycopg`). No task queue — all work happens inline within request/stream handlers, concurrency via `asyncio.gather` and bounded semaphores.

```
fastapi, uvicorn[standard], httpx, beautifulsoup4, lxml, feedparser,
python-dotenv, pydantic, aiofiles, pandas, yfinance, vaderSentiment,
psycopg[binary]
```

**Frontend** — React 19 (Create React App), no state-management library (component state + prop-drilling), `recharts` for charts, `axios` for HTTP, `react-hot-toast` for notifications. No CSS framework — hand-written CSS with CSS custom properties for theming.

**External services the backend talks to:**
| Service | Used for | Auth |
|---|---|---|
| Yahoo Finance (`yfinance`) | Price history, LTP, intraday candles, fundamentals fallback | None (no key) |
| Screener.in (scraped) | Primary fundamentals source (ratios, quarterly results, shareholding, financial statements) | None (scraped HTML) |
| NSE archives | Official equity symbol/name master list (weekly refresh) | None |
| BSE India API | Corporate announcements/filings | None |
| Google News RSS | Headline news per stock | None |
| Google Gemini API | AI "Devil's Advocate" thesis generation | `GEMINI_API_KEY` |

No paid data vendor is used anywhere — this is deliberately a zero-cost data stack, which is also why prices are **delayed** (~15 min, Yahoo Finance) rather than live-tick.

---

## 3. Feature Tour (user-facing)

### 3.1 Search
Type-ahead search (`SearchBar.js`) merging the local NSE directory (instant, full company names) with a live Yahoo Finance search for anything not in the local list. 300ms debounce, Enter-to-search fallback for symbols not found by name.

### 3.2 Watchlist (far-left sidebar)
Persistent list of tracked symbols (`Watchlist.js`). Shows live LTP (polled every 30s via `/api/watchlist/pulse`), an alert badge (🔔) when alerts are armed/triggered, and one-click removal. Clicking a row opens that stock's full research page.

### 3.3 Saved Screens
A named, re-loadable snapshot of a screener universe — e.g. save "Pharma Watch" as a specific list of 12 tickers, reload it any time without retyping. Backed by the `saved_screens` table (upsert-on-name, deduped, order-preserved). Sits above the Watchlist in the sidebar; the Save button is disabled until a screen has actually run.

### 3.4 Price Alerts
Per-stock price-level alerts (`alert_store.py`), either custom (user-picked level/direction) or **auto-armed from a trade plan** — one click on "🔔 Monitor this plan" creates an entry, stop, and one alert per target level in a single call. Checked every 30s against delayed Yahoo Finance prices while the app is open (explicitly *not* a broker GTT substitute — the UI says so). Triggered alerts surface as toast notifications and in a collapsible Alerts panel; can be acknowledged or deleted.

### 3.5 Master Screener (batch ranking)
The centerpiece bulk-analysis tool (`Screener.js`, 688 lines). Paste up to 500 tickers/company names (or upload a `.txt`/`.csv`), and it:
- Resolves free-text names to NSE symbols (`/api/resolve`)
- Streams results progressively over SSE (`/api/screen-stream`) in batches of 25, so the table fills in live rather than waiting for all 500 to finish
- Cross-sectionally ranks every stock against the others in the same run (momentum/quality/value/low-risk composite, see §4.2)
- Renders through a **custom virtualized list** (fixed 86px rows, `ResizeObserver`-measured viewport, only the visible slice + overscan in the DOM) so a 500-row run never taxes the browser
- **Per-row display**: rank, symbol, PARTIAL badge (price-only rows with no fundamentals), **LTP + daily % change** (monospace, green/red), Master Score, two semantic "lens" chips (Fund: Strong/Weak/Neutral/N/A and Chart: Breakout/Pullback/Breakdown/Uptrend/Range), a speculative-setup warning triangle (weak fundamentals + strong chart action disagreeing), and three factor micro-bars (M/Q/V) with hover tooltips
- **Quick-view filters**: `ALL` / `BUY ZONE` (verdict Buy or Buy on Dip) / `WAIT` (pending breakouts or extended/overbought setups), each showing a live count, filtering the rendered list instantly client-side
- "Refresh List" re-streams the current universe using cached fundamentals (skips re-scraping, just re-pulls prices and re-ranks)

### 3.6 Stock Detail Workspace (main panel)
Opened by clicking any search result, watchlist item, or screener row. A dashboard grid of cards, in order:

1. **Overview Card** — company identity, sector/industry, live price + day change, a "Delayed Data" disclosure chip, a fundamentals-freshness chip (cache age / stale flag), a **Dual Conviction** readout (two independent 0–100 scores: *Technical Trend Setup Strength* and *Fundamental Corporate Health* — kept separate rather than blended into one ambiguous number), an interactive price chart (1M/3M/6M/1Y ranges, recharts) with trade-plan levels overlaid (entry zone band, stop line, target lines) and volume bars tagged HVE/HVY/HVQ, plus a fundamentals metrics grid (P/E, P/B, ROE, ROCE, D/E, dividend yield, book value, promoter holding %, pledge % with a warning if &gt;5%).
2. **Gatekeeper override** *(conditional)* — when the swing plan's verdict is `Avoid` or price is below the 200-DMA, the entire trade-planning UI is replaced by a hard-stop red banner explaining why, so a broken setup can never be accidentally acted on. Reappears as normal once the structure repairs.
3. **Factor Report Card** *(only when opened from a screener run)* — the four winsorized z-score factor bars (Momentum 35%, Quality 30%, Value 20%, Low-Risk 15%) behind that stock's screener rank, so a disagreement between "the chart looks great" and "the composite score is mediocre" is explained visually.
4. **Trade Plan** — the full output of the Decision Engine (see §4.3): horizon tabs (Swing / Positional), a verdict banner (Buy / Buy on Dip / Wait / Avoid) with a confidence bar, entry/stop/target price tiles (click-to-copy, GTT offset % vs. last close), a fundamentals gate readout, and **"The Case"** — a bull-vs-bear evidence ledger with a visual tug-of-war bar, historical base-rate statistics for this exact setup on this exact stock (win rate with a Wilson 95% confidence interval, expected R, median holding period, regime-matched sub-stats), price-action/volume chips (OBV divergence, distribution days, pocket pivots, VCP tightening, etc.), a collapsible Minervini Trend Template checklist (8-point pass/fail), and relative-strength-vs-NIFTY stats. A "🔔 Monitor this plan" button arms alerts in one click.
5. **AI Alpha Thesis** — Gemini-generated analysis (see §4.4): a conviction gauge (SVG doughnut, 0–100), thesis summary, a steel-manned bull case next to the AI's own strongest bear attack, a full **Bear Case Ledger** (every attack with its cited evidence, a 1–10 severity score, and the condition that would refute it), red flags, key catalysts, valuation view, and suggested action.
6. **Quarterly Results** + **Shareholding Pattern** (side by side) — quarterly revenue/profit/OPM trend table+chart, and promoter/FII/DII/retail shareholding with QoQ deltas and BSE corporate announcements.
7. **Audit Trail** (sticky tabbed footer) — three collapsible deep-dive tabs: Technicals & Structural Signals, Fundamental Financial Audits (full Piotroski/Altman/DuPont/Beneish breakdown), and News & Filings Log. Kept out of the main scroll so the page stays decision-focused by default.

### 3.7 In-App Guide
A full guided walkthrough (`GuideView.js`) using a fictional stock ("DEMOTECH") rendered through the **exact same production components** as a real stock page, with explanatory callouts interleaved — teaches a new user what every score, chip, and chart annotation means without needing to already understand the methodology. Toggled via a floating action button.

---

## 4. Backend — Engine-by-Engine Detail

The backend is organized as: `routers/` (HTTP surface, thin) → `stock_service.py` (orchestration) → engines (`quant_engine`, `swing_engine`, `decision_engine`, `conviction_engine`, `ai_engine`, `price_action`) → data layer (`price_service`, `data_cache`, `screener_scraper`, `symbol_resolver`, `qualitative_engine`, `db`).

### 4.1 Fundamental Quant Scoring — `quant_engine.py`

| Score | Method | Output |
|---|---|---|
| **Piotroski F-Score** | 9 binary signals across Profitability / Leverage / Efficiency (ROA&gt;0, CFO&gt;0, ΔROA&gt;0, CFO&gt;ROA "earnings quality", Δdebt/assets&lt;0, Δcurrent ratio&gt;0, no dilution, Δmargin&gt;0, Δasset turnover&gt;0) | 0–9, banded Strong(≥8)/Good(≥6)/Average(≥4)/Weak(≥2)/Distressed |
| **Altman Z″** | Emerging-market model: `6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4` (WC/TA, RE/TA, EBIT/TA, Equity/Liabilities) | Zones: Safe &gt;2.6, Grey 1.1–2.6, Distress ≤1.1 |
| **DuPont ROE** | 3-way decomposition: `ROE = Net Margin × Asset Turnover × Equity Multiplier`, 5-year trend + primary-driver diagnosis | margin/efficiency/leverage-driven label |
| **Beneish M-Score** | 8-variable earnings-manipulation model (DSRI, GMI, AQI, SGI, DEPI, SGAI, TATA, LVGI) | M &gt; -1.78 = probable manipulator; -2.22 to -1.78 = grey; ≤ -2.22 = clean |
| **Magic Formula** | Greenblatt Earnings Yield (EBIT/EV) + Return on Capital (EBIT/(NWC+NFA)), combined rank | (used in cross-sectional context) |
| **Composite Quality (0–100)** | `40×(Piotroski/9) + 30×norm(AltmanZ, 1.1→6.0) + 30×min(ROE/30,1)` | single blended fundamentals score |

*(Note: the Altman model was deliberately corrected in the project's history — commit `e4af4e1` removed an incorrectly-mixed +3.25 bond-rating constant that was inflating every score.)*

### 4.2 Price Factors & Cross-Sectional Ranking — `swing_engine.py`

Per-stock price factors from daily OHLCV: multi-horizon returns (1M/3M/6M), classic 12-1 momentum, 52-week-high proximity, Wilder RSI(14), MACD histogram, Wilder ATR(14) + ATR%, annualized volatility, risk-adjusted momentum (return/vol), a trend score from MA50/MA200 relationships, and volume ratio (20d avg / 60d avg).

**Cross-sectional ranking** (what powers the Master Screener):
1. Winsorize each factor at the 5th/95th percentile within the current run
2. Z-score everything
3. Group into four factors and average member z-scores: **Momentum (35%)**, **Quality (30%)**, **Value (20%)**, **Low-Risk (15%)**
4. Weighted composite z-score → **`score = Φ(composite) × 100`** (normal-CDF percentile, 0–100)
5. Hard flags override the score into `Avoid`: Beneish manipulation, Altman distress, Piotroski ≤3, RSI &gt;75, below the 200-DMA
6. Verdict bands: Strong Candidate (≥70 + trend≥1 + Piotroski≥6) / Buy Watch (≥60) / Neutral (≥40) / Avoid

### 4.3 Trade Decision Engine — `decision_engine.py`

Turns candles + factors + quant into **structure-anchored** (not indicator-blind) trade plans across two horizons.

- **Pivots**: fractal swing highs/lows over the trailing 250 bars, clustered within 1.5% into weighted support/resistance levels.
- **Setup detection** (priority order): `breakout` (near resistance/52w-high + volume surge + uptrend, with a bar-quality check for false breakouts), `pullback` (uptrend, RSI reset to 35–55, pulling into a rising MA50/support, with pullback-volume character checked), `trend_continuation` (strong uptrend, RSI 50–70, positive MACD, headroom to resistance), or `none`.
- **Swing plan** (days–weeks): entry zone from the detected setup, stop = 2×ATR below entry (tightened to structure if a nearer support exists, further refined against 1H/15m intraday pivots when available), targets at 1.5R/2.5R (capped at nearby resistance). Verdict: Buy (in zone) / Buy on Dip (above zone) / Wait (below zone, overbought, or R:R &lt;1.2) / Avoid (downtrend).
- **Positional plan** (weeks–months): gated by fundamentals (hard-fail on manipulation/distress flags kills the plan outright; soft-fail on weak Piotroski/composite caps the verdict at Wait even if technicals say Buy). Entry near 52w-high/MA50/support depending on setup; stop at the nearest major swing-low or MA200; target via a measured-move projection (60-day range height, capped at +25%); fixed trailing-stop exit rule (close below the 50-DMA).
- Every plan ships a fixed disclaimer: "Educational analysis only — not investment advice. Price data is delayed (Yahoo Finance)."

### 4.4 Conviction Engine — `conviction_engine.py` (the largest engine, 849 lines)

Produces the 0–100 "conviction" score and the full evidence dossier behind "The Case" in the Trade Plan card.

- **Setup base rates**: an event study that replays the *stock's own history* — every time this exact setup fired historically, simulate the trade (2×ATR stop, 1.5R target, 40-bar max hold) and report win rate (with a **Wilson 95% confidence interval**, not a naive point estimate), expected R, and median holding period. Confidence tiers (insufficient/low/moderate/high) based on sample size gate the weight given to the result.
- **Regime-conditioning**: NIFTY is classified as `up`/`recovering`/`down` on every historical date, and base-rate stats are also computed for just the subset of historical signals that fired in a regime matching *today's* — because "this setup wins 60% overall" is misleading if that 60% only happened in bull markets and today is a downtrend.
- **Trend Template** (Minervini 8-point checklist): MA stacking, MA200 direction, price vs. 52w range, relative strength vs. NIFTY, volume character, minimum price floor, volatility contraction.
- **Relative Strength vs. NIFTY**: excess return at 1M/3M/6M, beta (covariance-based), and RS-line-at-new-high detection.
- **Market Regime**: NIFTY trend + volatility percentile + drawdown + O'Neil distribution-day count → Risk-On / Neutral / Risk-Off, each with an actionable guidance string.
- **The evidence ledger** (`build_case`): an additive bull/bear point system across setup quality, trend template, base-rate EV (regime-multiplier-adjusted: 0.6× in Risk-Off, 1.2× in Risk-On for momentum-dependent setups), relative strength, fundamentals, live price-action signals, market regime, and plan risk:reward — summing to `conviction = clamp(50 + bull − bear, 2, 98)`.
- **"The Bottom Line"** (`synthesize_verdicts`): reconciles the Trade Setup lens, the Business Quality lens, and the AI Analyst lens into one of six named patterns (`aligned_bull`, `momentum_trade` — "rent it, don't own it", `quality_watch` — "stalk it", `no_edge`, `mixed`, `hard_disqualified`), each with horizon-specific directives, and flags when the AI's independent score disagrees sharply (≥20 points) with the quant score.

### 4.5 AI Analyst — `ai_engine.py`

Direct REST calls to the Gemini API (`gemini-2.5-flash` by default, no SDK dependency) with a system prompt that explicitly casts the model as **"the Devil's Advocate on an Indian-equities investment committee"** — an aggressive risk officer whose job is to attack the bull case before capital is committed. Hard constraints baked into the prompt: the model may never calculate or estimate a number itself — every figure must be cited verbatim from the data it's given (ratios, quarterly trends, quant scores, trade-plan levels, sentiment). It's explicitly allowed to concede if the case is genuinely strong.

Structured JSON output is enforced via Gemini's `responseMimeType: application/json`, temperature 0.15. Returns a conviction score/label, thesis summary, steel-manned bull case, a strongest bear-case headline, a full **bear case ledger** (attack + verbatim evidence + severity 1–10 + the condition that would refute it), red flags, catalysts, valuation view, and a plan commentary. Resilient by construction: retries on 429/503/500 with backoff, strips markdown fences, and **never raises** — an unset API key or any failure produces a clean "AI analysis unavailable" response rather than breaking the page.

### 4.6 Price-Action / Volume Forensics — `price_action.py`

Institutional-footprint detectors, described in-code as "the present-day confirmation layer" (complementing the conviction engine's historical base rates): OBV divergence, Chaikin Accumulation/Distribution line direction, up/down volume ratio, O'Neil distribution-day count, pocket pivots (Kacher/Morales), pullback-volume character (dry-up vs. expansion), market structure (HH/HL uptrend vs. LH/LL downtrend from raw pivots), VCP-style volatility-contraction tightness + NR7, climax-volume exhaustion detection, and trailing (no-lookahead) **volume anomaly tagging** — HVE (highest volume ever), HVY (highest in a year), HVQ (highest in a quarter) — which show up as the annotated bars on the price chart.

### 4.7 Data Layer

- **Prices**: exclusively **Yahoo Finance** via `yfinance` (no API key, no paid vendor) — explicitly delayed (~15 min) and documented as unsuitable for execution timing. `auto_adjust=True` is used deliberately so dividends/splits don't create false gaps in MAs/RSI/ATR or falsely trigger backtested stops.
- **Fundamentals**: **Screener.in is primary** (scraped via `httpx` + BeautifulSoup, with a resolve-canonical-slug retry cascade for renamed/mismatched tickers), with **Yahoo Finance's reported financial statements overlaid** on specific fields Screener approximates less reliably (e.g., current assets/liabilities, which Screener's consolidated view doesn't break out directly).
- **Caching**: per-symbol fundamentals cache in the database, 4-hour TTL (tunable via a `settings` key), single-flight de-duplication (concurrent requests for the same cold symbol share one fetch), and **stale-on-error** fallback — if a live fetch fails, the last good copy is served and explicitly flagged stale rather than the page breaking.
- **Symbol resolution**: a 4-stage cascade (exact match against the official NSE directory → fuzzy token-overlap name match → Screener.in's own search API for anything not yet in the directory → symbol-shaped passthrough), backed by a weekly-refreshed cache of NSE's official equity list (~2,400 symbols).
- **News & filings**: Google News RSS per stock, plus BSE India's corporate-announcements API (scrip code resolved via BSE's own autocomplete). Both feed a hand-rolled finance-domain sentiment lexicon (not a general NLP library) that weights phrases like "record profit" or "SEBI notice" and hard-flags red-flag terms (fraud, CBI probe, promoter pledge, going-concern) regardless of surrounding positive language.
- **Legacy/unused**: `kite_bridge.py` is a standalone, unmounted FastAPI app wrapping the real Zerodha Kite Connect API — the original price-data path before the migration to Yahoo Finance. `kite_mcp_bridge.py` is a non-functional stub. Neither is imported by `main.py`; both are retained for reference only.

### 4.8 Persistence — `db.py`

Dual-backend by design (see §1): **Postgres when `DATABASE_URL` is set, SQLite otherwise** (local dev default, zero config). Every public function has an identical signature on both backends, so no caller code differs by environment. Five tables: `watchlist`, `alerts`, `settings` (JSON-encoded key/value), `fundamentals_cache`, `saved_screens`. The SQLite path also auto-migrates any legacy `watchlist.json`/`alerts.json` files on first run.

### 4.9 Alerts — `alert_store.py`

An alert is `{symbol, exchange, kind, level, direction, status, ...}`; `direction="above"` fires at `ltp ≥ level`, `"below"` at `ltp ≤ level`; once triggered, an alert never refires. `create_from_plan` auto-arms a full set (entry re-entry alert, stop alert, one alert per target) from a single trade-plan horizon in one call, replacing any prior alert set for that `(symbol, horizon)` pair. Checked on a 30-second poll against delayed prices — explicitly advisory, not a broker-GTT replacement.

---

## 5. API Reference

All routes are prefixed `/api/`. No auth layer — this is a single-user personal tool. 22 endpoints across 4 routers.

**`routers/stocks.py`** — search, single-stock research, plans, AI
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/search` | Autocomplete (local NSE directory + Yahoo Finance) |
| POST | `/api/resolve` | Resolve free-text names/symbols to NSE tickers (batch, max 500) |
| GET | `/api/stock/{symbol}` | Full research payload — price history, fundamentals, technicals, news |
| GET | `/api/stock/{symbol}/plan` | Trade Decision Engine — swing + positional plans, conviction dossier |
| GET | `/api/stock/{symbol}/alpha` | Everything above + quant scores + Gemini AI thesis (slowest endpoint) |
| GET | `/api/market-regime` | NIFTY tape check (Risk-On/Neutral/Risk-Off), 30-min cache |
| GET | `/api/ltp/{symbol}` | Last traded price for one instrument |

**`routers/watchlist.py`** — watchlist, live prices, alerts
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/watchlist` | List watchlist entries |
| POST | `/api/watchlist` | Add a symbol |
| DELETE | `/api/watchlist/{symbol}` | Remove a symbol |
| GET | `/api/watchlist/prices` | Batch LTPs for the whole watchlist |
| GET | `/api/alerts` | List alerts (optional `symbol` filter) |
| POST | `/api/alerts` | Create a custom alert |
| POST | `/api/alerts/from-plan` | Auto-arm entry/stop/target alerts from a trade plan |
| DELETE | `/api/alerts/{alert_id}` | Delete an alert |
| POST | `/api/alerts/{alert_id}/ack` | Acknowledge a triggered alert |
| GET | `/api/watchlist/pulse` | 30s poll: LTPs + newly-triggered alerts + per-symbol alert counts |

**`routers/screener.py`** — batch screener
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/screen-stream` | SSE stream: up to 500 symbols, batched (25/batch, concurrency 6), progressive `batch` events then a final cross-sectionally-ranked `result` |

**`routers/screens.py`** — saved screens
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/screens` | List saved screens (metadata only) |
| POST | `/api/screens` | Create/upsert a saved screen (name + ticker array) |
| GET | `/api/screens/{screen_id}` | Full saved screen (with tickers) |
| DELETE | `/api/screens/{screen_id}` | Delete a saved screen |

---

## 6. Frontend Architecture

**Layout** (`App.js` + `App.css`): a locked three-pane viewport shell — `.sidebar` (Watchlist/Saved Screens, self-scrolling), `.master-panel` (the Screener, collapsible), `.main-content` (search bar fixed, detail view scrolling independently). Collapses to a stacked, page-scrolling layout below ~860px (tablet/phone).

**No global state library.** `App.js` owns the "currently open stock" state and passes callbacks down; each feature component (`Screener`, `Watchlist`, `TradePlan`, etc.) manages its own local state and talks to the backend directly via `api.js` (a thin axios wrapper — one exported function per endpoint).

**Component inventory:**
| Component | Role |
|---|---|
| `App.js` | Layout shell, top-level state, phase-1/1.5/2 load orchestration |
| `SearchBar.js` | Debounced autocomplete |
| `Watchlist.js` (incl. `SavedScreensPanel`) | Sidebar: saved screens + watchlist + alerts panel |
| `Screener.js` | Master batch screener: SSE streaming, virtualization, filters |
| `OverviewCard.js` | Identity, price, dual-conviction chips, price chart |
| `Gatekeeper.js` | Hard-stop override UI for broken setups |
| `FactorReportCard.js` | Screener-rank factor breakdown (M/Q/V/Low-Risk bars) |
| `TradePlan.js` | Verdict banner, entry/stop/target tiles, "The Case" evidence ledger |
| `AlphaThesis.js` | Gemini AI thesis, conviction gauge, bear-case ledger |
| `QuantScores.js` | Piotroski (9-signal breakdown) / Altman / DuPont / Beneish detail |
| `QuarterlyResults.js`, `Shareholding.js`, `NewsFeed.js`, `Technicals.js` | Supporting data panels |
| `AuditTabs.js` | Sticky tabbed footer housing the above three deep-dive panels |
| `MarketRegime.js` | NIFTY regime banner |
| `GuideView.js` + `guideData.js` | Full fictional-stock guided walkthrough |
| `InfoTip.js` | Reusable hover-tooltip for metric definitions (`metricInfo.js`) |

**Rendering technique of note:** the Master Screener implements its own list virtualization (no dependency) — fixed row height, `ResizeObserver`-measured viewport, absolute-positioned visible slice + overscan — so a 500-row screen only ever mounts a few dozen DOM nodes.

---

## 7. Deployment

| Concern | How it's handled |
|---|---|
| Frontend build | Vercel, builds from `main`. `REACT_APP_API_URL` set as a Vercel env var (build-time, requires rebuild to change) |
| Backend | Render (`render.yaml` blueprint), free web plan, `uvicorn main:app` |
| Database | `DATABASE_URL` env var on Render → external Postgres (Neon recommended for a permanently-free tier; Render's own managed free Postgres expires after ~30 days) |
| Secrets | `GEMINI_API_KEY` set directly in the Render dashboard (not committed); `.env.example` documents every variable the app reads |
| CORS | Backend allows any `*.vercel.app` origin plus local dev hosts — no per-deployment CORS config needed |

**To stand this up fresh:** deploy `backend/` to Render (or any ASGI host) with `GEMINI_API_KEY` and `DATABASE_URL` set; deploy `frontend/` to Vercel (or any static host) with `REACT_APP_API_URL` pointed at the backend's public URL; point `DATABASE_URL` at any Postgres instance (Neon's free tier works with zero code changes, since `db.py` speaks standard Postgres via `psycopg`).

---

## 8. Known Issues / Technical Debt

- **`routers/stocks.py`** calls `asyncio.gather(...)` in the `/api/search` handler but never imports `asyncio` in that file — this is a latent `NameError` bug that would surface the first time that code path actually executes. Worth a one-line fix (`import asyncio`).
- **`vaderSentiment`** is listed in `requirements.txt` but neither `qualitative_engine.py` nor `screener_scraper.py` actually uses it — both implement their own hand-rolled lexicon scorer instead. Likely dead weight, or a leftover from an earlier iteration.
- **`kite_bridge.py` / `kite_mcp_bridge.py`** are unmounted, unused legacy code from a discontinued Zerodha Kite Connect integration (superseded by the Yahoo Finance price path). Safe to remove if not planned for revival.
- **No auth layer** anywhere — acceptable for a single-user personal tool, but relevant if this is ever shared or multi-tenant.
- **Screener.in scraping** is inherently fragile to upstream HTML changes; the resolve-slug retry cascade and yfinance overlay mitigate but don't eliminate this risk.

---

## 9. Development Timeline (condensed)

Reconstructed from commit history, oldest to newest:

1. **Initial build** — core stock research page, basic fundamentals.
2. **Trade decision engine v1** — conviction dossier, price-action layer added.
3. **Altman Z-Score correction** — emerging-market model adopted; fixed a score-inflation bug from an incorrectly mixed constant.
4. **UI overhaul** — master-detail workspace, Gatekeeper hard-stop, unified Kite/GTT execution helper, Trade Setup card consolidation.
5. **Resilient data layer** — SQLite persistence (replacing raw JSON files) + 4-hour fundamentals TTL cache introduced.
6. **Conviction v2** — regime-conditioned base rates, Wilson confidence intervals, sample-size safeguards, and the Gemini "Devil's Advocate" AI rework (structured bear-case ledger).
7. **OPM/sector/intraday precision pass** — quarterly OPM%, sector tagging, intraday (1H/15m) stop refinement, volume-anomaly (HVE/HVY/HVQ) chart annotations.
8. **Screener limit raised to 500**; 15-minute intraday stop fallback; visible stop-timeframe badge.
9. **Backend scale-up** — resilient fundamentals cascade (Screener → slug retry → yfinance fallback with completeness flags), chunked async SSE batch streaming for the screener, named watchlist persistence groundwork.
10. **Frontend scale-up** — progressive SSE consumption, custom list virtualization, semantic Fund/Chart chips with a speculative-disagreement warning, factor tooltips.
11. **Save Screen feature** — `saved_screens` table + sidebar panel (save/load/delete named ticker lists), retiring an earlier unused plural-`watchlists` prototype.
12. **Delete control** for saved screens wired into the UI.
13. **Layout hardening** — fixed overfill/overflow bugs, mobile/iPad responsive tiers, a locked full-height app shell with independently-scrolling panes (current layout).
14. **Screener pricing + quick filters** (this session) — LTP + daily % change added to every screener row; `ALL`/`BUY ZONE`/`WAIT` quick-view filter bar with live counts.
15. **Durable persistence** (this session) — root-caused the disappearing watchlist/saved-screens bug to Render's ephemeral free-tier disk; made the data directory configurable, then added a dual SQLite/Postgres backend to `db.py` (verified end-to-end against a live Postgres instance, including cross-process persistence), wiring `DATABASE_URL` through `render.yaml`.
16. **Branch promotion** — merged the pricing/filters/persistence work from the `feature/v6` development branch into `main` (the branch Vercel actually builds from) via PR, since it had been merged into `feature/v6` but not yet reached production.

---

## 10. Glossary (quick reference)

- **LTP** — Last Traded Price (delayed ~15 min here, sourced from Yahoo Finance).
- **Piotroski F-Score** — 0–9 fundamental strength score from 9 yes/no financial-health signals.
- **Altman Z″** — bankruptcy/distress risk score; here the emerging-market variant (no US-manufacturer-only terms).
- **Beneish M-Score** — statistical likelihood a company is manipulating earnings.
- **R-multiple** — profit/loss expressed as a multiple of the initial risk (e.g., "+1.5R" = gained 1.5× what was risked).
- **Wilson confidence interval** — a small-sample-safe way to state the plausible range for a win rate, used instead of a naive percentage that overstates confidence on thin samples.
- **VCP** — Volatility Contraction Pattern, a Minervini/O'Neil concept where successive pullbacks tighten before a strong breakout.
- **Distribution day** — an O'Neil concept: a heavy-volume down day, read as institutional selling.
- **Regime** — the prevailing market trend/volatility state (Risk-On / Neutral / Risk-Off), used to condition how much weight historical base rates deserve.
