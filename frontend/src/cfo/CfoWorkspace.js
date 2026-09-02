import React, { useCallback, useEffect, useMemo, useState } from 'react';
import LegacyResearch from '../App';
import SearchBar from '../components/SearchBar';
import { PriceChart } from '../components/OverviewCard';
import {
  getCandidateAnalysis, getDailyJobStatus, getMorningBrief,
  getPaperTradeSnapshot, getPortfolioSettings, getSectorSnapshot,
  getWatchlist, updatePortfolioSettings,
} from '../api';
import './CfoWorkspace.css';

const NAV = [
  ['morning', 'Morning', 'Today'],
  ['sectors', 'Sectors', 'Leadership'],
  ['candidates', 'Candidates', 'Top 100'],
  ['portfolio', 'Portfolio', 'Risk book'],
  ['research', 'Research', 'Full dossier'],
  ['system', 'System', 'Data & jobs'],
];

const ACTION_LABEL = {
  BUY_NOW: 'Ready now', WAIT_FOR_ENTRY: 'Near entry', WATCH: 'Watch',
  AVOID: 'Skip', DATA_INSUFFICIENT: 'Needs data',
};

const fmt = (value, digits = 1) => value == null ? '—' : Number(value).toFixed(digits);
const money = (value) => value == null ? '—' : `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
const trendLabel = (score) => ({
  '-2': 'Bearish', '-1': 'Weak', 0: 'Mixed', 1: 'Constructive', 2: 'Strong bullish',
}[String(score)] || 'Unknown');

function StatusPill({ value, children }) {
  const tone = value === 'BUY_NOW' || value === 'healthy' || value === 'constructive' ? 'positive'
    : value === 'AVOID' || value === 'failed' || value === 'defensive' ? 'negative'
      : value === 'WAIT_FOR_ENTRY' || value === 'attention' || value === 'mixed' ? 'caution' : 'neutral';
  return <span className={`cfo-pill cfo-pill-${tone}`}><i aria-hidden="true" />{children || ACTION_LABEL[value] || value || 'Unknown'}</span>;
}

function Metric({ label, value, note }) {
  return <div className="cfo-metric"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}

function EmptyState({ title, body }) {
  return <section className="cfo-empty"><span className="cfo-empty-mark">07:00</span><h2>{title}</h2><p>{body}</p></section>;
}

function SectionHeader({ eyebrow, title, detail, action }) {
  return <div className="cfo-section-head"><div><span>{eyebrow}</span><h2>{title}</h2>{detail && <p>{detail}</p>}</div>{action}</div>;
}

function CandidateRow({ candidate, onOpen, expanded, onToggle }) {
  const plan = candidate.trade_plan || {};
  return <div className={`cfo-candidate ${expanded ? 'is-expanded' : ''}`}>
    <button className="cfo-candidate-main" onClick={onToggle} aria-expanded={expanded}>
      <span className="cfo-rank">{candidate.global_rank || '—'}</span>
      <span className="cfo-company"><strong>{candidate.symbol}</strong><small>{candidate.company}</small></span>
      <span className="cfo-action"><StatusPill value={candidate.action} /></span>
      <span><small>Setup</small><strong>{(candidate.setup_type || 'None').replaceAll('_', ' ')}</strong></span>
      <span><small>Reward / risk</small><strong className="mono">{fmt(plan.risk_reward, 2)}×</strong></span>
      <span><small>Entry distance</small><strong className="mono">{fmt(candidate.entry_distance_pct)}%</strong></span>
      <span><small>Business quality</small><strong>{fmt(candidate.components?.cfo_health, 0)}</strong></span>
      <span><small>Confidence</small><strong>{fmt(candidate.confidence, 0)}%</strong></span>
      <span className="cfo-chevron" aria-hidden="true">⌄</span>
    </button>
    {expanded && <div className="cfo-candidate-expand">
      <div><small>Why it is here</small><p>{candidate.action_reason || candidate.setup_label || 'No active setup'}.</p></div>
      <div><small>Entry</small><p className="mono">{money(plan.entry?.low)} – {money(plan.entry?.high)}</p></div>
      <div><small>Stop</small><p className="mono">{money(plan.stop?.price)}</p></div>
      <div><small>Targets</small><p className="mono">{(plan.targets || []).map(t => money(t.price)).join(' · ') || '—'}</p></div>
      <div><small>Invalidation</small><p>{plan.invalidation || 'Awaiting complete evidence'}</p></div>
      <button className="cfo-link-btn" onClick={() => onOpen(candidate.symbol)}>Open decision dossier →</button>
    </div>}
  </div>;
}

function Morning({ brief, job, onPage, onCandidate, onSector }) {
  if (brief.status === 'setup_required') {
    const running = job?.status === 'running';
    const failed = job?.status === 'failed';
    const pct = job?.total ? Math.round((job.progress || 0) / job.total * 100) : 0;
    const usable = job?.payload?.usable_histories;
    return <div className="cfo-page">
      <section className="cfo-hero cfo-setup-hero">
        <div><span className="cfo-eyebrow">First trusted snapshot</span><h1>{running ? 'Scanning NSE now.' : failed ? 'Incomplete data was held back.' : 'Your morning brief is being prepared.'}</h1><p>{running ? 'StockLens is building the first full-market ranking in the background. You can leave this page; no manual wait is required.' : failed ? 'You see no stocks because StockLens refused to rank a partial market. Your watchlist and Research remain available while the next guarded run retries.' : 'The automated daily pipeline has not published a complete snapshot yet.'}</p></div>
        <div className="cfo-regime-card"><span>Snapshot state</span><StatusPill value={failed ? 'failed' : running ? 'mixed' : 'attention'}>{failed ? 'Held back' : running ? 'Building' : 'Pending'}</StatusPill><strong>{running ? `${pct}%` : '0'}</strong><small>{running ? `${job.progress || 0} of ${job.total || 0} equities processed` : 'published candidates—not a stock verdict'}</small></div>
      </section>
      <section className="cfo-panel cfo-setup-panel">
        <SectionHeader eyebrow="Why there are no stocks" title={failed ? 'An incomplete scan was not shown' : 'The first ranking is not ready yet'} detail="StockLens publishes only after enough NSE price histories and candidates have been checked." />
        <div className="cfo-summary-strip">
          <Metric label="NSE processed" value={job?.progress || 0} note={`${job?.total || 0} total`} />
          <Metric label="Usable histories" value={usable ?? '—'} note="252 sessions required" />
          <Metric label="Eligible so far" value={job?.payload?.eligible ?? '—'} note="price and liquidity checks" />
          <Metric label="Bull AI evidence" value={brief.external_enrichment?.covered || 0} note="supplementary dossiers" />
        </div>
        {job?.error && <div className="cfo-setup-error"><strong>Last run stopped safely</strong><p>{job.error}</p></div>}
        <div className="cfo-setup-actions"><button className="cfo-primary" onClick={() => onPage('system')}>View pipeline details</button><button className="cfo-text-btn" onClick={() => onPage('research')}>Open Research</button></div>
      </section>
    </div>;
  }
  const top = (brief.candidates || []).filter(c => ['BUY_NOW', 'WAIT_FOR_ENTRY', 'WATCH'].includes(c.action)).slice(0, 8);
  const exceptions = brief.data_health?.exceptions || [];
  return <div className="cfo-page">
    <section className="cfo-hero">
      <div><span className="cfo-eyebrow">Your morning overview</span><h1>What looks interesting today.</h1><p>{brief.market_regime?.posture || 'The morning snapshot is being prepared.'}</p></div>
      <div className="cfo-regime-card"><span>Market mood</span><StatusPill value={brief.market_regime?.state}>{brief.market_regime?.state || 'Unknown'}</StatusPill><strong>{brief.universe?.eligible || 0}</strong><small>liquid NSE stocks checked and eligible</small></div>
    </section>

    <section className="cfo-summary-strip">
      <Metric label="Ready now" value={(brief.candidates || []).filter(c => c.action === 'BUY_NOW').length} note="inside entry zone; checks clear" />
      <Metric label="Near entry" value={(brief.candidates || []).filter(c => c.action === 'WAIT_FOR_ENTRY').length} note="strong setup; watch the price" />
      <Metric label="Risk in open trades" value={`${fmt(brief.portfolio?.heat_pct)}%`} note={`${fmt(brief.portfolio?.max_heat_pct)}% limit`} />
      <Metric label="Updated" value={brief.trading_date || 'Pending'} note={brief.validation?.status === 'early' ? 'results still being tracked' : 'historically tested'} />
    </section>

    {brief.validation?.status === 'early' && <div className="cfo-validation-note"><strong>Research mode</strong><span>“Ready now” means today’s price, trend, liquidity and business checks line up. It is not a proven promise: only {brief.validation?.closed_paper_trades || 0} of 100 tracking trades have closed so far.</span></div>}

    <section className="cfo-panel cfo-action-panel">
      <SectionHeader eyebrow="First" title="Portfolio actions" detail="What changed in positions and setups since the last valid snapshot." />
      {(brief.portfolio?.actions || []).length ? brief.portfolio.actions.map((a, i) => <div key={i}>{a}</div>)
        : <div className="cfo-quiet"><span>✓</span><div><strong>No urgent portfolio action</strong><p>Stops, targets and event exposure have no new exception in this snapshot.</p></div></div>}
    </section>

    <section className="cfo-two-col">
      <div className="cfo-panel">
        <SectionHeader eyebrow="Market groups" title="Strongest sectors" action={<button onClick={() => onPage('sectors')} className="cfo-text-btn">View all</button>} />
        <div className="cfo-sector-list">{(brief.sectors || []).slice(0, 6).map(sector => <button key={sector.sector} onClick={() => onSector(sector.sector)}>
          <span className="cfo-sector-rank">{sector.rank}</span><span><strong>{sector.sector}</strong><small>{sector.trend} · {sector.actionable_count} ready or near</small></span><b className="mono">{fmt(sector.score)}</b>
        </button>)}</div>
      </div>
      <div className="cfo-panel">
        <SectionHeader eyebrow="Change ledger" title="What moved" />
        <div className="cfo-change-grid"><div><strong>{brief.changes?.new?.length || 0}</strong><span>New</span><small>{(brief.changes?.new || []).slice(0, 4).join(', ') || 'No change'}</small></div><div><strong>{brief.changes?.upgraded?.length || 0}</strong><span>Upgraded</span><small>{(brief.changes?.upgraded || []).slice(0, 4).join(', ') || 'No change'}</small></div><div><strong>{brief.changes?.downgraded?.length || 0}</strong><span>Downgraded</span><small>{(brief.changes?.downgraded || []).slice(0, 4).join(', ') || 'No change'}</small></div></div>
      </div>
    </section>

    <section className="cfo-panel">
      <SectionHeader eyebrow="Today’s shortlist" title="Best setups this morning" detail="Ranked by setup quality, relative strength, business health, liquidity and reward versus risk." action={<button onClick={() => onPage('candidates')} className="cfo-text-btn">Open Top 100</button>} />
      <div className="cfo-morning-cards">{top.length ? top.map(c => <button key={c.symbol} onClick={() => onCandidate(c.symbol)}><span><b>#{c.global_rank}</b><StatusPill value={c.action} /></span><strong>{c.symbol}</strong><small>{c.company}</small><div><span>{c.setup_type?.replaceAll('_', ' ') || 'No setup'}</span><b className="mono">{fmt(c.trade_plan?.risk_reward, 2)}×</b></div></button>) : <p className="cfo-muted">No ranked candidates in the latest snapshot.</p>}</div>
    </section>

    <section className="cfo-two-col">
      <div className="cfo-panel"><SectionHeader eyebrow="Events" title="Results and risk calendar" detail="Nearest confirmed events; the complete list remains in each stock dossier." />{(brief.results_calendar || []).length ? brief.results_calendar.slice(0, 8).map((e, i) => <div className="cfo-trade" key={i}><strong>{e.symbol || 'Event'}</strong><span>{e.date || String(e)}</span><span>{e.sessions_away != null ? `${e.sessions_away} sessions` : ''}</span><StatusPill value={e.entry_blocked ? 'AVOID' : 'neutral'}>{e.entry_blocked ? 'Entry blocked' : 'Monitor'}</StatusPill></div>) : <div className="cfo-quiet"><span>—</span><div><strong>No confirmed event block loaded</strong><p>Unknown event evidence never counts as a positive.</p></div></div>}</div>
      <div className="cfo-panel"><SectionHeader eyebrow="Integrity" title="Data-health exceptions" /><div className="cfo-exceptions">{exceptions.length ? exceptions.map((e, i) => <p key={i}><span>!</span>{e}</p>) : <p className="is-clear"><span>✓</span>All required sources passed their controls.</p>}</div></div>
    </section>
  </div>;
}

function Sectors({ brief, selected, detail, loading, onSelect, onCandidate }) {
  const sectors = brief.sectors || [];
  const active = detail || sectors.find(s => s.sector === selected) || sectors[0];
  return <div className="cfo-page">
    <SectionHeader eyebrow="Sectors" title="Where the market is strongest" detail="Trend, strength versus NIFTY and trading activity show which groups are leading." />
    <div className="cfo-sector-grid">{sectors.map(s => <button className={active?.sector === s.sector ? 'active' : ''} key={s.sector} onClick={() => onSelect(s.sector)}><span><b>#{s.rank}</b><StatusPill value={s.trend === 'Leading' ? 'constructive' : s.trend === 'Lagging' ? 'defensive' : 'mixed'}>{s.trend}</StatusPill></span><h3>{s.sector}</h3><div><Metric label="Score" value={fmt(s.score)} /><Metric label="Breadth" value={`${fmt(s.breadth_pct)}%`} /></div><small>{s.actionable_count} ready or near · {s.eligible_count} ranked</small></button>)}</div>
    {loading ? <div className="cfo-panel">Loading sector evidence…</div> : active && <section className="cfo-panel cfo-sector-detail"><SectionHeader eyebrow={`Sector #${active.rank || '—'}`} title={active.sector} detail="Current snapshot; conclusions lead and underlying candidates remain available." /><div className="cfo-summary-strip"><Metric label="Trend" value={active.trend} /><Metric label="Breadth" value={`${fmt(active.breadth_pct)}%`} /><Metric label="Relative strength" value={fmt(active.relative_strength)} /><Metric label="Volume participation" value={fmt(active.volume_participation)} /></div><div className="cfo-sector-candidates">{(active.candidates || active.top_candidates || []).map(c => <button key={c.symbol} onClick={() => onCandidate(c.symbol)}><strong>{c.symbol}</strong><span>{c.company}</span><StatusPill value={c.action} /><b className="mono">{fmt(c.score, 0)}</b></button>)}</div></section>}
  </div>;
}

