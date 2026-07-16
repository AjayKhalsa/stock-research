/**
 * guideData.js — the fictional "DEMOTECH" stock used by the in-app guide.
 * Every object matches the real API response shapes exactly, so the guide
 * renders through the SAME components as a live research page. Numbers are
 * hand-crafted to be internally consistent (EBIT = PBT + interest, R:R math
 * checks out, z-scores plausible) so the walkthrough doubles as a worked
 * example.
 */

/* ── deterministic 260-day price series: uptrend + pullback to the 50-DMA ── */
function genHistory() {
  const out = [];
  let price = 720;
  const start = new Date('2025-07-01');
  for (let i = 0; i < 260; i++) {
    const d = new Date(start.getTime() + i * 86400000);
    if (d.getDay() === 0 || d.getDay() === 6) continue;
    // trend + two corrections + final pullback, all deterministic
    const trend = 1.0016;
    const wave = Math.sin(i / 18) * 0.004;
    const dip1 = i > 90 && i < 105 ? -0.006 : 0;
    const dip2 = i > 175 && i < 188 ? -0.005 : 0;
    const endPull = i > 244 ? -0.004 : 0;
    price = price * (trend + wave / 10) * (1 + dip1 + dip2 + endPull);
    const vol = Math.round(180000 + 90000 * Math.abs(Math.sin(i / 7))
                + (i > 238 && i < 244 ? 220000 : 0));   // volume spike on the last rally
    out.push({ date: d.toISOString().slice(0, 10), close: Math.round(price * 100) / 100, volume: vol });
  }
  return out;
}
const HISTORY = genHistory();
const LAST = HISTORY[HISTORY.length - 1].close;   // ≈ ₹1,00x

export const DEMO_SYMBOL = 'DEMOTECH';

/* ── /api/stock shape ────────────────────────────────────────────────────── */
export const demoStock = {
  symbol: DEMO_SYMBOL,
  exchange: 'NSE',
  company_name: 'Demo Technologies Ltd (Example)',
  price_history: HISTORY,
  live_price: LAST,
  day_change: 8.4,
  day_change_pct: 0.85,
  open: LAST - 6, high: LAST + 4, low: LAST - 11,
  week_high_52: Math.round(LAST * 1.06), week_low_52: 705,
  market_cap: '24,500',
  pe_ratio: 28.4, pb_ratio: 5.1, roe: 19.2, roce: 23.5,
  dividend_yield: 0.8, debt_to_equity: 0.22, book_value: 196,
  quarterly_results: [
    { quarter: 'Sep 2025', revenue: 1180, net_profit: 148, ebitda: 236 },
    { quarter: 'Dec 2025', revenue: 1260, net_profit: 160, ebitda: 254 },
    { quarter: 'Mar 2026', revenue: 1345, net_profit: 178, ebitda: 278 },
    { quarter: 'Jun 2026', revenue: 1410, net_profit: 191, ebitda: 296 },
  ],
  shareholding: {
    promoter: 54.2, promoter_prev: 54.2,
    fii: 18.6, fii_prev: 17.1,
    dii: 12.4, dii_prev: 12.9,
    retail: 14.8, retail_prev: 15.8,
    promoter_pledge: 0.0,
    latest_quarter: 'Jun 2026', prev_quarter: 'Mar 2026',
  },
  technicals: { ma50: Math.round(LAST * 0.965), ma200: Math.round(LAST * 0.86), rsi: 47.8, current_price: LAST, trend: 'Uptrend' },
  news: [
    { title: 'Demo Technologies wins multi-year platform deal; brokers raise estimates', source: 'Example Wire', published: '', link: '#', sentiment: 'Positive', red_flag: false },
    { title: 'Demo Technologies Q1 profit up 22% YoY on margin expansion', source: 'Example Wire', published: '', link: '#', sentiment: 'Positive', red_flag: false },
    { title: 'IT sector faces near-term demand uncertainty, says industry body', source: 'Example Wire', published: '', link: '#', sentiment: 'Negative', red_flag: false },
  ],
};

/* ── /api/stock/{s}/plan shape ───────────────────────────────────────────── */
const ENTRY_LOW = Math.round((LAST * 0.962) * 100) / 100;
const ENTRY_HIGH = Math.round((LAST * 0.982) * 100) / 100;
const ENTRY_MID = Math.round(((ENTRY_LOW + ENTRY_HIGH) / 2) * 100) / 100;
const STOP = Math.round((ENTRY_LOW - 2 * 18.6 * 0.55) * 100) / 100;   // structure-tightened
const RISK = ENTRY_MID - STOP;
const T1 = Math.round((ENTRY_MID + 1.5 * RISK) * 100) / 100;
const T2 = Math.round((ENTRY_MID + 2.5 * RISK) * 100) / 100;

