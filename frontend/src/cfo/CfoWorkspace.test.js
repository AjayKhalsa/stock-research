import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import CfoWorkspace from './CfoWorkspace';
import * as api from '../api';

jest.mock('../api', () => ({
  getMorningBrief: jest.fn(),
  getDailyJobStatus: jest.fn(),
  getPaperTradeSnapshot: jest.fn(),
  getPortfolioSettings: jest.fn(),
  getWatchlist: jest.fn(),
  getSectorSnapshot: jest.fn(),
  getCandidateAnalysis: jest.fn(),
  updatePortfolioSettings: jest.fn(),
  createHumanReview: jest.fn(),
  searchInstruments: jest.fn(() => Promise.resolve([])),
  resolveSymbols: jest.fn(() => Promise.resolve([])),
  createPaperTrade: jest.fn(),
}));

const brief = {
  trading_date: '2026-08-28',
  market_regime: { state: 'constructive', posture: 'Normal risk; favour sector leaders' },
  universe: { official_equities: 2200, eligible: 700, deeply_enriched: 150, published: 100 },
  data_health: { status: 'healthy', exceptions: [], official_price_as_of: '2026-08-28' },
  portfolio: { open_positions: 1, heat_pct: 0.75, max_heat_pct: 6, actions: [] },
  changes: { new: ['TCS'], upgraded: [], downgraded: [] },
  results_calendar: [], validation: { status: 'early', closed_paper_trades: 0 },
  historical_truth: { total: 24, armed: 5, active: 3, resolved: 14,
    excluded: 2, observational: 12, observational_resolved: 4,
    win_rate_pct: 57.1, expectancy_r: 0.31,
    avg_mfe_r: 1.42, avg_mae_r: 0.61 },
  latest_backtest: { status: 'insufficient_data', overall: { sample: 14,
    gross_expectancy_r: .34, net_expectancy_r: .27, net_total_r: 3.78,
    net_median_r: .18, net_volatility_r: 1.12, profit_factor: 1.44,
    avg_winner_r: 1.21, avg_loser_r: -.81, target_hit_rate_pct: 50,
    stop_hit_rate_pct: 35.7, median_holding_sessions: 8,
    max_drawdown_r: 2.1, win_rate_pct: 57.1, win_rate_95ci_pct: [32.6, 78.6] },
    by_setup: [{ group: 'pullback', sample: 8, net_expectancy_r: .36 }],
    by_market_regime: [{ group: 'risk_on', sample: 9, net_expectancy_r: .42 }],
    by_sector: [{ group: 'IT', sample: 5, net_expectancy_r: .31 }],
    by_market_cap_bucket: [{ group: 'large_proxy', sample: 7, net_expectancy_r: .24 }],
    cost_model: { round_trip_bps: 35 }, shadow_test: {
      current: { model_version: 'swing-v1.5.0', role: 'production_champion', sample: 14 },
      challenger: { model_version: null, role: 'v2_challenger', status: 'awaiting_evidence' },
      promotion_policy: { automatic_promotion: false, minimum_resolved_outcomes: 100,
        observed_resolved_outcomes: 14, remaining: 86,
        next_step: 'continue forward collection without changing live weights' },
    } },
  shadow_model: { status: 'awaiting_evidence', production_model: 'swing-v1.5.0',
    usable_sample: 14, remaining: 86, automatic_promotion: false, challenger: null },
  human_review_summary: { total: 3, by_assessment: { AGREE: 2, TOO_OPTIMISTIC: 1 } },
  human_model_experiment: { linked_outcomes: 2, cohorts: {
    model_accepted_human_accepted: { sample: 1, net_expectancy_r: .8 },
    model_accepted_human_rejected: { sample: 1, net_expectancy_r: -.4 },
    model_rejected_human_accepted: { sample: 0, net_expectancy_r: null },
    both_rejected: { sample: 0, net_expectancy_r: null },
  } },
  model_errors: { resolved_sample: 14, false_positives: { count: 4 },
    false_negatives: { count: 2 }, missed_opportunities: { status: 'unavailable' } },
  data_archive_status: { immutable_revisions: true, latest_raw_date: '2026-08-28',
    latest_feature_date: '2026-08-28', counts: { securities: 2200,
      market_prices_raw: 2200, market_prices_adjusted: 78000,
      financial_reports: 900, company_events: 40, stock_feature_snapshots: 2350 },
    latest_audit: { status: 'attention', as_of_date: '2026-08-28',
      metrics: { failures: 0, warnings: 2, raw_coverage_pct: 100,
        feature_coverage_pct: 100 },
      checks: [{ name: 'financial_filing_dates', status: 'warn',
        message: '20/900 financial records lack a provider filing date' }] } },
  scan_history: [{ id: 'run-1', status: 'completed', started_at: 1787900000,
    duration_seconds: 311.4, payload: { trading_date: '2026-08-28',
      stocks_scanned: 2288, committee_failures: 1,
      published_action_counts: { BUY_NOW: 3, WAIT_FOR_ENTRY: 8 },
      data_quality: { failures: 0, warnings: 2 } } }],
  sectors: [{ sector: 'IT', rank: 1, score: 75, trend: 'Leading', breadth_pct: 72,
    relative_strength: 70, volume_participation: 64, actionable_count: 1, eligible_count: 10,
    top_candidates: [{ symbol: 'TCS', company: 'Tata Consultancy', action: 'WAIT_FOR_ENTRY', expected_r: 1.1 }] }],
  candidates: [{ symbol: 'TCS', company: 'Tata Consultancy', sector: 'IT', global_rank: 1,
    sector_rank: 1, action: 'WAIT_FOR_ENTRY', score: 77, expected_r: 1.1, confidence: 72,
    setup_type: 'pullback', setup_label: 'Pullback to support', entry_distance_pct: 1.2,
    components: { cfo_health: 76 }, trade_plan: { entry: { low: 3900, high: 3950 },
      stop: { price: 3775 }, targets: [{ label: 'T1', price: 4150 }], invalidation: 'Close below stop' } }],
};