function Candidates({ candidates, onOpen }) {
  const [filter, setFilter] = useState('ALL');
  const [expanded, setExpanded] = useState(null);
  const filtered = filter === 'ALL' ? candidates : candidates.filter(c => c.action === filter);
  return <div className="cfo-page">
    <SectionHeader eyebrow="Daily ranking" title="Top 100 setups" detail="Expand a row for the price levels and reason. Open it for the chart and source checks." />
    <div className="cfo-filterbar" role="group" aria-label="Filter candidates">{['ALL', 'BUY_NOW', 'WAIT_FOR_ENTRY', 'WATCH', 'AVOID', 'DATA_INSUFFICIENT'].map(f => <button key={f} className={filter === f ? 'active' : ''} onClick={() => setFilter(f)}>{f === 'ALL' ? 'All' : ACTION_LABEL[f]} <span>{f === 'ALL' ? candidates.length : candidates.filter(c => c.action === f).length}</span></button>)}</div>
    <div className="cfo-bench-head"><span>Rank</span><span>Company</span><span>Status</span><span>Setup</span><span>Reward / risk</span><span>Entry distance</span><span>Business</span><span>Data confidence</span></div>
    <div className="cfo-bench">{filtered.map(candidate => <CandidateRow key={candidate.symbol} candidate={candidate} expanded={expanded === candidate.symbol} onToggle={() => setExpanded(expanded === candidate.symbol ? null : candidate.symbol)} onOpen={onOpen} />)}</div>
  </div>;
}