const demoSwing = {
  horizon: 'swing',
  verdict: 'Buy',
  setup: 'pullback',
  setup_label: 'Pullback toward rising 50-DMA',
  evidence: [
    'Price within 3% of rising 50-DMA',
    'RSI 47.8 — reset, not oversold',
    'Above 200-DMA',
    'Volume drying up on the pullback — sellers exhausted',
  ],
  confidence: 74,
  entry: { low: ENTRY_LOW, high: ENTRY_HIGH, type: 'pullback', rationale: 'Band around the rising 50-DMA / pivot support cluster' },
  stop: { price: STOP, basis: 'structure', rationale: '0.25 ATR below pivot support (tighter than the 2-ATR fallback)', risk_pct: Math.round(RISK / ENTRY_MID * 10000) / 100 },
  targets: [
    { label: 'T1', price: T1, basis: '1.5R', rr: 1.5 },
    { label: 'T2', price: T2, basis: '2.5R', rr: 2.5 },
  ],
  risk_reward: 1.5,
  invalidation: `Plan invalid if a daily close is below ₹${STOP}`,
  notes: ['RSI 47.8 — room to run'],
  flags: [],
};

const demoPositional = {
  ...demoSwing,
  horizon: 'positional',
  verdict: 'Buy on Dip',
  entry: { low: Math.round(LAST * 0.94), high: Math.round(LAST * 0.985), type: 'pullback', rationale: 'Accumulation band around the rising 50-DMA (price > MA50 > MA200)' },
  stop: { price: Math.round(LAST * 0.885), basis: 'structure', rationale: '0.5 ATR below major swing low (3 touches)', risk_pct: 7.4 },
  targets: [{ label: 'T1', price: Math.round(LAST * 1.22), basis: 'Measured move: 60-day range height projected from entry', rr: 3.1 }],
  risk_reward: 3.1,
  exit_rule: 'Trail: exit on a daily close below the 50-DMA',
  fundamentals_gate: { status: 'pass', reasons: ['Piotroski 7/9', 'Altman Safe', 'Quality composite 78/100'] },
  invalidation: `Plan invalid if a daily close is below ₹${Math.round(LAST * 0.885)} (major swing low)`,
  notes: [],
};

