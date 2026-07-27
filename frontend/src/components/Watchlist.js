import React, { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import toast from 'react-hot-toast';
import {
  getWatchlist, removeFromWatchlist, getWatchlistPulse, getAlerts, ackAlert, deleteAlert,
  getScreens, getScreen, saveScreen, deleteScreen,
  getChartinkUrl, setChartinkUrl, getChartinkScanClause, setChartinkScanClause,
  getPaperTradeStats, getPaperTradesList, getAutoScreenStatus,
} from '../api';

import './Watchlist.css';

const CHARTINK_SCREEN_NAME = 'Daily Chartink Auto-Run';

function formatAgeMinutes(mins) {
  if (mins == null) return '';
  if (mins < 60) return `${Math.round(mins)}m ago`;
  return `${(mins / 60).toFixed(1)}h ago`;
}

/* Save/load panel for named screens. Sits at the very top of the sidebar. */
function SavedScreensPanel({ screenTickers, onLoadScreen }) {
  const [screens, setScreens] = useState([]);
  const [selected, setSelected] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const inputRef = useRef(null);

  // Chartink daily auto-fetcher — the URL a server-side cron scrapes each
  // day into the "Daily Chartink Auto-Run" saved screen above.
  const [chartinkUrl, setChartinkUrlState] = useState('');
  // Optional scan_clause override — most screener pages build this with
  // client-side JS, so it's invisible to the plain-HTML scraper; storing the
  // real value here (copied once from the browser) skips that guesswork.
  const [chartinkScanClause, setChartinkScanClauseState] = useState('');
  const [editingLink, setEditingLink] = useState(false);
  const [linkDraft, setLinkDraft] = useState('');
  const [scanClauseDraft, setScanClauseDraft] = useState('');
  const [savingLink, setSavingLink] = useState(false);
  const linkInputRef = useRef(null);
  // Last (or in-progress) cron run outcome — so a failed/stalled auto-fetch
  // is visible here instead of only in Render's logs.
  const [runStatus, setRunStatus] = useState(null);

  const refresh = useCallback(async () => {
    try { setScreens(await getScreens()); } catch {}
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { if (modalOpen) setTimeout(() => inputRef.current?.focus(), 30); }, [modalOpen]);

  useEffect(() => {
    getChartinkUrl().then(r => setChartinkUrlState(r.url || '')).catch(() => {});
    getChartinkScanClause().then(r => setChartinkScanClauseState(r.scan_clause || '')).catch(() => {});
  }, []);
  useEffect(() => { if (editingLink) setTimeout(() => linkInputRef.current?.focus(), 30); }, [editingLink]);

  useEffect(() => {
    const poll = () => getAutoScreenStatus().then(setRunStatus).catch(() => {});
    poll();
    const interval = setInterval(poll, 60000);
    return () => clearInterval(interval);
  }, []);

  const hasAutoRunScreen = screens.some(s => s.name === CHARTINK_SCREEN_NAME);

  const handleEditLink = () => {
    setLinkDraft(chartinkUrl);
    setScanClauseDraft(chartinkScanClause);
    setEditingLink(true);
  };

  const handleSaveLink = async () => {
    const trimmedUrl = linkDraft.trim();
    const trimmedClause = scanClauseDraft.trim();
    setSavingLink(true);
    try {
      const [urlRec, clauseRec] = await Promise.all([
        setChartinkUrl(trimmedUrl),
        setChartinkScanClause(trimmedClause),
      ]);
      setChartinkUrlState(urlRec.url || '');
      setChartinkScanClauseState(clauseRec.scan_clause || '');
      setEditingLink(false);
      toast.success(trimmedUrl ? 'Chartink settings saved' : 'Chartink link cleared');
    } catch {
      toast.error('Could not save the Chartink settings');
    } finally {
      setSavingLink(false);
    }
  };

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

      <div className="ce-row">
        <span className="ce-label" title="A server-side cron scrapes this Chartink screener daily into the &quot;Daily Chartink Auto-Run&quot; saved screen above.">
          {hasAutoRunScreen ? 'Chartink Auto-Fetch' : 'Chartink Auto-Fetch (not yet run)'}
        </span>
        {!editingLink && (
          <button className="ce-edit-btn" onClick={handleEditLink} title="Edit the Chartink screener URL">
            ⚙️ Edit Link
          </button>
        )}
      </div>
      {!editingLink && (
        <div className="ce-current" title={chartinkUrl || undefined}>
          {chartinkUrl || 'No URL configured'}
        </div>
      )}
      {!editingLink && chartinkUrl && (
        <div className="ce-clause-note" title={chartinkScanClause || undefined}>
          {chartinkScanClause
            ? 'Scan clause: configured (skips auto-detect)'
            : 'Scan clause: not set — relying on auto-detect, which fails for most screens'}
        </div>
      )}
      {!editingLink && runStatus?.status === 'running' && (
        <div className="ce-status ce-status-running">
          Running… {runStatus.done ?? 0}/{runStatus.total ?? '?'} fetched
        </div>
      )}
      {!editingLink && runStatus?.status === 'error' && (
        <div className="ce-status ce-status-error" title={runStatus.error || ''}>
          Last run FAILED {formatAgeMinutes(runStatus.age_minutes)}
          {runStatus.error ? ` — ${runStatus.error}` : ''}
        </div>
      )}
      {!editingLink && runStatus?.status === 'done' && (
        <div className={`ce-status ${runStatus.count ? 'ce-status-ok' : 'ce-status-error'}`}
             title={runStatus.error || ''}>
          {runStatus.count
            ? `Last run: ${formatAgeMinutes(runStatus.age_minutes)} · ${runStatus.count} matched`
            : `Last run: ${formatAgeMinutes(runStatus.age_minutes)} · ${runStatus.error || 'no matches'}`}
        </div>
      )}
      {editingLink && (
        <div className="ce-edit-form">
          <input
            ref={linkInputRef}
            className="ce-input"
            placeholder="https://chartink.com/screener/..."
            value={linkDraft}
            onChange={(e) => setLinkDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Escape') setEditingLink(false); }}
          />
          <textarea
            className="ce-textarea"
            placeholder="Scan clause (optional, but usually required) — e.g. ( {cash} ( daily close > 20 and ... ) )"
            value={scanClauseDraft}
            onChange={(e) => setScanClauseDraft(e.target.value)}
            rows={3}
          />
          <div className="ce-clause-help">
            Chartink builds this with page JavaScript, so it's rarely visible in the raw
            HTML — copy it from your browser's DevTools (Network tab → the "process" request
            when you click Run Scan → its form payload) and paste it here once. Leave blank
            to fall back to best-effort auto-detection.
          </div>
          <div className="ce-edit-actions">
            <button className="ce-save-btn" onClick={handleSaveLink} disabled={savingLink}>
              {savingLink ? '...' : 'Save'}
            </button>
            <button className="ce-cancel-btn" onClick={() => setEditingLink(false)} disabled={savingLink}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {modalOpen && createPortal(
        // Portalled to <body>: the sidebar's backdrop-filter (frosted glass)
        // creates a CSS containing block for any position:fixed descendant,
        // which was pinning this overlay inside the 250px sidebar column
        // instead of covering the viewport. Escaping via a portal sidesteps
        // that regardless of what CSS the sidebar (or any ancestor) uses.
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
        </div>,
        document.body
      )}
    </div>
  );
}

function statusTone(status) {
  if (status === 'WIN_T1' || status === 'WIN_T2') return 'win';
  if (status === 'STOPPED_OUT') return 'loss';
  return 'active';
}

/* Persistent forward-testing scorecard. Sits in the always-visible sidebar
   (never behind the collapsible screener panel) so the system's real,
   running track record is never more than a glance away. */
function ScorecardWidget() {
  const [stats, setStats] = useState(null);   // null = not loaded yet
  const [showLog, setShowLog] = useState(false);
  const [trades, setTrades] = useState([]);
  const [loadingTrades, setLoadingTrades] = useState(false);

  const refreshStats = useCallback(async () => {
    try { setStats(await getPaperTradeStats()); } catch {}
  }, []);

  useEffect(() => {
    refreshStats();
    const interval = setInterval(refreshStats, 60000);
    return () => clearInterval(interval);
  }, [refreshStats]);

  const openLog = async () => {
    setShowLog(true);
    setLoadingTrades(true);
    try {
      setTrades(await getPaperTradesList());
    } catch {
      toast.error('Could not load the trade log');
    } finally {
      setLoadingTrades(false);
    }
  };

  if (stats === null) return null;   // avoid flashing an empty state on load

  const expColor = stats.net_pnl_r > 0 ? '#34d399' : stats.net_pnl_r < 0 ? '#f87171' : '#94a3b8';

  return (
    <div className="pt-scorecard">
      <div className="pt-scorecard-header">
        <span className="pt-scorecard-title">🧪 System Scorecard</span>
      </div>

      {stats.total_trades === 0 ? (
        <div className="pt-scorecard-empty">
          No paper trades logged yet — use "🧪 Paper Trade This Setup" on any Trade Plan.
        </div>
      ) : (
        <div className="pt-scorecard-rows">
          <div className="pt-scorecard-row">
            <span className="pt-scorecard-label">Win Rate</span>
            <span className="pt-scorecard-value">
              {stats.win_rate_pct}%
              <span className="pt-scorecard-sub"> ({stats.wins}W / {stats.losses}L)</span>
            </span>
          </div>
          <div className="pt-scorecard-row">
            <span className="pt-scorecard-label">Net Expectancy</span>
            <span className="pt-scorecard-value" style={{ color: expColor }}>
              {stats.net_pnl_r > 0 ? '+' : ''}{stats.net_pnl_r}R
            </span>
          </div>
          <div className="pt-scorecard-row">
            <span className="pt-scorecard-label">Active Paper Trades</span>
            <span className="pt-scorecard-value">{stats.active_count} Pending</span>
          </div>
        </div>
      )}

      <button className="pt-scorecard-log-btn" onClick={openLog}>View Trade Log</button>

      {showLog && createPortal(
        <div className="ss-modal-overlay" onMouseDown={() => setShowLog(false)}>
          <div className="ss-modal pt-log-modal" onMouseDown={(e) => e.stopPropagation()}>
            <div className="ss-modal-title">Paper Trade Log</div>
            <div className="ss-modal-sub">
              {trades.length} trade{trades.length === 1 ? '' : 's'} logged
            </div>
            <div className="pt-log-table-wrap">
              {loadingTrades ? (
                <div className="pt-log-empty">Loading…</div>
              ) : trades.length === 0 ? (
                <div className="pt-log-empty">No trades logged yet.</div>
              ) : (
                <table className="pt-log-table">
                  <thead>
                    <tr><th>Symbol</th><th>Entry Date</th><th>Entry</th><th>Status</th><th>R</th></tr>
                  </thead>
                  <tbody>
                    {trades.map(t => (
                      <tr key={t.id}>
                        <td className="pt-log-symbol">{t.symbol}</td>
                        <td>{String(t.entry_date || t.created_at).slice(0, 10)}</td>
                        <td>₹{Number(t.entry_price).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                        <td><span className={`pt-badge ${statusTone(t.status)}`}>{t.status}</span></td>
                        <td className={t.pnl_r > 0 ? 'pt-r-pos' : t.pnl_r < 0 ? 'pt-r-neg' : ''}>
                          {t.pnl_r > 0 ? '+' : ''}{t.pnl_r}R
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="ss-modal-actions">
              <button className="ss-modal-cancel" onClick={() => setShowLog(false)}>Close</button>
            </div>
          </div>
        </div>,
        document.body
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
      <ScorecardWidget />

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