function TrustPanel({ data }) {
  const trust = data.trust || {};
  const rows = [
    ['Price integrity', trust.price, trust.price === 'pass' ? 'NSE bhavcopy and Yahoo are on the same session and within the 1% tolerance.' : 'The independent price check did not pass.'],
    ['Financial evidence', trust.financials, trust.financials === 'pass' ? 'Required financial evidence is complete for this model.' : 'Some financial evidence is missing or partial.'],
    ['Business safety checks', trust.cfo_gate, trust.cfo_gate === 'pass' ? 'No serious financial warning was found.' : 'The financial checks contain a caution or a block.'],
    ['Results window', trust.results, trust.results === 'pass' ? `Next reported result date is outside the two-session block${data.results_date ? ` (${data.results_date})` : ''}.` : trust.results === 'block' ? 'Scheduled results are within two sessions; new entries are blocked.' : 'No confirmed result date is available, so this is not counted positively.'],
    ['Track record', trust.historical_validation, trust.historical_validation === 'pass' ? 'Historical testing passed the required thresholds.' : 'Early: there are not enough closed tracking trades to prove this approach yet.'],
    ['External research', trust.external_evidence, trust.external_evidence === 'pass' ? 'Bull AI company-document evidence is attached and source-labelled. It does not increase the score.' : 'This candidate has not received bounded Bull AI coverage; absence is not treated positively.'],
  ];
  const label = state => state === 'pass' ? 'Pass' : state === 'block' ? 'Blocked' : state === 'early' ? 'Early' : state === 'not_covered' ? 'Not covered' : 'Caution';
  const tone = state => state === 'pass' ? 'healthy' : state === 'block' ? 'failed' : state === 'not_covered' ? 'neutral' : 'attention';
  const rankText = data.global_rank ? `#${data.global_rank} overall · #${data.sector_rank} in ${data.sector}` : data.universe_membership?.label;
  return <div className="cfo-panel cfo-trust-panel"><SectionHeader eyebrow="Can I trust this?" title="Checks behind this stock" detail="Use the checks and their limits—not the ticker alone." /><div className="cfo-trust-score"><strong>{fmt(data.score, 0)}<span>/100</span></strong><div><b>Rules-based setup score</b><small>{rankText}</small></div></div><div className="cfo-trust-list">{rows.map(([name, state, detail]) => <div key={name}><StatusPill value={tone(state)}>{label(state)}</StatusPill><span><strong>{name}</strong><small>{detail}</small></span></div>)}</div></div>;
}

