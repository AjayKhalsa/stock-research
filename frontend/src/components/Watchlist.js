import React, { useState, useEffect, useCallback, useRef } from 'react';
import toast from 'react-hot-toast';
import { getWatchlist, removeFromWatchlist, getWatchlistPulse, getAlerts, ackAlert, deleteAlert } from '../api';
import './Watchlist.css';

export default function Watchlist({ onSelect, currentSymbol }) {
  const [items, setItems] = useState([]);
  const [prices, setPrices] = useState({});
  const [alertsBySymbol, setAlertsBySymbol] = useState({});
  const [showAlerts, setShowAlerts] = useState(false);
  const [alerts, setAlerts] = useState([]);
  // Guard against duplicate toasts if a pulse response races the next poll
  const toastedRef = useRef(new Set());

  const loadWatchlist = useCallback(async () => {
    try {
      const wl = await getWatchlist();
      setItems(wl);
    } catch {}
  }, []);

  const loadAlertList = useCallback(async () => {
    try {
      setAlerts(await getAlerts());
    } catch {}
  }, []);

  const pulse = useCallback(async () => {
    try {
      const p = await getWatchlistPulse();
      setPrices(p.prices || {});
      setAlertsBySymbol(p.alerts_by_symbol || {});
      (p.newly_triggered || []).forEach(a => {
        if (toastedRef.current.has(a.id)) return;
        toastedRef.current.add(a.id);
        const msg = `${a.symbol}: ${a.label} @ ₹${a.triggered_price} — delayed data`;
        if (a.kind === 'stop') toast.error(msg, { duration: 10000, icon: '🛑' });
        else toast.success(msg, { duration: 10000, icon: '🔔' });
      });
    } catch {}
  }, []);

  useEffect(() => {
    loadWatchlist();
  }, [loadWatchlist]);

  useEffect(() => {
    pulse();
    const interval = setInterval(pulse, 30000);
    return () => clearInterval(interval);
  }, [pulse]);

  useEffect(() => {
    if (showAlerts) loadAlertList();
  }, [showAlerts, loadAlertList, alertsBySymbol]);

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

  const handleAck = async (id) => {
    try {
      await ackAlert(id);
      loadAlertList();
      pulse();
    } catch {}
  };

  const handleDeleteAlert = async (id) => {
    try {
      await deleteAlert(id);
      loadAlertList();
      pulse();
    } catch {}
  };

  const getPrice = (item) => {
    const key = `${item.exchange}:${item.symbol}`;
    const p = prices[key];
    if (p == null) return null;
    return typeof p === 'object' ? p.last_price : p;
  };

  const totalUnacked = Object.values(alertsBySymbol)
    .reduce((n, s) => n + (s.triggered_unacked || 0), 0);
  const totalActive = Object.values(alertsBySymbol)
    .reduce((n, s) => n + (s.active || 0), 0);

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
          const aSum = alertsBySymbol[item.symbol];
          return (
            <div
              key={item.symbol}
              className={`wl-item ${isActive ? 'active' : ''}`}
              onClick={() => onSelect(item.symbol, item.exchange)}
            >
              <div className="wl-item-left">
                <span className="wl-symbol">
                  {item.symbol}
                  {aSum && (aSum.active > 0 || aSum.triggered_unacked > 0) && (
                    <span
                      className={`wl-alert-badge ${aSum.triggered_unacked > 0 ? 'hot' : ''}`}
                      title={`${aSum.active} active alert(s)${aSum.triggered_unacked ? `, ${aSum.triggered_unacked} triggered` : ''}`}
                    >
                      🔔{aSum.triggered_unacked > 0 ? aSum.triggered_unacked : aSum.active}
                    </span>
                  )}
                </span>
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

      {(totalActive > 0 || totalUnacked > 0) && (
        <div className="wl-alerts-section">
          <button className="wl-alerts-toggle" onClick={() => setShowAlerts(s => !s)}>
            <span>
              Alerts
              {totalUnacked > 0 && <span className="wl-alerts-hot-dot" />}
            </span>
            <span className="wl-alerts-meta">
              {totalActive} armed{totalUnacked > 0 ? ` · ${totalUnacked} hit` : ''} {showAlerts ? '▾' : '▸'}
            </span>
          </button>

          {showAlerts && (
            <div className="wl-alerts-list">
              {alerts.length === 0 && <div className="wl-alerts-empty">No alerts</div>}
              {alerts.map(a => (
                <div key={a.id} className={`wl-alert-item ${a.status}`}>
                  <div className="wl-alert-main" onClick={() => onSelect(a.symbol, a.exchange)}>
                    <span className="wl-alert-sym">{a.symbol}</span>
                    <span className="wl-alert-label">{a.label}</span>
                    <span className="wl-alert-level">
                      {a.status === 'triggered'
                        ? `hit @ ₹${a.triggered_price}`
                        : `${a.direction === 'above' ? '≥' : '≤'} ₹${a.level}`}
                    </span>
                  </div>
                  <div className="wl-alert-actions">
                    {a.status === 'triggered' && !a.acknowledged && (
                      <button title="Acknowledge" onClick={() => handleAck(a.id)}>✓</button>
                    )}
                    <button title="Delete alert" onClick={() => handleDeleteAlert(a.id)}>×</button>
                  </div>
                </div>
              ))}
              <div className="wl-alerts-note">
                Checked every 30s on delayed data while the app is open — not a substitute for broker GTT orders.
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
