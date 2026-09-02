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
  searchInstruments: jest.fn(() => Promise.resolve([])),
  resolveSymbols: jest.fn(() => Promise.resolve([])),
}));

const brief = {
  trading_date: '2026-08-28',
  market_regime: { state: 'constructive', posture: 'Normal risk; favour sector leaders' },
  universe: { official_equities: 2200, eligible: 700, deeply_enriched: 150, published: 100 },
  data_health: { status: 'healthy', exceptions: [], official_price_as_of: '2026-08-28' },
  portfolio: { open_positions: 1, heat_pct: 0.75, max_heat_pct: 6, actions: [] },
  changes: { new: ['TCS'], upgraded: [], downgraded: [] },
  results_calendar: [], validation: { status: 'early', closed_paper_trades: 0 },
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
  api.getSectorSnapshot.mockResolvedValue({ ...brief.sectors[0], candidates: brief.candidates });
  api.getCandidateAnalysis.mockResolvedValue({ ...brief.candidates[0], cfo: { score: 76, gate: 'pass', metrics: {} },
    classification: 'Developing', data_confidence: { overall: 82, price_data: 100, financial_data: 78, event_data: 55, ai_extraction: null },
    earnings_momentum: { score: 84, coverage: 90, status: 'full', margin_direction: 'expansion',
      metrics: { revenue_growth_yoy: 20, revenue_growth_qoq: 5, ebitda_growth_yoy: 28,
        pat_growth_yoy: 32, ebitda_margin_change_yoy: 1.5, pat_margin_change_yoy: 1.2 }, cautions: [] },
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

test('shows a daily chart section without leaving the dossier', async () => {
  render(<CfoWorkspace />);
  await screen.findByText(/What looks interesting today/i);
  fireEvent.click(screen.getByText('Tata Consultancy').closest('button'));
  await screen.findByText(/Checks behind this stock/i);
  fireEvent.click(screen.getByRole('button', { name: 'Chart' }));
  expect(screen.getByText(/What the chart is doing/i)).toBeInTheDocument();
  expect(screen.getByText(/Daily chart is temporarily unavailable/i)).toBeInTheDocument();
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