function ExternalEvidence({ research = [] }) {
  const item = research.find(entry => entry.provider === 'Bull AI');
  if (!item) return <div className="cfo-panel cfo-bull-evidence"><SectionHeader eyebrow="Bull AI" title="No extra document review yet" detail="The main rules-based analysis still works. Missing external evidence is never treated as confirmation." /><StatusPill value="neutral">Not covered</StatusPill></div>;
  const classes = [...(item.classification?.sectors || []), ...(item.classification?.industries || [])];
  return <div className="cfo-panel cfo-bull-evidence">
    <SectionHeader eyebrow={`Bull AI · refreshed ${item.as_of || 'date unavailable'}`} title="Company-document enrichment" detail={item.scope} action={<StatusPill value="healthy">Source-backed pilot</StatusPill>} />
    <div className="cfo-evidence-chips">{classes.map(value => <span key={value}>{value}</span>)}</div>
    <div className="cfo-evidence-cards">{(item.cards || []).map((card, index) => <article key={`${card.kind}-${index}`}><header><span>{card.kind}</span><StatusPill value={card.status === 'caution' ? 'attention' : 'neutral'}>{card.status}</StatusPill></header><h3>{card.title}</h3><p>{card.summary}</p><div className="cfo-source-links">{(card.sources || []).map((source, sourceIndex) => source.url ? <a key={sourceIndex} href={source.url} target="_blank" rel="noreferrer">{source.label} ↗</a> : <span key={sourceIndex}>{source.label}</span>)}</div></article>)}</div>
    <div className="cfo-evidence-lists"><div><h3>Disclosed counterparties</h3>{(item.counterparties || []).map((party, index) => <div className="cfo-evidence-row" key={`${party.name}-${index}`}><span><strong>{party.name}</strong><small>{party.relation} · {party.detail}</small></span>{party.source?.url ? <a href={party.source.url} target="_blank" rel="noreferrer">Source ↗</a> : null}</div>)}</div><div><h3>Peer context</h3><div className="cfo-peer-list">{(item.peers || []).map(peer => <span key={peer.symbol}><strong>{peer.symbol}</strong><small>{peer.name}</small></span>)}</div><h3>Coverage limits</h3><ul>{(item.limitations || []).map((limit, index) => <li key={index}>{limit}</li>)}</ul></div></div>
  </div>;
}

