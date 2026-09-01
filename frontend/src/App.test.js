import { render, screen, waitFor } from '@testing-library/react';
import App from './App';
import * as api from './api';

jest.mock('./api', () => ({
  API_BASE: 'http://localhost:8000',
  getStock: jest.fn(),
  getAlpha: jest.fn(),
  getPlan: jest.fn(),
  searchInstruments: jest.fn(() => Promise.resolve([])),
  getWatchlist: jest.fn(() => Promise.resolve([])),
  removeFromWatchlist: jest.fn(),
  getWatchlistPulse: jest.fn(() => Promise.resolve({ prices: {}, alerts_by_symbol: {} })),
  getAlerts: jest.fn(() => Promise.resolve([])),
  ackAlert: jest.fn(),
  deleteAlert: jest.fn(),
  resolveSymbols: jest.fn(),
  getScreens: jest.fn(() => Promise.resolve([])),
  getScreen: jest.fn(),
  saveScreen: jest.fn(),
  deleteScreen: jest.fn(),
  getChartinkUrl: jest.fn(() => Promise.resolve({ url: '' })),
  setChartinkUrl: jest.fn(),
  getChartinkScanClause: jest.fn(() => Promise.resolve({ scan_clause: '' })),
  setChartinkScanClause: jest.fn(),
  getPaperTradeSnapshot: jest.fn(() => Promise.resolve({
    stats: { total_trades: 0, wins: 0, losses: 0, win_rate_pct: 0, net_pnl_r: 0, active_count: 0 },
    trades: [],
  })),
  getAutoScreenStatus: jest.fn(() => Promise.resolve({})),
  getNseUniverse: jest.fn(() => Promise.resolve({ count: 2387, source: 'NSE EQUITY_L' })),
  startNseMarketScan: jest.fn(() => Promise.resolve({ status: 'started' })),
  getHealth: jest.fn(() => Promise.resolve({ ok: true, storage: { backend: 'postgres', durable: true } })),
  fetchChartinkMatches: jest.fn(),
  describeApiError: jest.fn((error, fallback) => fallback),
  getMarketRegime: jest.fn(() => Promise.resolve({ regime: 'Unknown' })),
  addToWatchlist: jest.fn(),
  createAlertsFromPlan: jest.fn(),
}));

beforeEach(() => {
  localStorage.clear();
  api.getMarketRegime.mockResolvedValue({ regime: 'Unknown' });
  api.getWatchlist.mockResolvedValue([]);
  api.getWatchlistPulse.mockResolvedValue({ prices: {}, alerts_by_symbol: {} });
  api.getScreens.mockResolvedValue([]);
  api.getChartinkUrl.mockResolvedValue({ url: '' });
  api.getChartinkScanClause.mockResolvedValue({ scan_clause: '' });
  api.getPaperTradeSnapshot.mockResolvedValue({
    stats: { total_trades: 0, wins: 0, losses: 0, win_rate_pct: 0, net_pnl_r: 0, active_count: 0 },
    trades: [],
  });
  api.getAutoScreenStatus.mockResolvedValue({});
  api.getNseUniverse.mockResolvedValue({ count: 2387, source: 'NSE EQUITY_L' });
  api.getHealth.mockResolvedValue({ ok: true, storage: { backend: 'postgres', durable: true } });
});

test('keeps the paper trade scorecard visible while the backend is waking', () => {
  api.getPaperTradeSnapshot.mockReturnValue(new Promise(() => {}));
  render(<App />);
  expect(screen.getByText(/System Scorecard/)).toBeInTheDocument();
  expect(screen.getByText('Connecting')).toBeInTheDocument();
  expect(screen.getByText('Restoring your trade log…')).toBeInTheDocument();
});

test('shows the last paper trade snapshot when a refresh is unavailable', async () => {
  localStorage.setItem('stocklens_paper_trade_snapshot_v1', JSON.stringify({
    stats: { total_trades: 3, wins: 1, losses: 1, win_rate_pct: 50, net_pnl_r: 0.5, active_count: 1 },
    trades: [{ id: 1, symbol: 'TCS', status: 'ACTIVE', pnl_r: 0, entry_price: 100 }],
  }));
  api.getPaperTradeSnapshot.mockRejectedValue(new Error('backend sleeping'));
  render(<App />);
  expect(screen.getByText(/System Scorecard/)).toBeInTheDocument();
  expect(screen.getByText((_, element) => element?.classList?.contains('pt-scorecard-value')
    && element.textContent.startsWith('50%'))).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText('Cached')).toBeInTheDocument());
});

test('renders the research workspace and primary discovery actions', async () => {
  render(<App />);
  expect(screen.getByText('StockLens')).toBeInTheDocument();
  expect(screen.getByText('Stock Screener')).toBeInTheDocument();
  expect(screen.getByPlaceholderText(/Search stock by name or symbol/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Analyze stocks/i })).toBeDisabled();
  expect(screen.getByText('NSE Market Scan')).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText('2387 stocks')).toBeInTheDocument());
  await waitFor(() => {
    expect(api.getMarketRegime).toHaveBeenCalled();
    expect(api.getWatchlist).toHaveBeenCalled();
    expect(api.getWatchlistPulse).toHaveBeenCalled();
    expect(api.getScreens).toHaveBeenCalled();
  });
});