beforeEach(() => {
  api.getMorningBrief.mockResolvedValue(brief);
  api.getDailyJobStatus.mockResolvedValue({ status: 'completed', stage: 'published', progress: 100, total: 100 });
  api.getPaperTradeSnapshot.mockResolvedValue({ stats: { active_count: 0, wins: 0, losses: 0 }, trades: [] });
  api.getPortfolioSettings.mockResolvedValue({ risk_per_trade_pct: .75,
    max_portfolio_heat_pct: 6, max_open_positions: 8 });
  api.getWatchlist.mockResolvedValue([]);
  api.createPaperTrade.mockResolvedValue({ id: 1, status: 'ARMED' });
  api.createHumanReview.mockResolvedValue({ id: 7, assessment: 'TOO_OPTIMISTIC',
    notes: 'Supply is heavier', model_version: 'cfo-v1' });
  api.getSectorSnapshot.mockResolvedValue({ ...brief.sectors[0], candidates: brief.candidates });
  api.getCandidateAnalysis.mockResolvedValue({ ...brief.candidates[0], snapshot_id: 'snapshot-test-1',
    human_reviews: [], cfo: { score: 76, gate: 'pass', metrics: {} },
    classification: 'Developing', data_confidence: { overall: 82, price_data: 100, financial_data: 78, event_data: 55, ai_extraction: null },
    earnings_momentum: { score: 84, coverage: 90, status: 'full', margin_direction: 'expansion',
      metrics: { revenue_growth_yoy: 20, revenue_growth_qoq: 5, ebitda_growth_yoy: 28,
        pat_growth_yoy: 32, ebitda_margin_change_yoy: 1.5, pat_margin_change_yoy: 1.2 }, cautions: [] },
    setup_engines: { selected: { name: 'pullback' },
      breakout: { score: 61, criteria: [] },
      pullback: { score: 82, criteria: [{ name: 'existing uptrend', score: 100, weight: .18, detail: 'trend score 2' }] },
      trend_continuation: { score: 74, criteria: [] } },
    evidence: { price: { source: 'NSE + Yahoo', status: 'matched' }, model: { version: 'cfo-v1' }, ai_committee: { status: 'not_run' } },
    daily_history: [], trust: { price: 'pass', financials: 'pass', cfo_gate: 'pass',
      results: 'caution', historical_validation: 'early', external_evidence: 'pass' },
    external_research: [{ provider: 'Bull AI', as_of: '2026-09-01', scope: 'Bounded company-document evidence.',
      classification: { sectors: ['Technology'], industries: ['IT Services'] }, score_effect: 'none',
      cards: [{ kind: 'guidance', status: 'outstanding', title: 'FY27 guidance',
        summary: 'This target is not yet due.', sources: [{ label: 'Transcript · page 5', url: 'https://example.com/source' }] }],
      counterparties: [], peers: [{ symbol: 'INFY', name: 'Infosys Ltd.' }], limitations: ['No score boost.'] }] });
});