function CandidateDossier({ data, loading, error, symbol, onBack, onResearch }) {
  const [tab, setTab] = useState('decision');
  if (loading) return <div className="cfo-page"><button className="cfo-back" onClick={onBack}>← Back</button><div className="cfo-panel">Checking {symbol || 'this stock'} against today’s price, trend and financial data…</div></div>;
  if (error || !data) return <div className="cfo-page"><button className="cfo-back" onClick={onBack}>← Back</button><div className="cfo-panel cfo-setup-error"><strong>Could not analyse {symbol}</strong><p>{error || 'No usable analysis was returned.'}</p><button className="cfo-primary" onClick={() => onResearch(symbol)}>Try the full research view</button></div></div>;
  const plan = data.trade_plan || {};
  const metrics = data.cfo?.metrics || {};
  const rankText = data.global_rank ? `#${data.global_rank} overall · #${data.sector_rank} in ${data.sector}` : data.universe_membership?.label || data.sector;
  return <div className="cfo-page cfo-dossier">
    <button className="cfo-back" onClick={onBack}>← Back to list</button>
    <header className="cfo-decision-header"><div><span className="cfo-eyebrow">{rankText}</span><h1>{data.symbol} <small>{data.company}</small></h1><p>{data.action_reason || data.setup_label || 'No active setup'}</p></div><StatusPill value={data.action} /><div className="cfo-decision-numbers"><Metric label="Entry" value={`${money(plan.entry?.low)}–${money(plan.entry?.high)}`} /><Metric label="Stop" value={money(plan.stop?.price)} /><Metric label="Reward / risk" value={`${fmt(plan.risk_reward, 2)}×`} /><Metric label="Data confidence" value={`${fmt(data.confidence, 0)}%`} /></div></header>
    <nav className="cfo-tabs">{['decision', 'business', 'chart', 'evidence'].map(t => <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t[0].toUpperCase() + t.slice(1)}</button>)}</nav>
    {tab === 'decision' && <section className="cfo-tab-grid"><div className="cfo-panel"><SectionHeader eyebrow="Trade plan" title="Levels and invalidation" /><dl className="cfo-definition"><div><dt>Entry zone</dt><dd className="mono">{money(plan.entry?.low)} – {money(plan.entry?.high)}</dd></div><div><dt>Stop</dt><dd className="mono">{money(plan.stop?.price)}</dd></div><div><dt>Targets</dt><dd className="mono">{(plan.targets || []).map(t => `${t.label} ${money(t.price)}`).join(' · ') || '—'}</dd></div><div><dt>Risk to stop</dt><dd>{plan.entry?.low != null && plan.stop?.price != null ? `${fmt(((plan.entry.low - plan.stop.price) / plan.entry.low) * 100, 2)}% from the low end of entry` : '—'}</dd></div><div><dt>Time stop</dt><dd>{plan.time_stop_sessions || 40} sessions</dd></div><div><dt>Invalidation</dt><dd>{plan.invalidation || 'Not available'}</dd></div></dl></div><TrustPanel data={data} /></section>}
    {tab === 'business' && <section className="cfo-tab-grid"><div className="cfo-panel"><SectionHeader eyebrow={data.cfo?.sector_model === 'financial' ? 'Bank and finance checks' : 'Business checks'} title="Business quality" /><div className="cfo-big-score">{fmt(data.cfo?.score, 0)}<span>/100</span></div><StatusPill value={data.cfo?.gate === 'pass' ? 'healthy' : data.cfo?.gate === 'hard_block' ? 'failed' : 'attention'}>{data.cfo?.gate === 'hard_block' ? 'Blocked' : data.cfo?.gate === 'data_insufficient' ? 'Needs data' : data.cfo?.gate}</StatusPill><ul>{[...(data.cfo?.hard_blocks || []), ...(data.cfo?.cautions || []), ...(data.cfo?.reasons || [])].map((r, i) => <li key={i}>{r.replace('CFO/PAT', 'Operating cash / profit')}</li>)}</ul></div><div className="cfo-panel"><SectionHeader eyebrow="Reported numbers" title="Financial evidence" /><div className="cfo-metric-grid"><Metric label="Return on capital" value={`${fmt(metrics.roce)}%`} /><Metric label="Return on equity" value={`${fmt(metrics.roe)}%`} /><Metric label="Cash profit coverage" value={`${fmt(metrics.cfo_pat, 2)}×`} /><Metric label="Revenue growth" value={`${fmt(metrics.revenue_growth)}%`} /><Metric label="Profit growth" value={`${fmt(metrics.profit_growth)}%`} /><Metric label="Financial strength" value={fmt(metrics.piotroski, 0)} /></div></div></section>}
    {tab === 'chart' && <section className="cfo-chart-stack"><div className="cfo-panel cfo-daily-chart"><SectionHeader eyebrow="Daily price and volume" title="What the chart is doing" detail="Daily adjusted price history; the latest close is checked against NSE data." />{(data.daily_history || []).length >= 5 ? <PriceChart history={data.daily_history} levels={plan} volumeTags={[]} /> : <div className="cfo-quiet"><span>!</span><div><strong>Daily chart is temporarily unavailable</strong><p>The saved analysis remains visible, but missing chart data is never treated as confirmation.</p></div></div>}</div><div className="cfo-tab-grid"><div className="cfo-panel"><SectionHeader eyebrow="Chart readings" title="Trend and momentum" /><div className="cfo-metric-grid"><Metric label="Price" value={money(data.price)} /><Metric label="Trend" value={trendLabel(data.technicals?.trend_score)} /><Metric label="RSI" value={fmt(data.technicals?.rsi)} /><Metric label="Daily movement" value={money(data.technicals?.atr)} /><Metric label="Volume versus normal" value={`${fmt(data.technicals?.vol_ratio, 2)}×`} /><Metric label="Near 52-week high" value={`${fmt((data.technicals?.prox_52w || 0) * 100)}%`} /></div></div><div className="cfo-panel"><SectionHeader eyebrow="Why this score" title="Score breakdown" /><div className="cfo-score-bars">{Object.entries(data.components || {}).map(([key, value]) => <div key={key}><span>{key === 'cfo_health' ? 'business quality' : key.replaceAll('_', ' ')}</span><i><b style={{ width: `${value}%` }} /></i><strong>{fmt(value, 0)}</strong></div>)}</div></div></div></section>}
    {tab === 'evidence' && <section className="cfo-tab-grid"><div className="cfo-panel"><SectionHeader eyebrow="Sources" title="How fresh is this?" /><dl className="cfo-definition"><div><dt>Price source</dt><dd>{data.evidence?.price?.source}</dd></div><div><dt>Independent price check</dt><dd>{data.evidence?.price?.status}</dd></div><div><dt>Financial source</dt><dd>{data.evidence?.fundamentals?.origin || 'unavailable'}</dd></div><div><dt>Data coverage</dt><dd>{data.data_completeness}</dd></div><div><dt>Rules version</dt><dd>{data.evidence?.model?.version}</dd></div></dl></div><div className="cfo-panel"><SectionHeader eyebrow="AI review" title="What AI can and cannot do" /><p>AI may explain or lower a status. It cannot change the numbers, promote a blocked stock, or pretend missing evidence is positive.</p><StatusPill value="neutral">{data.evidence?.ai_committee?.status?.replace('_', ' ') || 'Not run'}</StatusPill><button className="cfo-primary" onClick={() => onResearch(data.symbol)}>Open full live research</button></div><ExternalEvidence research={data.external_research} /></section>}
  </div>;
}

