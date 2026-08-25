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
  getMarketRegime: jest.fn(() => Promise.resolve({ regime: 'Unknown' })),
  addToWatchlist: jest.fn(),
  createAlertsFromPlan: jest.fn(),
}));

beforeEach(() => {
  api.getMarketRegime.mockResolvedValue({ regime: 'Unknown' });
  api.getWatchlist.mockResolvedValue([]);
  api.getWatchlistPulse.mockResolvedValue({ prices: {}, alerts_by_symbol: {} });
  api.getScreens.mockResolvedValue([]);
});

test('renders the research workspace and primary discovery actions', async () => {
  render(<App />);
  expect(screen.getByText('StockLens')).toBeInTheDocument();
  expect(screen.getByText('Stock Screener')).toBeInTheDocument();
  expect(screen.getByPlaceholderText(/Search stock by name or symbol/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Run Screen/i })).toBeDisabled();
  await waitFor(() => {
    expect(api.getMarketRegime).toHaveBeenCalled();
    expect(api.getWatchlist).toHaveBeenCalled();
    expect(api.getWatchlistPulse).toHaveBeenCalled();
    expect(api.getScreens).toHaveBeenCalled();
  });
});
