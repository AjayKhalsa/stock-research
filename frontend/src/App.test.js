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
  getPaperTradeStats: jest.fn(() => Promise.resolve({ total_trades: 0 })),
  getPaperTradesList: jest.fn(() => Promise.resolve([])),
  getAutoScreenStatus: jest.fn(() => Promise.resolve({})),
  getHealth: jest.fn(() => Promise.resolve({ ok: true, storage: { backend: 'postgres', durable: true } })),
  fetchChartinkMatches: jest.fn(),
  describeApiError: jest.fn((error, fallback) => fallback),
  getMarketRegime: jest.fn(() => Promise.resolve({ regime: 'Unknown' })),
  addToWatchlist: jest.fn(),
  createAlertsFromPlan: jest.fn(),
}));

beforeEach(() => {
  api.getMarketRegime.mockResolvedValue({ regime: 'Unknown' });
  api.getWatchlist.mockResolvedValue([]);
  api.getWatchlistPulse.mockResolvedValue({ prices: {}, alerts_by_symbol: {} });
  api.getScreens.mockResolvedValue([]);
  api.getChartinkUrl.mockResolvedValue({ url: '' });
  api.getChartinkScanClause.mockResolvedValue({ scan_clause: '' });
  api.getPaperTradeStats.mockResolvedValue({ total_trades: 0 });
  api.getPaperTradesList.mockResolvedValue([]);
  api.getAutoScreenStatus.mockResolvedValue({});
  api.getHealth.mockResolvedValue({ ok: true, storage: { backend: 'postgres', durable: true } });
});

test('renders the research workspace and primary discovery actions', async () => {
  render(<App />);
  expect(screen.getByText('StockLens')).toBeInTheDocument();
  expect(screen.getByText('Stock Screener')).toBeInTheDocument();
  expect(screen.getByPlaceholderText(/Search stock by name or symbol/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Analyze stocks/i })).toBeDisabled();
  await waitFor(() => {
    expect(api.getMarketRegime).toHaveBeenCalled();
    expect(api.getWatchlist).toHaveBeenCalled();
    expect(api.getWatchlistPulse).toHaveBeenCalled();
    expect(api.getScreens).toHaveBeenCalled();
  });
});