function Portfolio({ snapshot, settings, onSave }) {
  const [draft, setDraft] = useState(settings || {});
  useEffect(() => setDraft(settings || {}), [settings]);
  const trades = snapshot?.trades || [];
  return <div className="cfo-page"><SectionHeader eyebrow="Portfolio" title="Your open trades" detail="See open positions, concentration and upcoming results before adding another stock." />
    <section className="cfo-summary-strip"><Metric label="Open positions" value={snapshot?.stats?.active_count || 0} note={`${settings?.max_open_positions || 8} maximum`} /><Metric label="Closed paper trades" value={(snapshot?.stats?.wins || 0) + (snapshot?.stats?.losses || 0)} note="confidence remains early to 100" /><Metric label="Win rate" value={`${fmt(snapshot?.stats?.win_rate_pct)}%`} /><Metric label="Net expectancy" value={`${fmt(snapshot?.stats?.net_pnl_r, 2)}R`} /></section>
    <section className="cfo-two-col"><div className="cfo-panel"><SectionHeader eyebrow="Open trades" title="Paper tracking" />{trades.filter(t => t.status === 'ACTIVE').length ? trades.filter(t => t.status === 'ACTIVE').map(t => <div className="cfo-trade" key={t.id}><strong>{t.symbol}</strong><span>Entry <b className="mono">{money(t.entry_price)}</b></span><span>Stop <b className="mono">{money(t.stop_loss)}</b></span><StatusPill value="neutral">Active</StatusPill></div>) : <div className="cfo-quiet"><span>—</span><div><strong>No open paper trades</strong><p>Use paper tracking to build a real result history before relying on the rankings.</p></div></div>}</div>
    <form className="cfo-panel cfo-settings" onSubmit={e => { e.preventDefault(); onSave(draft); }}><SectionHeader eyebrow="Limits" title="Portfolio guardrails" detail="These are exposure limits only. StockLens does not tell you how many shares to buy." /><label>Maximum risk per idea (%)<input type="number" min="0.1" max="2" step="0.05" value={draft.risk_per_trade_pct || ''} onChange={e => setDraft({ ...draft, risk_per_trade_pct: Number(e.target.value) })} /></label><label>Maximum total open risk (%)<input type="number" min="1" max="12" step="0.25" value={draft.max_portfolio_heat_pct || ''} onChange={e => setDraft({ ...draft, max_portfolio_heat_pct: Number(e.target.value) })} /></label><label>Maximum open trades<input type="number" min="1" max="30" value={draft.max_open_positions || ''} onChange={e => setDraft({ ...draft, max_open_positions: Number(e.target.value) })} /></label><button className="cfo-primary" type="submit">Save limits</button></form></section>
  </div>;
}