test('opens on the decision-first morning brief', async () => {
  render(<CfoWorkspace />);
  expect(await screen.findByText(/What looks interesting today/i)).toBeInTheDocument();
  expect(screen.getByText('700')).toBeInTheDocument();
  expect(screen.getAllByText('TCS').length).toBeGreaterThan(0);
  expect(screen.getByText(/Portfolio actions/i)).toBeInTheDocument();
  expect(screen.getByText(/Research mode/i)).toBeInTheDocument();
  expect(screen.queryByText(/CFO workspace/i)).not.toBeInTheDocument();
});

test('explains zero stocks as an unpublished guarded snapshot', async () => {
  api.getMorningBrief.mockResolvedValueOnce({
    status: 'setup_required', candidates: [], sectors: [],
    market_regime: { state: 'unknown' }, universe: {}, portfolio: {},
    external_enrichment: { covered: 3 },
  });
  api.getDailyJobStatus.mockResolvedValueOnce({
    status: 'failed', stage: 'failed', progress: 2302, total: 2302,
    error: 'Price-history coverage too low: 431/2302 usable (minimum 1151)',
    payload: { usable_histories: 431, eligible: 222 },
  });
  render(<CfoWorkspace />);
  expect(await screen.findByText(/Incomplete data was held back/i)).toBeInTheDocument();
  expect(screen.getByText(/incomplete scan was not shown/i)).toBeInTheDocument();
  expect(screen.getByText('431')).toBeInTheDocument();
  expect(screen.getByText(/not a stock verdict/i)).toBeInTheDocument();
});

test('reaches a candidate dossier within two interactions', async () => {
  render(<CfoWorkspace />);
  await screen.findByText(/What looks interesting today/i);
  fireEvent.click(screen.getByText('Tata Consultancy').closest('button'));
  await waitFor(() => expect(api.getCandidateAnalysis).toHaveBeenCalledWith('TCS'));
  expect(await screen.findByText(/Levels and invalidation/i)).toBeInTheDocument();
  expect(screen.getByText(/Checks behind this stock/i)).toBeInTheDocument();
  expect(screen.queryByText(/Position sizing/i)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Business' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Evidence' })).toBeInTheDocument();
});

test('calculates position size only after the user supplies portfolio value', async () => {
  render(<CfoWorkspace />);
  await screen.findByText(/What looks interesting today/i);
  fireEvent.click(screen.getByText('Tata Consultancy').closest('button'));
  await screen.findByText(/Position size from your maximum loss/i);
  expect(screen.getByText(/enter your portfolio value/i)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/Portfolio value/i), { target: { value: '1000000' } });
  expect(screen.getByText('50', { selector: 'strong' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Track this setup on paper/i }));
  await waitFor(() => expect(api.createPaperTrade).toHaveBeenCalledWith(expect.objectContaining({
    symbol: 'TCS', entry_low: 3900, entry_high: 3950, stop_loss: 3775,
    target_t1: 4150, action_at_add: 'WAIT_FOR_ENTRY',
  })));
  expect(await screen.findByText(/Daily candles will determine/i)).toBeInTheDocument();
});

