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
import TradePlan      from './components/TradePlan';
import BottomLine     from './components/BottomLine';
import MarketRegime   from './components/MarketRegime';
import Gatekeeper     from './components/Gatekeeper';
import KiteGTT        from './components/KiteGTT';
import FactorReportCard from './components/FactorReportCard';
import AuditTabs      from './components/AuditTabs';
import { getStock, getAlpha, getPlan } from './api';
import './App.css';

export default function App() {
  const [currentSymbol, setCurrentSymbol] = useState(null);

  // Master screener panel (collapsible left workspace)
  const [isMasterOpen, setIsMasterOpen] = useState(true);
  // The screener row for the selected stock (carries cross-sectional z-scores)
  const [selectedRow, setSelectedRow] = useState(null);

  // Phase 1 — base data (fast)
  const [stockData,    setStockData]    = useState(null);
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState(null);

  // Phase 2 — AI + quant data (slow, runs in background after phase 1)
  const [alphaData,    setAlphaData]    = useState(null);
  const [alphaLoading, setAlphaLoading] = useState(false);
  const [alphaError,   setAlphaError]   = useState(null);

  // Phase 1.5 — trade decision plan (fires alongside alpha, lands sooner)
  const [planData,    setPlanData]    = useState(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planHorizon, setPlanHorizon] = useState('swing');

  // Stale-request guard: increments on every new symbol load
  const alphaSeqRef = useRef(0);

  const loadStock = useCallback(async (symbol, exchangeOrRow = 'NSE', row = null) => {
    // Screener passes (symbol, rowObject); search/watchlist pass (symbol, exchange)
    let exchange = 'NSE';
    if (typeof exchangeOrRow === 'string') exchange = exchangeOrRow;
    else if (exchangeOrRow && typeof exchangeOrRow === 'object') row = exchangeOrRow;
    setSelectedRow(row || null);

    setLoading(true);
    setError(null);
    setStockData(null);
    setAlphaData(null);
    setAlphaError(null);
    setPlanData(null);

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

    // ── Phase 1.5 + 2: trade plan and alpha fire concurrently ─────────────
    const seq = ++alphaSeqRef.current;
    setAlphaLoading(true);
    setPlanLoading(true);

    const planPromise = (async () => {
      try {
        const plan = await getPlan(symbol, exchange);
        if (alphaSeqRef.current === seq) setPlanData(plan);
      } catch (e) {
        console.warn('[plan]', e);
      } finally {
        if (alphaSeqRef.current === seq) setPlanLoading(false);
      }
    })();

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
    await planPromise;
  }, []);

  // ── Gatekeeper: structural override on broken setups ─────────────────────
  const swing = planData?.swing;
  const ma200 = planData?.key_levels?.ma200;
  const gatekeeperActive = !!planData && !planData.error && (
    swing?.verdict === 'Avoid' ||
    (planData.price != null && ma200 != null && planData.price < ma200)
  );

  return (
    <div className="app-layout">
      <Toaster position="top-right" toastOptions={{
        style: { background: '#ffffff', color: '#0f172a', border: '1px solid rgba(15,23,42,0.1)', borderRadius: 12, boxShadow: '0 8px 24px rgba(16,24,40,0.12)' }
      }} />

      {/* ── Far-left rail: brand + watchlist/alerts hub ── */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <span className="logo-icon">📈</span>
          <span className="logo-text">StockLens</span>
        </div>
        <Watchlist onSelect={loadStock} currentSymbol={currentSymbol?.symbol} />
      </aside>

      {/* ── Master screener panel (collapsible) ── */}
      <div className={`master-panel ${isMasterOpen ? 'open' : 'closed'}`}>
        <div className="master-panel-inner">
          <Screener onSelectStock={loadStock} activeSymbol={currentSymbol?.symbol} />
        </div>
      </div>

      {/* ── Divider with toggle chevron ── */}
      <div className="master-divider">
        <button
          className="master-toggle"
          onClick={() => setIsMasterOpen(o => !o)}
          title={isMasterOpen ? 'Collapse screener panel' : 'Expand screener panel'}
        >
          {isMasterOpen ? '◀' : '▶'}
        </button>
      </div>

      {/* ── Detail panel ── */}
      <main className="main-content">
        <div className="top-bar" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <SearchBar onSelect={loadStock} />
        </div>

        <div className="detail-scroll">
          <div style={{ padding: '14px 28px 0' }}>
            <MarketRegime />
          </div>

          {!currentSymbol && !loading && (
            <div className="empty-state">
              <div className="empty-icon">🔍</div>
              <h2>Search or screen any Indian stock</h2>
              <p>Run a screen in the left panel and click a result, or search directly.
                 Every stock gets a trade plan, evidence dossier, and reconciled bottom line.</p>
              <div className="popular-stocks">
                <span className="popular-label">Popular:</span>
                {['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'SUNPHARMA'].map(s => (
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
            <>
              <div className="dashboard-grid">

                {/* ── Tier 1 + chart: identity, price, dual conviction, channels ── */}
                <OverviewCard
                  data={stockData}
                  planLevels={planData?.[planHorizon]}
                  synthesis={alphaData?.trade_plans?.synthesis || planData?.synthesis}
                />

                {/* ── Bottom Line: reconciled verdict across all lenses ── */}
                <BottomLine
                  synthesis={alphaData?.trade_plans?.synthesis || planData?.synthesis}
                  loading={planLoading}
                  alphaLoading={alphaLoading}
                />

                {/* ── Gatekeeper override OR the active trade workspace ── */}
                {gatekeeperActive ? (
                  <Gatekeeper planData={planData} />
                ) : (
                  <>
                    {selectedRow && <FactorReportCard row={selectedRow} />}
                    {planData && !planData.error && swing?.entry && (
                      <KiteGTT plan={swing} livePrice={stockData.live_price} symbol={currentSymbol?.symbol} />
                    )}
                    <TradePlan
                      data={planData}
                      loading={planLoading}
                      horizon={planHorizon}
                      onHorizonChange={setPlanHorizon}
                      aiCommentary={alphaData?.alpha_thesis?.plan_commentary}
                      symbol={currentSymbol?.symbol}
                      exchange={currentSymbol?.exchange}
                    />
                  </>
                )}

                {/* ── Tier 5: narrative + stakeholder footprint ── */}
                {alphaError && (
                  <div className="error-banner" style={{ margin: 0 }}>⚠️ {alphaError}</div>
                )}
                <AlphaThesis data={alphaData?.alpha_thesis} loading={alphaLoading} />

                <div className="grid-row-2">
                  <QuarterlyResults data={stockData.quarterly_results} />
                  <Shareholding
                    data={stockData.shareholding}
                    announcements={alphaData?.bse_announcements}
                  />
                </div>
              </div>

              {/* ── Tier 6: sticky tabbed audit trail ── */}
              <AuditTabs
                technicals={<Technicals data={stockData.technicals} livePrice={stockData.live_price}
                                        dossier={planData?.dossier} />}
                fundamentals={<QuantScores data={alphaData?.quant} loading={alphaLoading} />}
                news={<NewsFeed news={stockData.news}
                                announcements={alphaData?.bse_announcements}
                                sentiment={alphaData?.sentiment} />}
              />
            </>
          )}
        </div>
      </main>
    </div>
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
