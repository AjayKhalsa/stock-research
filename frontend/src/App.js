import React, { useState, useCallback, useRef } from 'react';
import { Toaster } from 'react-hot-toast';
import SearchBar      from './components/SearchBar';
import Watchlist      from './components/Watchlist';
import OverviewCard   from './components/OverviewCard';
import QuarterlyResults from './components/QuarterlyResults';
import Shareholding   from './components/Shareholding';
import NewsFeed       from './components/NewsFeed';
import Technicals     from './components/Technicals';
import AlphaThesis    from './components/AlphaThesis';
import QuantScores    from './components/QuantScores';
import Screener       from './components/Screener';
import { getStock, getAlpha } from './api';
import './App.css';

export default function App() {
  // 'research' | 'screener'
  const [view, setView] = useState('research');

  const [currentSymbol, setCurrentSymbol] = useState(null);

  // Phase 1 — base data (fast)
  const [stockData,    setStockData]    = useState(null);
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState(null);

  // Phase 2 — AI + quant data (slow, runs in background after phase 1)
  const [alphaData,    setAlphaData]    = useState(null);
  const [alphaLoading, setAlphaLoading] = useState(false);
  const [alphaError,   setAlphaError]   = useState(null);

  // Stale-request guard: increments on every new symbol load
  const alphaSeqRef = useRef(0);

  const loadStock = useCallback(async (symbol, exchange = 'NSE') => {
    setView('research');   // switch to research view when a stock is selected
    // Reset everything
    setLoading(true);
    setError(null);
    setStockData(null);
    setAlphaData(null);
    setAlphaError(null);

    // ── Phase 1: base endpoint ─────────────────────────────────────────────
    let baseData;
    try {
      baseData = await getStock(symbol, exchange);
      setStockData(baseData);
      setCurrentSymbol({ symbol, exchange });
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load stock data. Please try again.');
      setLoading(false);
      return;
    }
    setLoading(false);

    // ── Phase 2: alpha endpoint (AI + quant, takes 5-15 s) ────────────────
    const seq = ++alphaSeqRef.current;
    setAlphaLoading(true);
    try {
      const alpha = await getAlpha(symbol, exchange);
      if (alphaSeqRef.current === seq) setAlphaData(alpha);
    } catch (e) {
      if (alphaSeqRef.current === seq)
        setAlphaError('AI analysis unavailable — check backend or Gemini API key.');
      console.warn('[alpha]', e);
    } finally {
      if (alphaSeqRef.current === seq) setAlphaLoading(false);
    }
  }, []);

  return (
    <div className="app-layout">
      <Toaster position="top-right" toastOptions={{
        style: { background: '#ffffff', color: '#0f172a', border: '1px solid rgba(15,23,42,0.1)', borderRadius: 12, boxShadow: '0 8px 24px rgba(16,24,40,0.12)' }
      }} />

      <aside className="sidebar">
        <div className="sidebar-logo">
          <span className="logo-icon">📈</span>
          <span className="logo-text">StockLens</span>
        </div>
        <Watchlist onSelect={loadStock} currentSymbol={currentSymbol?.symbol} />
      </aside>

      <main className="main-content">
        {/* ── Top bar: search + nav tabs ──────────────────────────────────── */}
        <div className="top-bar" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <SearchBar onSelect={loadStock} />
          <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
            <NavTab
              active={view === 'research'}
              onClick={() => setView('research')}
              icon="🔍"
              label="Research"
            />
            <NavTab
              active={view === 'screener'}
              onClick={() => setView('screener')}
              icon="📊"
              label="Screener"
            />
          </div>
        </div>

        {/* ── Swing screener view ──────────────────────────────────────────── */}
        {view === 'screener' && (
          <Screener onSelectStock={(symbol) => loadStock(symbol)} />
        )}

        {/* ── Stock Research view ──────────────────────────────────────────── */}
        {view === 'research' && (
          <>
            {!currentSymbol && !loading && (
              <div className="empty-state">
                <div className="empty-icon">🔍</div>
                <h2>Search for any Indian stock</h2>
                <p>Fundamental analysis, AI alpha thesis, quant scores, technicals and news — all in one place.</p>
                <div className="popular-stocks">
                  <span className="popular-label">Popular:</span>
                  {['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'WIPRO'].map(s => (
                    <button key={s} className="chip-btn" onClick={() => loadStock(s)}>{s}</button>
                  ))}
                </div>
              </div>
            )}

            {loading && <LoadingSkeleton />}

            {error && !loading && (
              <div className="error-banner"><span>⚠️ {error}</span></div>
            )}

            {stockData && !loading && (
              <div className="dashboard-grid">

                {/* ── Phase-1 panels (always visible once loaded) ── */}
                <OverviewCard data={stockData} onAddWatchlist={currentSymbol} />

                <div className="grid-row-2">
                  <QuarterlyResults data={stockData.quarterly_results} />
                  <Shareholding data={stockData.shareholding} />
                </div>

                <Technicals data={stockData.technicals} livePrice={stockData.live_price} />

                {/* ── Phase-2 panels (appear / fill in once alpha loads) ── */}
                {alphaError && (
                  <div className="error-banner" style={{ margin: 0 }}>
                    ⚠️ {alphaError}
                  </div>
                )}

                <AlphaThesis data={alphaData?.alpha_thesis} loading={alphaLoading} />
                <QuantScores  data={alphaData?.quant}        loading={alphaLoading} />

                {/* ── News + BSE Filings ── */}
                <NewsFeed
                  news={stockData.news}
                  announcements={alphaData?.bse_announcements}
                  sentiment={alphaData?.sentiment}
                />

              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function NavTab({ active, onClick, icon, label }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: 7,
        padding: '8px 18px', borderRadius: 999, cursor: 'pointer',
        fontFamily: 'inherit',
        border: active ? '1px solid rgba(99,102,241,0.45)' : '1px solid var(--border-strong)',
        background: active
          ? 'linear-gradient(135deg, rgba(99,102,241,0.16), rgba(139,92,246,0.14))'
          : 'transparent',
        color: active ? 'var(--accent-blue)' : 'var(--text-secondary)',
        fontSize: 13, fontWeight: 600,
        boxShadow: active ? '0 0 18px rgba(99,102,241,0.15)' : 'none',
        transition: 'all 0.2s ease',
        whiteSpace: 'nowrap',
      }}
    >
      <span>{icon}</span>
      <span>{label}</span>
    </button>
  );
}

function LoadingSkeleton() {
  return (
    <div className="dashboard-grid">
      <div className="card" style={{ padding: 24 }}>
        <div className="skeleton" style={{ height: 32, width: '40%', marginBottom: 16 }} />
        <div className="skeleton" style={{ height: 48, width: '30%', marginBottom: 8 }} />
        <div style={{ display: 'flex', gap: 16, marginTop: 24 }}>
          {[1,2,3,4,5,6].map(i => (
            <div key={i} style={{ flex: 1 }}>
              <div className="skeleton" style={{ height: 16, marginBottom: 6 }} />
              <div className="skeleton" style={{ height: 24 }} />
            </div>
          ))}
        </div>
      </div>
      <div className="grid-row-2">
        <div className="card" style={{ padding: 24, height: 350 }}>
          <div className="skeleton" style={{ height: 20, width: '30%', marginBottom: 16 }} />
          <div className="skeleton" style={{ height: 280 }} />
        </div>
        <div className="card" style={{ padding: 24, height: 350 }}>
          <div className="skeleton" style={{ height: 20, width: '30%', marginBottom: 16 }} />
          <div className="skeleton" style={{ height: 280 }} />
        </div>
      </div>
    </div>
  );
}