test('stores human judgment against the exact recommendation snapshot', async () => {
  render(<CfoWorkspace />);
  await screen.findByText(/What looks interesting today/i);
  fireEvent.click(screen.getByText('Tata Consultancy').closest('button'));
  await screen.findByText(/What did the model get right or wrong/i);
  fireEvent.click(screen.getByRole('button', { name: /Too optimistic/i }));
  fireEvent.click(screen.getByRole('button', { name: /Heavy supply/i }));
  fireEvent.change(screen.getByLabelText(/Review note/i), {
    target: { value: 'Supply is heavier' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Save review/i }));
  await waitFor(() => expect(api.createHumanReview).toHaveBeenCalledWith({
    snapshot_id: 'snapshot-test-1', symbol: 'TCS',
    assessment: 'TOO_OPTIMISTIC', tags: ['HEAVY_SUPPLY'], notes: 'Supply is heavier',
  }));
  expect(await screen.findByText(/Review saved against this exact recommendation snapshot/i)).toBeInTheDocument();
});

test('shows armed entries and active trades as distinct open paper tests', async () => {
  api.getPaperTradeSnapshot.mockResolvedValueOnce({
    stats: { armed_count: 1, active_count: 1, resolved_count: 2,
      wins: 1, losses: 1, win_rate_pct: 50, expectancy_r: 0.25 },
    trades: [
      { id: 1, symbol: 'TCS', status: 'ARMED', entry_low: 3900,
        entry_high: 3950, entry_price: 3925, stop_loss: 3775 },
      { id: 2, symbol: 'INFY', status: 'ACTIVE', entry_price: 1600, stop_loss: 1540 },
    ],
  });
  render(<CfoWorkspace />);
  await screen.findByText(/What looks interesting today/i);
  fireEvent.click(screen.getByRole('button', { name: /Portfolio Risk book/i }));
  expect(await screen.findByText(/Waiting for entry/i)).toBeInTheDocument();
  expect(screen.getByText('Active')).toBeInTheDocument();
  expect(screen.getByText(/1 waiting · 1 active/i)).toBeInTheDocument();
  expect(screen.getByText(/0.25R/i)).toBeInTheDocument();
});

test('shows the automatic historical truth ledger in System', async () => {
  render(<CfoWorkspace />);
  await screen.findByText(/What looks interesting today/i);
  fireEvent.click(screen.getByRole('button', { name: /System Data & jobs/i }));
  expect(await screen.findByText(/Automatic recommendation outcomes/i)).toBeInTheDocument();
  expect(screen.getByText('24')).toBeInTheDocument();
  expect(screen.getByText(/5 waiting · 3 active/i)).toBeInTheDocument();
  expect(screen.getByText('12')).toBeInTheDocument();
  expect(screen.getByText('4 resolved')).toBeInTheDocument();
  expect(screen.getByText(/0.31R/i)).toBeInTheDocument();
  expect(screen.getByText(/Production, V2, and human judgment/i)).toBeInTheDocument();
  expect(screen.getByText(/86 outcomes remaining/i)).toBeInTheDocument();
  expect(screen.getByText(/3 reviews/i)).toBeInTheDocument();
  expect(screen.getByText(/Outcome-linked experiment/i)).toBeInTheDocument();
  expect(screen.getByText(/False positives and false negatives/i)).toBeInTheDocument();
  expect(screen.getByText(/Point-in-time data foundation/i)).toBeInTheDocument();
  expect(screen.getByText('78000')).toBeInTheDocument();
  expect(screen.getByText(/Automated archive audit/i)).toBeInTheDocument();
  expect(screen.getByText(/0 failures · 2 warnings/i)).toBeInTheDocument();
  expect(screen.getByText(/Seven-run operating history/i)).toBeInTheDocument();
  expect(screen.getByText(/2288 scanned · 3 ready · 8 near/i)).toBeInTheDocument();
  expect(screen.getByText(/Median trade/i)).toBeInTheDocument();
  expect(screen.getByText(/Target hit/i)).toBeInTheDocument();
  expect(screen.getByText(/Market-cap results/i)).toBeInTheDocument();
  expect(screen.getByText(/large proxy/i)).toBeInTheDocument();
});