function System({ job, brief }) {
  const pct = job?.total ? Math.round((job.progress || 0) / job.total * 100) : 0;
  return <div className="cfo-page"><SectionHeader eyebrow="System" title="Data, automation and audit" detail="The workspace prepares itself. Job controls stay here, away from daily decisions." />
    <section className="cfo-two-col"><div className="cfo-panel"><SectionHeader eyebrow="Daily pipeline" title="07:00 IST snapshot" /><div className="cfo-job"><StatusPill value={job?.status}>{job?.status || 'Never run'}</StatusPill><h3>{job?.stage?.replaceAll('_', ' ') || 'Waiting'}</h3><p>{job?.progress || 0} of {job?.total || 0} · {pct}%</p><div><i style={{ width: `${pct}%` }} /></div>{job?.error && <small className="cfo-error">{job.error}</small>}</div><p className="cfo-muted">Runs from the protected scheduler. A failed run never replaces the last valid snapshot.</p></div><div className="cfo-panel"><SectionHeader eyebrow="Current snapshot" title="Coverage" /><div className="cfo-metric-grid"><Metric label="Official universe" value={brief.universe?.official_equities || 0} /><Metric label="Eligible" value={brief.universe?.eligible || 0} /><Metric label="Deep enriched" value={brief.universe?.deeply_enriched || 0} /><Metric label="Published" value={brief.universe?.published || 0} /></div></div></section>
    <section className="cfo-panel"><SectionHeader eyebrow="Provider policy" title="Free-data-first, evidence-aware" /><div className="cfo-provider-grid"><div><StatusPill value="healthy">Official</StatusPill><h3>NSE equity master</h3><p>Daily eligible universe and listed-security identity.</p></div><div><StatusPill value={brief.data_health?.official_price_as_of ? 'healthy' : 'attention'}>{brief.data_health?.official_price_as_of ? 'Reconciled' : 'Pending'}</StatusPill><h3>NSE bhavcopy</h3><p>Official latest-session close and the 1% conflict gate.</p></div><div><StatusPill value="neutral">Adjusted</StatusPill><h3>Yahoo Finance</h3><p>Split/dividend-adjusted history for indicators and structure.</p></div><div><StatusPill value="neutral">Cached 7 days</StatusPill><h3>Financial evidence</h3><p>Reported statements with source, age and completeness retained.</p></div><div><StatusPill value={brief.external_enrichment?.covered ? 'healthy' : 'neutral'}>{brief.external_enrichment?.covered || 0} covered</StatusPill><h3>Bull AI evidence</h3><p>Bounded filings, guidance, peers, counterparties and transactions. Evidence never boosts a score automatically.</p></div></div></section>
  </div>;
}