export const demoPlan = {
  symbol: DEMO_SYMBOL,
  exchange: 'NSE',
  company_name: 'Demo Technologies Ltd (Example)',
  as_of: HISTORY[HISTORY.length - 1].date,
  price: LAST,
  atr: 18.6,
  key_levels: {
    supports: [
      { price: Math.round(LAST * 0.965), touches: 4, last_touch: '2026-07-01' },
      { price: Math.round(LAST * 0.91), touches: 3, last_touch: '2026-05-14' },
    ],
    resistances: [
      { price: Math.round(LAST * 1.05), touches: 2, last_touch: '2026-06-20' },
    ],
    ma50: Math.round(LAST * 0.965), ma200: Math.round(LAST * 0.86),
    high_52w: Math.round(LAST * 1.06),
  },
  price_action: {
    signals: {
      structure: { state: 'uptrend', detail: 'higher highs and higher lows intact' },
      obv: { state: 'confirming', detail: 'volume flow confirms the price trend' },
      distribution_days: 1,
      pocket_pivots: ['2026-07-10'],
      pullback_volume: { state: 'dry_up', ratio: 0.61, detail: 'pullback volume 61% of 50d average — sellers exhausted' },
      up_down_volume_ratio: 1.62,
      tightness: { contracting: true, nr7: true },
      climax: { state: 'none' },
      close_range: { last: 0.74, avg_up_days: 0.68 },
    },
  },
  swing: demoSwing,
  positional: demoPositional,
  dossier: {
    regime: {
      regime: 'risk_on', label: 'Risk-On', trend: 'up',
      guidance: 'NIFTY in an uptrend with contained volatility — long setups have tailwind; normal aggression is justified.',
      nifty: 26480.5, ma50: 25900.2, ma200: 24710.8,
      vol_percentile: 34, drawdown_pct: -1.2, distribution_days: 1,
      as_of: HISTORY[HISTORY.length - 1].date,
    },
    relative_strength: {
      excess_1m: 0.031, excess_3m: 0.094, excess_6m: 0.148,
      beta: 1.12, rs_line_new_high: true,
      label: 'Market leader: beating NIFTY by 9.4% over 3M',
    },
    trend_template: {
      score: 7, max_score: 8,
      items: [
        { label: 'Price above MA50 > MA150 > MA200', pass: true, detail: 'fully aligned uptrend' },
        { label: '200-DMA rising (vs 1 month ago)', pass: true, detail: 'long-term trend direction' },
        { label: 'At least 25% above 52-week low', pass: true, detail: '52w low ₹705 — currently +42%' },
        { label: 'Within 25% of 52-week high', pass: true, detail: '5.5% below the high' },
        { label: 'Outperforming NIFTY over 3 months', pass: true, detail: 'excess return +9.4%' },
        { label: 'Up-day volume exceeds down-day volume (20d)', pass: true, detail: 'accumulation' },
        { label: 'Not a penny stock (price above ₹20)', pass: true, detail: `₹${LAST}` },
        { label: 'Volatility contracting (ATR% below 6-month median)', pass: false, detail: 'now 1.86% vs median 1.71% — slightly elevated' },
      ],
    },
    base_rates: {
      n: 16, wins: 10, win_rate: 62.5, avg_r: 0.55, expected_r: 0.55,
      median_hold: 11, since: HISTORY[0].date,
      note: '16 comparable pullback setups since 2021: 10 winners (62%), average +0.55R per trade (2-ATR stop, 1.5R target, 40-bar timeout).',
    },
    price_action: {
      structure: { state: 'uptrend', detail: 'higher highs and higher lows intact' },
      obv: { state: 'confirming', detail: 'volume flow confirms the price trend' },
      distribution_days: 1,
      pocket_pivots: ['2026-07-10'],
      pullback_volume: { state: 'dry_up', ratio: 0.61, detail: 'pullback volume 61% of 50d average — sellers exhausted' },
      up_down_volume_ratio: 1.62,
      tightness: { contracting: true, nr7: true },
      climax: { state: 'none' },
      close_range: { last: 0.74, avg_up_days: 0.68 },
    },
    case: {
      conviction: 84, bull_points: 52, bear_points: 18,
      final_call: 'High-conviction Buy',
      ledger: [
        { side: 'bull', points: 15, text: 'History is on your side: 16 comparable setups, 62.5% win rate, +0.55R expected value per trade', source: 'base_rates' },
        { side: 'bull', points: 10, text: 'Active pullback setup: Pullback toward rising 50-DMA', source: 'technicals' },
        { side: 'bull', points: 10, text: 'Trend template 7/8 — institutional-grade uptrend structure', source: 'checklist' },
        { side: 'bull', points: 8, text: 'Market leader: beating NIFTY by 9.4% over 3M', source: 'relative_strength' },
        { side: 'bull', points: 8, text: 'Piotroski 7/9 — fundamentals improving on most fronts', source: 'fundamentals' },
        { side: 'bull', points: 6, text: 'Volume drying up on the pullback — sellers exhausted', source: 'price_action' },
        { side: 'bear', points: 6, text: 'Poor payoff would apply if T1 were capped by resistance — it is not here', source: 'plan' },
        { side: 'bull', points: 6, text: 'Tape supports longs: Risk-On — up trend, vol at 34th percentile', source: 'regime' },
        { side: 'bear', points: 12, text: 'Valuation stretched: P/E 28.4 vs sector median ~22 — priced for continued execution', source: 'fundamentals' },
      ],
    },
  },
  synthesis: {
    lenses: [
      { key: 'trade', label: 'Trade Setup', score: 84, verdict: 'Buy', horizon: 'days–weeks', question: 'Is this a good trade right now?', detail: 'Pullback toward rising 50-DMA' },
      { key: 'business', label: 'Business Quality', score: 78, verdict: 'Strong', horizon: 'quarters–years', question: 'Is this a good business to own?', detail: 'Piotroski 7/9, Altman Safe, gate: pass' },
      { key: 'ai', label: 'AI Analyst', score: 72, verdict: 'Buy', horizon: 'blended', question: 'Narrative judge weighing everything', detail: 'Agrees with the plan; flags valuation as the main risk' },
    ],
    pattern: 'aligned_bull',
    pattern_label: 'Aligned — chart and business agree',
  },
  disclaimer: 'Educational analysis only — not investment advice. Price data is delayed (Yahoo Finance). DEMOTECH is a fictional company.',
};

