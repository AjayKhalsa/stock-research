import React, { useState, useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import { getWatchlist, removeFromWatchlist, getWatchlistPrices } from '../api';
import './Watchlist.css';

export default function Watchlist({ onSelect, currentSymbol }) {
  const [items, setItems] = useState([]);
  const [prices, setPrices] = useState({});

  const loadWatchlist = useCallback(async () => {
    try {
      const wl = await getWatchlist();
      setItems(wl);
    } catch {}
  }, []);

  const loadPrices = useCallback(async () => {
    try {
      const p = await getWatchlistPrices();
      setPrices(p || {});
    } catch {}
  }, []);

  useEffect(() => {
    loadWatchlist();
  }, [loadWatchlist]);

  useEffect(() => {
    if (items.length === 0) return;
    loadPrices();
    const interval = setInterval(loadPrices, 30000);
    return () => clearInterval(interval);
  }, [items, loadPrices]);

  const handleRemove = async (e, symbol) => {
    e.stopPropagation();
    try {
      const updated = await removeFromWatchlist(symbol);
      setItems(updated);
      toast.success(`${symbol} removed from watchlist`);
    } catch {
      toast.error('Failed to remove');
    }
  };

  const getPrice = (item) => {
    const key = `${item.exchange}:${item.symbol}`;
    const p = prices[key];
    if (p == null) return null;
    return typeof p === 'object' ? p.last_price : p;
  };

  return (
    <div className="watchlist">
      <div className="wl-header">
        <span className="wl-title">Watchlist</span>
        <span className="wl-count">{items.length}</span>
      </div>

      {items.length === 0 && (
        <div className="wl-empty">
          <p>Add stocks to track them here</p>
        </div>
      )}

      <div className="wl-items">
        {items.map(item => {
          const price = getPrice(item);
          const isActive = item.symbol === currentSymbol;
          return (
            <div
              key={item.symbol}
              className={`wl-item ${isActive ? 'active' : ''}`}
              onClick={() => onSelect(item.symbol, item.exchange)}
            >
              <div className="wl-item-left">
                <span className="wl-symbol">{item.symbol}</span>
                <span className="wl-name">{item.name !== item.symbol ? item.name : item.exchange}</span>
              </div>
              <div className="wl-item-right">
                {price != null ? (
                  <span className="wl-price">₹{Number(price).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
                ) : (
                  <span className="wl-price wl-price-na">—</span>
                )}
                <button
                  className="wl-remove"
                  onClick={(e) => handleRemove(e, item.symbol)}
                  title="Remove"
                >
                  ×
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
