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