/* ── a broken stock, for the Gatekeeper section ─────────────────────────── */
export const demoBrokenPlan = {
  price: 412.4,
  key_levels: { ma200: 505.2 },
  price_action: { signals: { structure: { state: 'downtrend', detail: 'lower highs and lower lows — structure broken' } } },
  swing: {
    verdict: 'Avoid',
    notes: ['Price below 200-DMA / downtrend — no long swing setup'],
    flags: ['Price below 200-DMA / downtrend — no long swing setup', '7 distribution days in the last 25 sessions — institutional selling pressure'],
  },
};

/* ── /alpha subset: quant scores for the fundamentals section ───────────── */
export const demoQuant = {
  composite_quality_score: 78,
  piotroski: {
    score: 7, max_score: 9,
    interpretation: 'Strong — fundamentals improving on most fronts.',
    data_quality: 'high',
    signals: {
      F1_positive_roa:        { score: 1, value: 12.8, unit: '% ROA', description: 'Net Income / Total Assets > 0 — company is asset-profitable' },
      F2_positive_cfo:        { score: 1, value: 690,  unit: '₹ Cr', description: 'Operating cash flow is positive — real cash being generated' },
      F3_increasing_roa:      { score: 1, value: 1.4,  unit: 'pp YoY', description: 'ROA improved year-over-year' },
      F4_quality_earnings:    { score: 1, value: null, description: 'CFO/Assets > ROA — earnings are cash-backed, not accounting inflated' },
      F5_decreasing_leverage: { score: 1, value: -0.03, unit: 'Δ ratio', description: 'Long-term debt burden has not increased YoY' },
      F6_improving_liquidity: { score: 0, value: -0.08, unit: 'Δ ratio', description: 'Current ratio slipped from 2.31x to 2.23x — marginally weaker short-term cover' },
      F7_no_dilution:         { score: 1, value: 0,    description: 'No significant new share issuance detected' },
      F8_improving_margin:    { score: 1, value: 0.9,  unit: 'pp YoY', description: 'EBITDA margin expanded YoY — pricing power or cost efficiency' },
      F9_asset_turnover:      { score: 0, value: -0.02, unit: 'x YoY', description: 'Asset turnover eased from 0.88x to 0.86x — capacity added ahead of revenue' },
    },
  },
  altman: {
    z_score: 5.85, z_prime: 5.85, z_classic: 6.4,
    zone: 'Safe', zone_color: 'green',
    model: "Z''-score (emerging markets)",
    interpretation: 'Low probability of financial distress in the next 2 years.',
    components: {
      X1_working_capital_ratio: 0.31, X2_retained_earnings_ratio: 0.44,
      X3_ebit_to_assets: 0.19, X4_equity_vs_liabilities: 2.6, X5_asset_turnover: 0.86,
    },
    thresholds: { safe_above: 2.6, grey_above: 1.1 },
    data_quality: 'high',
  },
  dupont: {
    net_profit_margin_pct: 13.5, asset_turnover: 0.86, equity_multiplier: 1.63,
    roe_dupont_pct: 18.9, roe_reported_pct: 19.2,
    primary_roe_driver: 'Margin-led ROE — pricing power is doing the work, not leverage.',
    trend: [
      { year: 'Mar 2023', npm_pct: 11.2, asset_turnover: 0.81, equity_multiplier: 1.78, roe_computed_pct: 16.1 },
      { year: 'Mar 2024', npm_pct: 12.0, asset_turnover: 0.84, equity_multiplier: 1.71, roe_computed_pct: 17.2 },
      { year: 'Mar 2025', npm_pct: 12.8, asset_turnover: 0.85, equity_multiplier: 1.67, roe_computed_pct: 18.2 },
      { year: 'Mar 2026', npm_pct: 13.5, asset_turnover: 0.86, equity_multiplier: 1.63, roe_computed_pct: 18.9 },
    ],
  },
  beneish: {
    m_score: -2.61, is_manipulator: false, threshold: -1.78,
    interpretation: 'Non-manipulator — no strong manipulation signals',
    components: { DSRI: 1.02, GMI: 0.98, AQI: 1.01, SGI: 1.12, DEPI: 1.04, SGAI: 1.0, TATA: -0.03, LVGI: 0.97 },
    data_quality: 'partial',
  },
};

/* ── fake screener row for the Factor Report Card section ───────────────── */
export const demoRow = {
  symbol: DEMO_SYMBOL, rank: 2, score: 76.4, verdict: 'Strong Candidate',
  z_momentum: 1.24, z_quality: 0.86, z_value: -0.52, z_low_risk: 0.31,
};
