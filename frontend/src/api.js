import axios from 'axios';

export const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const API = axios.create({ baseURL: API_BASE });

export const searchInstruments = (q) => API.get('/api/search', { params: { q } }).then(r => r.data);
export const getStock = (symbol, exchange = 'NSE') => API.get(`/api/stock/${symbol}`, { params: { exchange } }).then(r => r.data);
export const getAlpha = (symbol, exchange = 'NSE') => API.get(`/api/stock/${symbol}/alpha`, { params: { exchange } }).then(r => r.data);
export const getLTP = (symbol, exchange = 'NSE') => API.get(`/api/ltp/${symbol}`, { params: { exchange } }).then(r => r.data);

export const getWatchlist = () => API.get('/api/watchlist').then(r => r.data);
export const addToWatchlist = (item) => API.post('/api/watchlist', item).then(r => r.data);
export const removeFromWatchlist = (symbol) => API.delete(`/api/watchlist/${symbol}`).then(r => r.data);
export const getWatchlistPrices = () => API.get('/api/watchlist/prices').then(r => r.data);

export const getPlan = (symbol, exchange = 'NSE') => API.get(`/api/stock/${symbol}/plan`, { params: { exchange } }).then(r => r.data);
export const resolveSymbols = (queries) => API.post('/api/resolve', { queries }).then(r => r.data);
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
export const saveScreen = (name, tickers) => API.post('/api/screens', { name, tickers }).then(r => r.data);
export const deleteScreen = (id) => API.delete(`/api/screens/${id}`).then(r => r.data);
