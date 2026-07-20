import React, { useState, useEffect, useCallback, useRef } from 'react';
import toast from 'react-hot-toast';
import {
  getWatchlist, removeFromWatchlist, getWatchlistPulse, getAlerts, ackAlert, deleteAlert,
  getScreens, getScreen, saveScreen, deleteScreen,
} from '../api';
import './Watchlist.css';

/* Save/load panel for named screens. Sits at the very top of the sidebar. */
function SavedScreensPanel({ screenTickers, onLoadScreen }) {
  const [screens, setScreens] = useState([]);
  const [selected, setSelected] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const inputRef = useRef(null);

  const refresh = useCallback(async () => {
    try { setScreens(await getScreens()); } catch {}
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { if (modalOpen) setTimeout(() => inputRef.current?.focus(), 30); }, [modalOpen]);

  const canSave = Array.isArray(screenTickers) && screenTickers.length > 0;

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed || !canSave || saving) return;
    setSaving(true);
    try {
      const rec = await saveScreen(trimmed, screenTickers);
      toast.success(`Saved "${rec.name}" (${rec.count} tickers)`);
      setModalOpen(false);
      setName('');
      await refresh();
      setSelected(String(rec.id));
    } catch {
      toast.error('Could not save screen');
    } finally {
      setSaving(false);
    }
  };

  const handleLoad = async (id) => {
    setSelected(id);
    if (!id) return;
    try {
      const rec = await getScreen(id);
      if (rec.tickers?.length) {
        onLoadScreen(rec.tickers);
        toast.success(`Loading "${rec.name}" (${rec.count} tickers)`);
      }
    } catch {
      toast.error('Could not load screen');
    }
  };

  const handleDelete = async () => {
    if (!selected) return;
    const rec = screens.find(s => String(s.id) === String(selected));
    if (!window.confirm(`Delete saved screen "${rec?.name || 'this screen'}"? This cannot be undone.`)) return;
    try {
      await deleteScreen(selected);
      toast.success(`Deleted "${rec?.name || 'screen'}"`);
      setSelected('');
      await refresh();
    } catch {
      toast.error('Could not delete screen');
    }
  };

  return (
    <div className="ss-panel">
      <div className="ss-header">
        <span className="ss-title">Saved Screens</span>
        <button
          className="ss-save-btn"
          onClick={() => setModalOpen(true)}
          disabled={!canSave}
          title={canSave ? 'Save the current screen results as a named list'
            : 'Run a screen first, then save its results'}
        >Save Screen</button>
      </div>

      <div className="ss-load-row">
        <select
          className="ss-select"
          value={selected}
          onChange={(e) => handleLoad(e.target.value)}
        >
          <option value="">Load a saved screen...</option>
          {screens.map(s => (
            <option key={s.id} value={s.id}>{s.name} ({s.count})</option>
          ))}
        </select>
        {selected && (
          <button
            className="ss-delete-btn"
            onClick={handleDelete}
            title="Delete the selected saved screen"
            aria-label="Delete selected screen"
          >
            <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 4.5h10M6.5 4.5V3.2h3V4.5M4.2 4.5l.6 8.3a1 1 0 0 0 1 .9h4.4a1 1 0 0 0 1-.9l.6-8.3"
                fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
      </div>

      {modalOpen && (
        <div className="ss-modal-overlay" onMouseDown={() => setModalOpen(false)}>
          <div className="ss-modal" onMouseDown={(e) => e.stopPropagation()}>
            <div className="ss-modal-title">Save Screen</div>
            <div className="ss-modal-sub">
              {screenTickers.length} ticker{screenTickers.length === 1 ? '' : 's'} from the current results
            </div>
            <input
              ref={inputRef}
              className="ss-modal-input"
              placeholder="Screen name, e.g. My Top Picks"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSave(); if (e.key === 'Escape') setModalOpen(false); }}
              maxLength={60}
            />
            <div className="ss-modal-actions">
              <button className="ss-modal-cancel" onClick={() => setModalOpen(false)}>Cancel</button>
              <button className="ss-modal-confirm" onClick={handleSave} disabled={!name.trim() || saving}>
                {saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Watchlist({ onSelect, currentSymbol, screenTickers, onLoadScreen }) {
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
      <SavedScreensPanel screenTickers={screenTickers} onLoadScreen={onLoadScreen} />

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
