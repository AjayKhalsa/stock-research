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
  expect(await screen.findByText(/Start with the decisions/i)).toBeInTheDocument();
  expect(screen.getByText('700')).toBeInTheDocument();
  expect(screen.getAllByText('TCS').length).toBeGreaterThan(0);
  expect(screen.getByText(/Portfolio actions/i)).toBeInTheDocument();
});

test('reaches a candidate dossier within two interactions', async () => {
  render(<CfoWorkspace />);
  await screen.findByText(/Start with the decisions/i);
  fireEvent.click(screen.getByText('Tata Consultancy').closest('button'));
  await waitFor(() => expect(api.getCandidateAnalysis).toHaveBeenCalledWith('TCS'));
  expect(await screen.findByText(/Levels and invalidation/i)).toBeInTheDocument();
  expect(screen.getByText(/Why this made the list/i)).toBeInTheDocument();
  expect(screen.queryByText(/Position sizing/i)).not.toBeInTheDocument();
  expect(screen.getByText(/Business/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Evidence' })).toBeInTheDocument();
});

test('shows a daily chart section without leaving the dossier', async () => {
  render(<CfoWorkspace />);
  await screen.findByText(/Start with the decisions/i);
  fireEvent.click(screen.getByText('Tata Consultancy').closest('button'));
  await screen.findByText(/Why this made the list/i);
  fireEvent.click(screen.getByRole('button', { name: 'Chart' }));
  expect(screen.getByText(/Daily market structure/i)).toBeInTheDocument();
  expect(screen.getByText(/Daily chart is temporarily unavailable/i)).toBeInTheDocument();
});

test('shows source-backed Bull AI evidence without changing the score', async () => {
  render(<CfoWorkspace />);
  await screen.findByText(/Start with the decisions/i);
  fireEvent.click(screen.getByText('Tata Consultancy').closest('button'));
  await screen.findByText(/Why this made the list/i);
  fireEvent.click(screen.getByRole('button', { name: 'Evidence' }));
  expect(screen.getByText(/Company-document enrichment/i)).toBeInTheDocument();
  expect(screen.getByText(/This target is not yet due/i)).toBeInTheDocument();
  expect(screen.getByText(/No score boost/i)).toBeInTheDocument();
});
