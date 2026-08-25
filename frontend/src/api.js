import axios from 'axios';

const DEFAULT_API_BASE = process.env.NODE_ENV === 'production'
  ? 'https://stocklens-api.onrender.com'
  : 'http://localhost:8000';

export const API_BASE = (process.env.REACT_APP_API_URL || DEFAULT_API_BASE).replace(/\/+$/, '');

const API = axios.create({ baseURL: API_BASE, timeout: 45000 });

export function describeApiError(error, fallback = 'Request failed') {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (error?.code === 'ECONNABORTED') return 'The backend took too long to respond. Please retry in a moment.';
  if (!error?.response) return `Backend unavailable at ${API_BASE}`;
  return `${fallback} (HTTP ${error.response.status})`;
}

export const searchInstruments = (q) => API.get('/api/search', { params: { q } }).then(r => r.data);
const pathSymbol = (symbol) => encodeURIComponent(String(symbol || '').trim().toUpperCase());

export const getStock = (symbol, exchange = 'NSE') => API.get(`/api/stock/${pathSymbol(symbol)}`, { params: { exchange } }).then(r => r.data);
export const getAlpha = (symbol, exchange = 'NSE') => API.get(`/api/stock/${pathSymbol(symbol)}/alpha`, { params: { exchange } }).then(r => r.data);
export const getLTP = (symbol, exchange = 'NSE') => API.get(`/api/ltp/${pathSymbol(symbol)}`, { params: { exchange } }).then(r => r.data);

export const getWatchlist = () => API.get('/api/watchlist').then(r => r.data);
export const addToWatchlist = (item) => API.post('/api/watchlist', item).then(r => r.data);
export const removeFromWatchlist = (symbol) => API.delete(`/api/watchlist/${pathSymbol(symbol)}`).then(r => r.data);
export const getWatchlistPrices = () => API.get('/api/watchlist/prices').then(r => r.data);

export const getPlan = (symbol, exchange = 'NSE') => API.get(`/api/stock/${pathSymbol(symbol)}/plan`, { params: { exchange } }).then(r => r.data);
export const resolveSymbols = (queries, requestConfig = {}) =>
  API.post('/api/resolve', { queries }, requestConfig).then(r => r.data);
export const getMarketRegime = () => API.get('/api/market-regime').then(r => r.data);
export const getAlerts = (symbol) => API.get('/api/alerts', { params: symbol ? { symbol } : {} }).then(r => r.data);
export const createAlert = (alert) => API.post('/api/alerts', alert).then(r => r.data);
export const createAlertsFromPlan = (payload) => API.post('/api/alerts/from-plan', payload).then(r => r.data);
export const deleteAlert = (id) => API.delete(`/api/alerts/${id}`).then(r => r.data);
export const ackAlert = (id) => API.post(`/api/alerts/${id}/ack`).then(r => r.data);
export const getWatchlistPulse = () => API.get('/api/watchlist/pulse').then(r => r.data);

// Saved screens (persistent, re-loadable screener universes)
export const getScreens = () => API.get('/api/screens').then(r => r.data);
export const getScreen = (id) => API.get(`/api/screens/${id}`).then(r => r.data);
export const saveScreen = (name, tickers, rankedData) => API.post('/api/screens', {
  name, tickers, ...(Array.isArray(rankedData) && rankedData.length ? { ranked_data: rankedData } : {}),
}).then(r => r.data);
export const deleteScreen = (id) => API.delete(`/api/screens/${id}`).then(r => r.data);

// Chartink daily auto-fetcher — saved screener URL
export const getChartinkUrl = () => API.get('/api/settings/chartink-url').then(r => r.data);
export const setChartinkUrl = (url) => API.post('/api/settings/chartink-url', { url }).then(r => r.data);
export const getChartinkScanClause = () => API.get('/api/settings/chartink-scan-clause').then(r => r.data);
export const setChartinkScanClause = (scan_clause) => API.post('/api/settings/chartink-scan-clause', { scan_clause }).then(r => r.data);
export const getAutoScreenStatus = () => API.get('/api/auto-screen/status').then(r => r.data);
// A full Chartink universe may contain hundreds of symbols. The backend now
// computes and caches its price-first ranking before returning, so allow this
// one deliberate refresh more time than ordinary interactive requests.
export const fetchChartinkMatches = (url) => API.post(
  '/api/chartink/fetch', { url }, { timeout: 120000 },
).then(r => r.data);
export const getHealth = () => API.get('/api/health').then(r => r.data);

// Paper trading / forward-testing log
export const createPaperTrade = (trade) => API.post('/api/paper-trades', trade).then(r => r.data);
export const getPaperTradeStats = () => API.get('/api/paper-trades/stats').then(r => r.data);
export const getPaperTradesList = () => API.get('/api/paper-trades/list').then(r => r.data);
export const evaluatePaperTrades = () => API.post('/api/paper-trades/evaluate').then(r => r.data);
