import React, { useState } from 'react';
import OverviewCard from './OverviewCard';
import TradePlan from './TradePlan';
import FactorReportCard from './FactorReportCard';
import Gatekeeper from './Gatekeeper';
import QuantScores from './QuantScores';
import Technicals from './Technicals';
import Shareholding from './Shareholding';
import QuarterlyResults from './QuarterlyResults';
import MarketRegime from './MarketRegime';
import { demoStock, demoPlan, demoBrokenPlan, demoQuant, demoRow } from '../guideData';
import './GuideView.css';

/* Explainer callout rendered between the real components */
function Note({ icon = '💡', title, children }) {
  return (
    <div className="guide-note">
      <div className="guide-note-title">{icon} {title}</div>
      <div className="guide-note-body">{children}</div>
    </div>
  );
}

export default function GuideView({ onClose }) {
  const [horizon, setHorizon] = useState('swing');

  return (
    <div className="dashboard-grid guide-view">

      {/* ── intro ── */}
      <div className="card guide-hero">
        <div className="guide-hero-top">
          <div>
            <div className="guide-hero-title">📖 How StockLens decides</div>
            <div className="guide-hero-sub">
              A guided walkthrough using <strong>DEMOTECH — a fictional stock</strong> —
              rendered through the exact same components as a real research page.
              Every number below is a worked example of what the app computes for
              any NSE stock you open.
            </div>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>✕ Exit guide</button>
        </div>
        <div className="guide-hero-grid">
          <div><strong>The philosophy:</strong> StockLens is a decision tool, not a data terminal.
            Every verdict must argue its case with evidence — historical base rates, market
            structure, institutional volume footprints, forensic accounting — so you can
            audit the reasoning, not trust a label.</div>
          <div><strong>Where the data comes from:</strong> Yahoo Finance (prices —
            dividend-adjusted daily candles, ~15 min delayed), yfinance reported financial
            statements (primary fundamentals), Screener.in (fallback fundamentals),
            BSE filings, Google News, and Gemini for the AI thesis. Sources degrade
            gracefully — a failed scrape never invents numbers.</div>
          <div><strong>What it is not:</strong> not investment advice, not live execution data,
            and not a substitute for broker-side GTT orders. Every plan carries that
            disclaimer for a reason.</div>
        </div>
      </div>

      {/* ── 1. market regime ── */}
      <Note icon="🌡️" title="1 · Market Regime — the first filter">
        Before judging any stock, institutions check the tape. The banner tracks the NIFTY's
        trend (price vs its 50/200-day averages), realized-volatility percentile, drawdown from
        the 52-week high, and <em>distribution days</em> (heavy-volume down days = institutional
        selling). Most long setups fail in a Risk-Off tape no matter how good the chart looks —
        so the regime gates every verdict below. Here DEMOTECH enjoys a Risk-On tape.
      </Note>
      <MarketRegime regime={demoPlan.dossier.regime} />

      {/* ── 2. overview ── */}
      <Note icon="🪪" title="2 · The header — price, dual conviction, and honesty about data">
        The two chips answer <em>different questions</em>: <strong>Technical Trend Setup
        Strength</strong> (is this a good trade for the next days–weeks?) and
        <strong> Fundamental Corporate Health</strong> (is this a good business for
        quarters–years?). They often disagree — that disagreement is information, not noise.
        The amber badge admits the quotes are ~15 minutes delayed; the chart shades the
        <span className="guide-green"> target channel</span> and
        <span className="guide-red"> risk channel</span> from the trade plan, draws entry/stop/target
        lines, and shows volume bars (green/red by up/down day) — volume is the footprint
        institutions can't hide. Key ratios below the chart: P/E (price per ₹1 of profit),
        P/B, ROE/ROCE (business quality), debt/equity (fragility), promoter pledge (forced-selling risk).
      </Note>
      <OverviewCard data={demoStock} planLevels={demoPlan[horizon]} synthesis={demoPlan.synthesis} demo />

      {/* ── 3. trade plan ── */}
      <Note icon="🎯" title="3 · The Trade Plan — exactly what to do, and what would prove it wrong">
        <p>The engine detects the current <strong>setup</strong> (breakout / pullback /
        trend-continuation) and builds a complete plan:</p>
        <ul>
          <li><strong>Entry zone</strong> — a band, not a point, anchored to structure
            (here: the rising 50-DMA where buyers previously defended).</li>
          <li><strong>Stop loss</strong> — 2×ATR math <em>floored by structure</em>: if a pivot
            support sits closer, the stop tightens below it. ATR (Average True Range) is the
            stock's typical daily movement — stops sized in ATRs don't get shaken out by noise.</li>
          <li><strong>Targets</strong> — R-multiples of your risk (T1 = 1.5R means: 1.5× the
            distance to your stop), capped at overhead resistance where sellers wait.
            The <strong>GTT %</strong> chips are pre-computed offsets you can paste straight
            into a Zerodha GTT order.</li>
          <li><strong>Invalidation</strong> — the price that proves the idea wrong. A plan
            without an exit condition is a hope, not a plan.</li>
        </ul>
        <p>Below it, <strong>The Case</strong> is the evidence stack: the weighted bull/bear
        ledger nets to the conviction score, the <strong>base rates</strong> box replays every
        historical occurrence of this same setup on this stock (here: 16 pullbacks since 2021,
        62% hit target first, +0.55R expected value per trade — the single most honest number
        in the app), the Minervini trend template is an auditable 8-point checklist, and the
        price-action chips summarize volume forensics (OBV, distribution days, pocket pivots,
        pullback volume dry-up). Toggle Swing/Positional — the positional plan adds a
        fundamentals gate and a trailing exit rule instead of a fixed T2.</p>
      </Note>
      <TradePlan data={demoPlan} loading={false} horizon={horizon}
                 onHorizonChange={setHorizon} symbol="DEMOTECH" readOnly
                 aiCommentary="I agree with the Buy: the 62% base rate and volume dry-up outweigh the stretched P/E — but respect the stop; valuation offers no cushion if the setup fails." />

      {/* ── 4. factor report card ── */}
      <Note icon="🧮" title="4 · Factor Report Card — how the screener ranks (z-scores)">
        When you open a stock from a screener run, you see its four factor composites
        <em> relative to the other stocks in your list</em>, as winsorized z-scores
        (0 = group average, +1σ = clearly stronger). The model weights are printed on each
        bar: Momentum 35%, Quality 30%, Value 20%, Low-Risk 15% — a swing-trading tilt.
        DEMOTECH ranks high on momentum and quality but <em>negative on value</em> (it's
        expensive) — which is exactly why a strong composite can coexist with a stretched P/E.
      </Note>
      <FactorReportCard row={demoRow} />

      {/* ── 5. gatekeeper ── */}
      <Note icon="🚫" title="5 · The Gatekeeper — what a broken stock looks like">
        When a stock trades below its 200-day average or the verdict is Avoid, StockLens
        refuses to show a trade plan at all — the planning space is replaced by this block and
        the execution helpers disappear. This is deliberate: the most expensive retail mistake
        is buying falling knives because a tool kept offering levels for them. Example below
        (a second fictional stock):
      </Note>
      <Gatekeeper planData={demoBrokenPlan} />

      {/* ── 6. fundamentals ── */}
      <Note icon="🧾" title="6 · Forensic fundamentals — is the business real?">
        <ul>
          <li><strong>Piotroski F-Score (0–9)</strong> — nine yes/no checks of improving
            fundamentals across profitability, leverage and efficiency. Click any badge to see
            the measured data behind it. 8–9 excellent; ≤3 deteriorating. DEMOTECH scores 7 —
            its two misses (liquidity, asset turnover) are shown with the exact numbers.</li>
          <li><strong>Altman Z″-Score</strong> — bankruptcy-risk model (emerging-market variant:
            6.56·X₁ + 3.26·X₂ + 6.72·X₃ + 1.05·X₄ over working capital, retained earnings,
            EBIT and equity vs liabilities). Above 2.6 = Safe; below 1.1 = distress risk.
            Computed from <em>reported</em> statements (yfinance) with true EBIT, not EBITDA.
            Not meaningful for banks/NBFCs.</li>
          <li><strong>DuPont decomposition</strong> — splits ROE into margin × turnover ×
            leverage, revealing <em>where</em> returns come from. Margin-led ROE (like here) is
            durable; leverage-led ROE is fragile.</li>
          <li><strong>Beneish M-Score</strong> (runs behind the scenes, feeds the evidence
            ledger) — an 8-ratio forensic test for earnings manipulation. Above −1.78 the
            accounting resembles known manipulators and the stock is hard-disqualified,
            whatever the chart says.</li>
        </ul>
      </Note>
      <QuantScores data={demoQuant} loading={false} />

      {/* ── 7. technicals ── */}
      <Note icon="📐" title="7 · Technical snapshot — trend, momentum, and market sensitivity">
        The 50-DMA is the medium-term trend, the 200-DMA the long-term line institutions watch;
        price above both, with the 50 above the 200, defines an uptrend. <strong>RSI (14)</strong>
        measures momentum velocity: above 70 = overbought (chasing), below 30 = oversold, and the
        40–55 zone during an uptrend pullback (DEMOTECH: 47.8) is where the best entries live.
        <strong> Beta vs NIFTY</strong> says how hard the stock moves per 1% of index move —
        1.12 means slightly amplified swings, so expect the regime to matter.
      </Note>
      <Technicals data={demoStock.technicals} livePrice={demoStock.live_price} dossier={demoPlan.dossier} />

      {/* ── 8. quarterly + shareholding ── */}
      <Note icon="🏛️" title="8 · Growth trajectory & who owns the stock">
        Quarterly bars show whether revenue/profit are actually compounding (DEMOTECH: four
        rising quarters). The shareholding chart shows the register: rising <strong>FII</strong>
        holdings = foreign institutions accumulating (a strong tell), stable
        <strong> promoter</strong> holding = skin in the game, and <strong>promoter pledge</strong>
        is the silent killer — pledged shares can be force-sold by lenders on a decline,
        accelerating crashes. The footprint panel underneath surfaces insider/SAST/block-deal
        filings from the BSE feed.
      </Note>
      <div className="grid-row-2">
        <QuarterlyResults data={demoStock.quarterly_results} />
        <Shareholding data={demoStock.shareholding} announcements={[]} />
      </div>

      {/* ── 9. workflow ── */}
      <div className="card guide-workflow">
        <div className="guide-note-title">🧭 9 · The intended workflow</div>
        <ol>
          <li><strong>Check the regime banner.</strong> Risk-Off? Demand A-grade setups or stand aside.</li>
          <li><strong>Screen.</strong> Paste symbols or full company names in the left panel — every stock gets
            ranked by the weighted factor model, with verdict and plan chips.</li>
          <li><strong>Open the best candidates.</strong> Read the Trade Plan levels, then audit The Case:
            do the base rates, the checklist, and the volume forensics agree? Where does the AI dissent?</li>
          <li><strong>Act only on plans that survive.</strong> Copy the GTT offsets into your broker,
            click <em>Monitor this plan</em> so the watchlist alerts fire when entry/stop/target levels
            are hit (checked every 30s on delayed data while the app is open).</li>
          <li><strong>Respect the invalidation.</strong> The plan tells you in advance what proves it wrong —
            when that prints, you exit. Never average down a failed trade into an "investment."</li>
        </ol>
        <div className="guide-disclaimer">
          Educational analysis only — not investment advice. All data delayed; DEMOTECH and every
          number on this page are fictional, crafted to be internally consistent for teaching.
        </div>
      </div>
    </div>
  );
}