export default function CfoWorkspace() {
  const [page, setPage] = useState('morning');
  const [railOpen, setRailOpen] = useState(true);
  const [brief, setBrief] = useState(null);
  const [job, setJob] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [settings, setSettings] = useState(null);
  const [watchlist, setWatchlist] = useState([]);
  const [drawer, setDrawer] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedSector, setSelectedSector] = useState(null);
  const [sectorDetail, setSectorDetail] = useState(null);
  const [sectorLoading, setSectorLoading] = useState(false);
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [candidateData, setCandidateData] = useState(null);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [candidateError, setCandidateError] = useState('');
  const [researchSymbol, setResearchSymbol] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    const results = await Promise.allSettled([getMorningBrief(), getDailyJobStatus(), getPaperTradeSnapshot(), getPortfolioSettings(), getWatchlist()]);
    if (results[0].status === 'fulfilled') setBrief(results[0].value); else setError('The morning snapshot could not be loaded. Cached research remains available.');
    if (results[1].status === 'fulfilled') setJob(results[1].value);
    if (results[2].status === 'fulfilled') setPortfolio(results[2].value);
    if (results[3].status === 'fulfilled') setSettings(results[3].value);
    if (results[4].status === 'fulfilled') setWatchlist(results[4].value || []);
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const openSector = async (sector) => {
    setPage('sectors'); setSelectedSector(sector); setSectorLoading(true); setSectorDetail(null);
    try { setSectorDetail(await getSectorSnapshot(sector)); } catch {} finally { setSectorLoading(false); }
  };
  const openCandidate = async symbol => {
    setPage('candidates'); setSelectedCandidate(symbol); setCandidateLoading(true); setCandidateData(null); setCandidateError('');
    try { setCandidateData(await getCandidateAnalysis(symbol)); }
    catch (error) {
      const saved = (brief?.candidates || []).find(c => c.symbol === symbol);
      if (saved) setCandidateData(saved);
      else setCandidateError(error.response?.data?.detail || 'The stock data provider did not return a usable result.');
    } finally { setCandidateLoading(false); }
  };
  const openResearch = symbol => {
    setResearchSymbol(symbol || null);
    setSelectedCandidate(null);
    setPage('research');
  };
  const saveSettings = async value => { const saved = await updatePortfolioSettings(value); setSettings(saved); };

  const currentLabel = useMemo(() => NAV.find(n => n[0] === page)?.[1] || 'Morning', [page]);
  return <div className={`cfo-shell ${railOpen ? '' : 'rail-collapsed'}`}>
    <aside className="cfo-rail"><div className="cfo-brand"><span>SL</span><div><strong>StockLens</strong><small>Swing workspace</small></div></div><nav>{NAV.map(([id, label, sub]) => <button key={id} className={page === id ? 'active' : ''} onClick={() => { setPage(id); setSelectedCandidate(null); }}><b>{label.slice(0, 1)}</b><span><strong>{label}</strong><small>{sub}</small></span></button>)}</nav><button className="cfo-collapse" onClick={() => setRailOpen(v => !v)}>{railOpen ? 'Collapse rail' : 'Expand'}</button></aside>
    <div className="cfo-workspace">
      <header className="cfo-topbar"><button className="cfo-menu" onClick={() => setRailOpen(v => !v)} aria-label="Toggle navigation">☰</button><div className="cfo-global-search"><SearchBar onSelect={openCandidate} /></div><div className="cfo-top-status"><span><small>Updated</small><strong>{brief?.trading_date || 'Pending'}</strong></span><StatusPill value={brief?.data_health?.status}>{brief?.data_health?.status || 'Loading'}</StatusPill><span><small>Open risk</small><strong>{fmt(brief?.portfolio?.heat_pct)}%</strong></span><button onClick={() => setDrawer(true)}>Watchlist <b>{watchlist.length}</b></button></div></header>
      <main className="cfo-canvas">{loading ? <div className="cfo-loading"><span /><p>Opening your latest morning snapshot…</p></div> : error && !brief ? <EmptyState title="Morning data is unavailable" body={error} /> : selectedCandidate ? <CandidateDossier data={candidateData} loading={candidateLoading} error={candidateError} symbol={selectedCandidate} onBack={() => setSelectedCandidate(null)} onResearch={openResearch} /> : page === 'morning' ? <Morning brief={brief} job={job} onPage={setPage} onCandidate={openCandidate} onSector={openSector} /> : page === 'sectors' ? <Sectors brief={brief} selected={selectedSector} detail={sectorDetail} loading={sectorLoading} onSelect={openSector} onCandidate={openCandidate} /> : page === 'candidates' ? <Candidates candidates={brief.candidates || []} onOpen={openCandidate} /> : page === 'portfolio' ? <Portfolio snapshot={portfolio} settings={settings} onSave={saveSettings} /> : page === 'research' ? <div className="cfo-research-embed"><LegacyResearch initialSymbol={researchSymbol} embedded /></div> : <System job={job} brief={brief} />}</main>
    </div>
    {drawer && <div className="cfo-drawer-scrim" onClick={() => setDrawer(false)}><aside className="cfo-drawer" onClick={e => e.stopPropagation()}><header><div><small>Context drawer</small><h2>Watchlist</h2></div><button onClick={() => setDrawer(false)}>Close</button></header>{watchlist.length ? watchlist.map(w => <button key={w.symbol} onClick={() => { setDrawer(false); openResearch(w.symbol); }}><strong>{w.symbol}</strong><span>{w.name}</span><b>Open →</b></button>) : <p>No stocks in your watchlist yet.</p>}</aside></div>}
    <nav className="cfo-mobile-nav">{[['morning', 'Morning'], ['sectors', 'Sectors'], ['watchlist', 'Watchlist'], ['search', 'Search'], ['more', 'More']].map(([id, label]) => <button key={id} className={page === id ? 'active' : ''} onClick={() => id === 'watchlist' ? setDrawer(true) : id === 'search' ? document.querySelector('.cfo-global-search input')?.focus() : setPage(id === 'more' ? 'system' : id)}><b>{label.slice(0, 1)}</b><span>{label}</span></button>)}</nav>
    <span className="sr-only" aria-live="polite">Current page: {currentLabel}</span>
  </div>;
}