test('searches the daily ranking and keeps rejected stocks auditable', async () => {
  api.getMorningBrief.mockResolvedValueOnce({ ...brief, candidates: [
    ...brief.candidates,
    { symbol: 'RISKY', company: 'Risky Industries', sector: 'Industrials',
      global_rank: 99, sector_rank: 8, action: 'AVOID', score: 64,
      setup_type: 'breakout', hard_blocks: ['Required safety check failed'],
      components: { business_quality: 50 }, trade_plan: {} },
  ] });
  render(<CfoWorkspace />);
  await screen.findByText(/What looks interesting today/i);
  fireEvent.click(screen.getByRole('button', { name: /Candidates Top 100/i }));
  expect(await screen.findByText(/Rejected and data-held stocks/i)).toBeInTheDocument();
  expect(screen.getByText('RISKY')).toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText(/Symbol, company, or sector/i), {
    target: { value: 'Tata' },
  });
  expect(screen.queryByText('RISKY')).not.toBeInTheDocument();
  expect(screen.getByText('TCS')).toBeInTheDocument();
});

test('shows a daily chart section without leaving the dossier', async () => {
  render(<CfoWorkspace />);
  await screen.findByText(/What looks interesting today/i);
  fireEvent.click(screen.getByText('Tata Consultancy').closest('button'));
  await screen.findByText(/Checks behind this stock/i);
  fireEvent.click(screen.getByRole('button', { name: 'Chart' }));
  expect(screen.getByText(/What the chart is doing/i)).toBeInTheDocument();
  expect(screen.getByText(/Daily chart is temporarily unavailable/i)).toBeInTheDocument();
  expect(screen.getByText(/Independent setup engines/i)).toBeInTheDocument();
});

test('shows source-backed Bull AI evidence without changing the score', async () => {
  render(<CfoWorkspace />);
  await screen.findByText(/What looks interesting today/i);
  fireEvent.click(screen.getByText('Tata Consultancy').closest('button'));
  await screen.findByText(/Checks behind this stock/i);
  fireEvent.click(screen.getByRole('button', { name: 'Evidence' }));
  expect(screen.getByText(/Company-document enrichment/i)).toBeInTheDocument();
  expect(screen.getByText(/This target is not yet due/i)).toBeInTheDocument();
  expect(screen.getByText(/No score boost/i)).toBeInTheDocument();
});

test('shows earnings momentum separately from business quality', async () => {
  render(<CfoWorkspace />);
  await screen.findByText(/What looks interesting today/i);
  fireEvent.click(screen.getByText('Tata Consultancy').closest('button'));
  await screen.findByText(/Checks behind this stock/i);
  fireEvent.click(screen.getByRole('button', { name: 'Business' }));
  expect(screen.getByText(/Earnings momentum/i)).toBeInTheDocument();
  expect(screen.getByText(/Latest reported quarters/i)).toBeInTheDocument();
  expect(screen.getByText(/EBITDA margin change/i)).toBeInTheDocument();
});

test('search opens any NSE stock in the modern analysis view', async () => {
  api.getCandidateAnalysis.mockResolvedValueOnce({
    ...brief.candidates[0], symbol: 'CAMS', company: 'Computer Age Management Services',
    global_rank: null, sector_rank: null,
    universe_membership: { ranked: false, label: "On-demand analysis — not in today's Top 100" },
    cfo: { score: 76, gate: 'pass', metrics: {} }, daily_history: [],
    evidence: { price: { status: 'matched' }, fundamentals: {}, model: {}, ai_committee: {} },
    trust: { price: 'pass', financials: 'pass', cfo_gate: 'pass', results: 'caution', historical_validation: 'early', external_evidence: 'not_covered' },
    external_research: [],
  });
  render(<CfoWorkspace />);
  await screen.findByText(/What looks interesting today/i);
  const input = screen.getByPlaceholderText(/Search stock by name or symbol/i);
  fireEvent.change(input, { target: { value: 'CAMS' } });
  fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
  await waitFor(() => expect(api.getCandidateAnalysis).toHaveBeenCalledWith('CAMS'));
  expect(await screen.findByText(/Computer Age Management Services/i)).toBeInTheDocument();
  expect(screen.getAllByText(/On-demand analysis/i).length).toBeGreaterThan(0);
});
