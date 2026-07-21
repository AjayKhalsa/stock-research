import React, { useRef, useState, useEffect, useMemo } from 'react';
import { API_BASE, resolveSymbols } from '../api';

const STREAM_URL = `${API_BASE}/api/screen-stream`;
const ROW_HEIGHT = 86;          // fixed height enables list windowing
const VIRTUALIZE_ABOVE = 30;    // plain render below this count

// ── helpers ───────────────────────────────────────────────────────────────────

function scoreColor(score) {
  if (score == null)  return '#94a3b8';
  if (score >= 70) return '#10b981';
  if (score >= 55) return '#6366f1';
  if (score >= 40) return '#f59e0b';
  return '#ef4444';
}

const TONE = {
  strong:  { bg: 'rgba(16,185,129,0.12)', color: '#059669', border: 'rgba(16,185,129,0.5)' },
  weak:    { bg: 'rgba(239,68,68,0.10)',  color: '#dc2626', border: 'rgba(239,68,68,0.5)' },
  neutral: { bg: 'var(--bg-inset)',       color: '#64748b', border: 'var(--border-strong)' },
  indigo:  { bg: 'rgba(99,102,241,0.10)', color: '#4f46e5', border: 'rgba(99,102,241,0.5)' },
};

// Fundamental lens: business quality, independent of the chart.
function fundamentalState(r) {
  const pio = r.piotroski_score;
  const zq = r.z_quality;
  const distress = r.altman_zone === 'Distress';
  if (r.data_completeness === 'price_only' || (pio == null && zq == null)) {
    return { label: 'Fund: N/A', tone: 'neutral',
             tip: 'No fundamental data available for this stock' };
  }
  if (distress || (pio != null && pio <= 3) || (zq != null && zq <= -0.6)) {
    return { label: 'Fund: Weak', tone: 'weak',
             tip: 'Weak business quality (Piotroski / Altman / relative quality)' };
  }
  if ((pio != null && pio >= 7) || (zq != null && zq >= 0.6)) {
    return { label: 'Fund: Strong', tone: 'strong',
             tip: 'Strong business quality (Piotroski / Altman / relative quality)' };
  }
  return { label: 'Fund: Neutral', tone: 'neutral',
           tip: 'Average business quality' };
}

// Technical lens: chart posture, independent of the fundamentals.
function technicalState(r) {
  const setup = r.plan_setup;
  const trend = r.trend_score;
  if (trend != null && trend < 0) {
    return { label: 'Chart: Breakdown', tone: 'weak', kind: 'breakdown',
             tip: 'Price below the 200-DMA / downtrend structure' };
  }
  if (setup === 'breakout') {
    return { label: 'Chart: Breakout', tone: 'strong', kind: 'breakout',
             tip: 'Breaking out of resistance / 52-week-high structure' };
  }
  if (setup === 'pullback') {
    return { label: 'Chart: Pullback', tone: 'indigo', kind: 'pullback',
             tip: 'Pulling back to support within an uptrend' };
  }
  if (setup === 'trend_continuation') {
    return { label: 'Chart: Uptrend', tone: 'strong', kind: 'uptrend',
             tip: 'Established uptrend continuation' };
  }
  return { label: 'Chart: Range', tone: 'neutral', kind: 'range',
           tip: 'No actionable chart setup' };
}

// The two lenses can disagree without either being wrong. Flag the specific
// dissonance where positive price action runs against weak fundamentals.
function isSpeculative(fund, tech) {
  return fund.tone === 'weak' && (tech.kind === 'breakout' || tech.kind === 'pullback');
}

// Trade-plan bucket for the quick view filters. Mirrors the swing verdict
// vocabulary emitted by the backend (Buy / Buy on Dip / Wait / Avoid).
//   buy  -> plan is active / actionable now
//   wait -> pending breakout (untriggered) or extended / overbought setup
//   other-> Avoid or no plan (only surfaced under ALL)
function planBucket(r) {
  const v = (r.plan_verdict || '').toLowerCase();
  if (v === 'buy' || v === 'buy on dip') return 'buy';
  if (v === 'wait') return 'wait';
  return 'other';
}

// Compact monospace LTP + daily-change readout shown beside the Master Score,
// e.g. "676.00 (-1.2%)". Change is green when up, red when down.
function PriceTag({ ltp, chg }) {
  if (ltp == null) return null;
  const up = chg != null && chg >= 0;
  const chgColor = chg == null ? '#94a3b8' : up ? '#059669' : '#dc2626';
  return (
    <span style={{
      fontFamily: 'var(--font-mono)', fontSize: 11.5, fontWeight: 600,
      color: '#334155', whiteSpace: 'nowrap', letterSpacing: '-0.2px',
    }}>
      {Number(ltp).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      {chg != null && (
        <span style={{ color: chgColor, marginLeft: 4 }}>
          ({up ? '+' : ''}{chg.toFixed(1)}%)
        </span>
      )}
    </span>
  );
}

function Spinner({ color = '#f59e0b', size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16"
      style={{ animation: 'scr-spin 1s linear infinite', flexShrink: 0 }}>
      <style>{`@keyframes scr-spin{to{transform:rotate(360deg)}}`}</style>
      <circle cx={8} cy={8} r={6} fill="none" stroke="#cbd5e1" strokeWidth={2.5} />
      <path d="M8 2 A6 6 0 0 1 14 8" fill="none" stroke={color}
        strokeWidth={2.5} strokeLinecap="round" />
    </svg>
  );
}

function WarnTriangle({ size = 13 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 1.5 L15 14 H1 Z" fill="none" stroke="#d97706" strokeWidth="1.4"
        strokeLinejoin="round" />
      <rect x="7.3" y="6" width="1.4" height="4" rx="0.7" fill="#d97706" />
      <circle cx="8" cy="11.6" r="0.9" fill="#d97706" />
    </svg>
  );
}

/* Lightweight styled hover tooltip. Renders above the trigger, within row
   bounds, so it is not clipped by the scrolling panel. */
function HoverTip({ text, children }) {
  const [show, setShow] = useState(false);
  return (
    <span
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <span style={{
          position: 'absolute', bottom: 'calc(100% + 6px)', left: '50%',
          transform: 'translateX(-50%)', width: 190, zIndex: 60,
          background: '#0f172a', color: '#f1f5f9', fontSize: 10.5, lineHeight: 1.45,
          fontWeight: 500, padding: '6px 9px', borderRadius: 7,
          boxShadow: '0 8px 24px rgba(15,23,42,0.28)', pointerEvents: 'none',
          whiteSpace: 'normal', textAlign: 'left',
        }}>
          {text}
        </span>
      )}
    </span>
  );
}

function Chip({ state }) {
  const t = TONE[state.tone] || TONE.neutral;
  return (
    <span title={state.tip} style={{
      padding: '2px 7px', borderRadius: 5, fontSize: 10, fontWeight: 700,
      background: t.bg, color: t.color, border: `1px solid ${t.border}`,
      whiteSpace: 'nowrap',
    }}>{state.label}</span>
  );
}

/* Centered z-score micro-bar with its factor-definition tooltip. */
function FactorBar({ z, label, tip }) {
  const clamped = z == null ? 0 : Math.max(-2.5, Math.min(2.5, z));
  const pctW = Math.abs(clamped) / 2.5 * 50;
  const pos = clamped >= 0;
  return (
    <HoverTip text={tip}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'default' }}>
        <span style={{ fontSize: 9, color: '#94a3b8', width: 10 }}>{label}</span>
        <span style={{ position: 'relative', width: 42, height: 5, background: 'var(--border)', borderRadius: 3, display: 'inline-block' }}>
          {z != null && (
            <span style={{
              position: 'absolute', top: 0, height: 5, borderRadius: 3,
              left: pos ? '50%' : `${50 - pctW}%`, width: `${pctW}%`,
              background: pos ? '#10b981' : '#ef4444',
            }} />
          )}
          <span style={{ position: 'absolute', left: '50%', top: -1, width: 1, height: 7, background: '#cbd5e1' }} />
        </span>
      </span>
    </HoverTip>
  );
}

const FACTOR_TIPS = {
  M: 'Momentum (Cross-sectional relative strength)',
  Q: 'Quality (Piotroski & Altman health scores)',
  V: 'Value (Earnings yield & valuation)',
};

// ── compact master row (fixed height for windowing) ───────────────────────────

function MasterRow({ r, active, onSelect, style }) {
  const fund = fundamentalState(r);
  const tech = technicalState(r);
  const speculative = isSpeculative(fund, tech);

  return (
    <div
      onClick={() => onSelect(r.symbol, r)}
      style={{
        ...style,
        boxSizing: 'border-box', height: ROW_HEIGHT,
        display: 'flex', flexDirection: 'column', gap: 5,
        padding: '9px 12px', cursor: 'pointer',
        borderBottom: '1px solid var(--border)',
        background: active ? 'linear-gradient(135deg, rgba(99,102,241,0.10), rgba(139,92,246,0.06))' : 'transparent',
        borderLeft: active ? '3px solid #6366f1'
          : speculative ? '3px solid #d97706' : '3px solid transparent',
        transition: 'background 0.15s ease',
      }}
      onMouseEnter={e => { if (!active) e.currentTarget.style.background = 'var(--bg-hover)'; }}
      onMouseLeave={e => { if (!active) e.currentTarget.style.background = active ? '' : 'transparent'; }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 11, color: '#94a3b8', width: 18 }}>{r.rank ?? '·'}</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: active ? '#6366f1' : '#0f172a' }}>{r.symbol}</span>
        {r.partial_data && (
          <span title="Partial data - fundamentals unavailable, ranked on price action only"
                style={{ fontSize: 8.5, fontWeight: 700, color: '#b45309',
                         background: 'rgba(245,158,11,0.14)', border: '1px solid rgba(245,158,11,0.4)',
                         borderRadius: 4, padding: '0 4px' }}>PARTIAL</span>
        )}
        <span style={{
          marginLeft: 'auto', display: 'flex', alignItems: 'baseline', gap: 8,
        }}>
          <PriceTag ltp={r.price} chg={r.day_change_pct} />
          <span style={{ fontSize: 15, fontWeight: 700, color: scoreColor(r.score) }}>
            {r.score != null ? r.score : '·'}
          </span>
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Chip state={fund} />
        <Chip state={tech} />
        {speculative && (
          <span title="Speculative Setup: Positive price action against weak fundamentals."
                style={{ display: 'inline-flex', alignItems: 'center', marginLeft: 'auto' }}>
            <WarnTriangle />
          </span>
        )}
      </div>

      <div style={{ display: 'flex', gap: 10 }}>
        <FactorBar z={r.z_momentum} label="M" tip={FACTOR_TIPS.M} />
        <FactorBar z={r.z_quality}  label="Q" tip={FACTOR_TIPS.Q} />
        <FactorBar z={r.z_value}    label="V" tip={FACTOR_TIPS.V} />
      </div>
    </div>
  );
}

// ── windowing: render only visible rows so 400+ rows never crash the DOM ──────

function useWindowing(rowCount, rowHeight, overscan = 6) {
  const ref = useRef(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [height, setHeight] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const measure = () => setHeight(el.clientHeight);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onScroll = () => setScrollTop(ref.current?.scrollTop || 0);
  const viewport = height || 600;
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const end = Math.min(rowCount, Math.ceil((scrollTop + viewport) / rowHeight) + overscan);
  return { ref, onScroll, start, end, totalHeight: rowCount * rowHeight };
}

function VirtualList({ rows, activeSymbol, onSelect }) {
  const { ref, onScroll, start, end, totalHeight } = useWindowing(rows.length, ROW_HEIGHT);
  const small = rows.length <= VIRTUALIZE_ABOVE;

  return (
    <div ref={ref} onScroll={onScroll} style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
      {small ? (
        rows.map(r => (
          <MasterRow key={r.symbol} r={r} active={r.symbol === activeSymbol} onSelect={onSelect} />
        ))
      ) : (
        <div style={{ position: 'relative', height: totalHeight }}>
          {rows.slice(start, end).map((r, i) => (
            <MasterRow
              key={r.symbol}
              r={r}
              active={r.symbol === activeSymbol}
              onSelect={onSelect}
              style={{ position: 'absolute', top: (start + i) * ROW_HEIGHT, left: 0, right: 0 }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── quick view filter (trade-plan status) ─────────────────────────────────────

const FILTERS = [
  { key: 'all',  label: 'ALL',      tip: 'Show every ranked stock' },
  { key: 'buy',  label: 'BUY ZONE', tip: 'Trade plan is active / actionable now (Buy or Buy on Dip)' },
  { key: 'wait', label: 'WAIT',     tip: 'Pending breakouts or extended / overbought setups' },
];

function FilterBar({ active, counts, onChange }) {
  return (
    <div style={{
      display: 'flex', gap: 6, padding: '8px 12px', flexShrink: 0,
      borderBottom: '1px solid var(--border)', alignItems: 'center',
    }}>
      {FILTERS.map(f => {
        const on = active === f.key;
        return (
          <button
            key={f.key}
            onClick={() => onChange(f.key)}
            title={f.tip}
            style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '4px 9px', borderRadius: 6, cursor: 'pointer',
              fontSize: 10, fontWeight: 700, letterSpacing: '0.4px',
              textTransform: 'uppercase',
              background: on ? 'rgba(99,102,241,0.10)' : 'transparent',
              border: `1px solid ${on ? 'rgba(99,102,241,0.5)' : 'var(--border-strong)'}`,
              color: on ? '#4f46e5' : '#64748b',
              transition: 'background 0.15s ease, border-color 0.15s ease',
            }}
          >
            {f.label}
            <span style={{
              fontSize: 9.5, fontWeight: 700, fontFamily: 'var(--font-mono)',
              color: on ? '#4f46e5' : '#94a3b8',
            }}>{counts[f.key]}</span>
          </button>
        );
      })}
    </div>
  );
}

// ── main master-panel component ───────────────────────────────────────────────

const EXAMPLE = 'RELIANCE, TCS, INFY, HDFCBANK, ITC, LT, SUNPHARMA';

export default function Screener({ onSelectStock, activeSymbol, onTickersChange, loadRequest }) {
  const [input,      setInput]      = useState('');
  const [running,    setRunning]    = useState(false);
  const [logLines,   setLogLines]   = useState([]);
  const [progress,   setProgress]   = useState({ done: 0, total: 0 });
  const [rows,       setRows]        = useState(null);   // progressive + ranked
  const [ranked,     setRanked]      = useState(false);  // final result arrived
  const [error,      setError]       = useState(null);
  const [resolving,  setResolving]  = useState(false);
  const [resolution, setResolution] = useState(null);
  const [showInput,  setShowInput]  = useState(true);
  const [filter,     setFilter]     = useState('all');   // all | buy | wait

  const esRef = useRef(null);
  const fileRef = useRef(null);
  const lastSymsRef = useRef([]);     // symbols of the current list (for Refresh)

  const parseTokens = (text) => {
    const out = [];
    for (const seg of text.split(/[,;\n\r\t]+/)) {
      const s = seg.trim().replace(/\s+/g, ' ');
      if (!s) continue;
      if (s.includes(' ') && /^[A-Z0-9.&\- ]+$/.test(s) && !/\b(LTD|LIMITED)\b/.test(s)) {
        out.push(...s.split(' '));
      } else {
        out.push(s);
      }
    }
    return [...new Set(out)];
  };

  const handleFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setInput(parseTokens(String(reader.result)).join('\n'));
    reader.readAsText(file);
    e.target.value = '';
  };

  // Open the SSE stream for a resolved symbol set and populate progressively.
  const streamSymbols = (syms) => {
    if (esRef.current) { esRef.current.close(); esRef.current = null; }
    lastSymsRef.current = syms;
    onTickersChange?.(syms);   // publish the current universe for Save Screen
    setRows([]);
    setRanked(false);
    setFilter('all');
    setProgress({ done: 0, total: syms.length });
    setRunning(true);

    const es = new EventSource(`${STREAM_URL}?symbols=${encodeURIComponent(syms.join(','))}`);
    esRef.current = es;

    es.onmessage = (evt) => {
      let msg;
      try { msg = JSON.parse(evt.data); } catch { return; }

      if (msg.type === 'log') {
        setLogLines(prev => [...prev.slice(-80), msg.text]);
      } else if (msg.type === 'batch') {
        // Progressive: append this batch's rows (unranked) so the table fills.
        setRows(prev => [...(prev || []), ...msg.rows]);
        setProgress({ done: msg.done, total: msg.total });
        setShowInput(false);
      } else if (msg.type === 'result') {
        // Authoritative cross-sectionally ranked set replaces the provisional rows.
        setRows(msg.data);
        setRanked(true);
        setShowInput(false);
      } else if (msg.type === 'done') {
        setRunning(false);
        es.close(); esRef.current = null;
      } else if (msg.type === 'error') {
        setError(msg.text || 'Screen failed.');
        setRunning(false);
        es.close(); esRef.current = null;
      }
    };

    es.onerror = () => {
      if (esRef.current) {
        setError('Connection lost - is the backend running?');
        setRunning(false);
        es.close(); esRef.current = null;
      }
    };
  };

  const handleRun = async () => {
    const tokens = parseTokens(input);
    if (tokens.length < 2) {
      setError('Enter at least 2 symbols or company names to rank them against each other.');
      return;
    }
    if (running || resolving) return;

    setError(null);
    setResolution(null);
    setLogLines([]);

    let syms;
    setResolving(true);
    try {
      const resolved = await resolveSymbols(tokens);
      setResolution(resolved);
      syms = [...new Set(resolved.filter(r => r.symbol).map(r => r.symbol))];
      const unresolved = resolved.filter(r => !r.symbol);
      if (unresolved.length > 0) {
        setError(`Could not resolve: ${unresolved.map(r => `"${r.query}"`).join(', ')} - screening the rest.`);
      }
    } catch {
      syms = tokens.filter(t => !t.includes(' ')).map(t => t.toUpperCase());
    } finally {
      setResolving(false);
    }

    if (syms.length < 2) {
      setError('Fewer than 2 entries resolved to NSE symbols - nothing to rank.');
      return;
    }
    streamSymbols(syms);
  };

  // Lightweight refresh: re-stream the current symbols. Cached fundamentals
  // (4h TTL) are skipped, so this mainly re-pulls prices and re-ranks - a
  // top-level metrics refresh without re-typing the universe. Deep per-stock
  // analysis stays lazy (only on row click).
  const handleRefresh = () => {
    if (running || resolving || lastSymsRef.current.length < 2) return;
    setError(null);
    streamSymbols(lastSymsRef.current);
  };

  useEffect(() => () => { if (esRef.current) esRef.current.close(); }, []);

  // Load workflow: a saved screen selected in the sidebar streams here.
  // Keep the latest streamSymbols in a ref so the nonce-keyed effect never
  // fires on a stale closure.
  const streamRef = useRef();
  streamRef.current = streamSymbols;
  useEffect(() => {
    const req = loadRequest;
    if (req && Array.isArray(req.tickers) && req.tickers.length >= 2) {
      setError(null);
      setResolution(null);
      setLogLines([]);
      streamRef.current(req.tickers);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadRequest?.nonce]);

  const busy = running || resolving;
  const count = rows?.length || 0;

  // Bucket counts for the filter chips + the list actually rendered.
  const counts = useMemo(() => {
    const c = { all: count, buy: 0, wait: 0 };
    (rows || []).forEach(r => {
      const b = planBucket(r);
      if (b === 'buy') c.buy += 1;
      else if (b === 'wait') c.wait += 1;
    });
    return c;
  }, [rows, count]);

  const filteredRows = useMemo(() => {
    if (!rows || filter === 'all') return rows || [];
    return rows.filter(r => planBucket(r) === filter);
  }, [rows, filter]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>

      {/* panel header */}
      <div style={{
        padding: '14px 14px 10px', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
      }}>
        <span style={{ fontSize: 13, fontWeight: 800, color: '#0f172a' }}>Master Screener</span>
        {count > 0 && (
          <span style={{ fontSize: 11, color: '#94a3b8' }}>
            {count}{ranked ? ' ranked' : ` / ${progress.total}`}
          </span>
        )}
        {rows && lastSymsRef.current.length >= 2 && (
          <button
            onClick={handleRefresh}
            disabled={busy}
            title="Re-pull prices and re-rank the current list (top-level metrics only)"
            style={{
              marginLeft: 'auto', background: 'none', border: '1px solid var(--border-strong)',
              borderRadius: 6, fontSize: 11, color: busy ? '#cbd5e1' : '#4f46e5',
              cursor: busy ? 'not-allowed' : 'pointer', padding: '3px 9px', fontWeight: 600,
            }}
          >{running ? 'Refreshing...' : 'Refresh List'}</button>
        )}
        <button
          onClick={() => setShowInput(s => !s)}
          style={{
            marginLeft: (rows && lastSymsRef.current.length >= 2) ? 0 : 'auto',
            background: 'none', border: '1px solid var(--border-strong)',
            borderRadius: 6, fontSize: 11, color: '#64748b', cursor: 'pointer', padding: '3px 9px',
          }}
        >{showInput ? 'Hide input' : 'New screen'}</button>
      </div>

      {/* input area (collapsible) */}
      {showInput && (
        <div style={{ padding: 12, borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder={`NSE symbols or company names\n(one name per line), e.g.\n${EXAMPLE}`}
            rows={3}
            style={{
              width: '100%', boxSizing: 'border-box', resize: 'vertical',
              background: 'var(--bg-inset)', color: '#0f172a',
              border: '1px solid var(--border-strong)', borderRadius: 8,
              padding: '8px 10px', fontSize: 12, fontFamily: 'var(--font-mono)',
            }}
          />
          <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              onClick={handleRun}
              disabled={busy}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '6px 14px', borderRadius: 7, fontSize: 12, fontWeight: 600,
                cursor: busy ? 'not-allowed' : 'pointer',
                background: busy ? 'var(--bg-hover)' : 'linear-gradient(135deg, #2f6feb, #5b4ee9)',
                border: busy ? '1px solid var(--border-strong)' : '1px solid transparent',
                color: busy ? '#64748b' : '#fff',
              }}
            >
              {resolving ? <><Spinner /> Resolving...</>
                : running ? <><Spinner /> {progress.done}/{progress.total}...</>
                : 'Run Screen'}
            </button>
            <button onClick={() => fileRef.current?.click()} disabled={busy}
              style={{ padding: '6px 10px', borderRadius: 7, fontSize: 11, cursor: busy ? 'not-allowed' : 'pointer',
                       background: 'var(--bg-hover)', border: '1px solid var(--border-strong)', color: '#64748b' }}>
              Upload
            </button>
            <input ref={fileRef} type="file" accept=".txt,.csv" onChange={handleFile} style={{ display: 'none' }} />
            <button onClick={() => setInput(EXAMPLE)} disabled={busy}
              style={{ padding: '6px 10px', borderRadius: 7, fontSize: 11, cursor: 'pointer',
                       background: 'none', border: '1px dashed var(--border-strong)', color: '#94a3b8' }}>
              Example
            </button>
            <span style={{ fontSize: 10.5, color: '#94a3b8', marginLeft: 'auto' }}>
              {parseTokens(input).length}/500
            </span>
          </div>

          {running && (
            <div style={{ marginTop: 8 }}>
              <div style={{ height: 5, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{
                  height: 5, borderRadius: 3, background: 'linear-gradient(90deg, #2f6feb, #a78bfa)',
                  width: `${progress.total ? progress.done / progress.total * 100 : 0}%`,
                  transition: 'width 0.3s',
                }} />
              </div>
              <div style={{
                marginTop: 6, fontSize: 10.5, color: '#64748b', fontFamily: 'var(--font-mono)',
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>
                {logLines[logLines.length - 1] || 'Starting...'}
              </div>
            </div>
          )}

          {error && <div style={{ marginTop: 8, fontSize: 11.5, color: '#ef4444' }}>{error}</div>}

          {resolution && resolution.some(r => r.method !== 'symbol') && (
            <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 4, maxHeight: 90, overflowY: 'auto' }}>
              {resolution.map((r, i) => (
                <span key={i} title={r.name || ''} style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 999,
                  background: r.symbol ? 'var(--bg-inset)' : 'rgba(239,68,68,0.08)',
                  border: `1px solid ${r.symbol ? 'var(--border)' : 'rgba(239,68,68,0.4)'}`,
                  color: r.symbol ? '#64748b' : '#ef4444',
                }}>
                  {r.method === 'symbol'
                    ? <strong style={{ color: '#0f172a' }}>{r.symbol}</strong>
                    : r.symbol
                      ? <>{r.query.slice(0, 22)} -&gt; <strong style={{ color: '#0f172a' }}>{r.symbol}</strong></>
                      : <>{r.query.slice(0, 26)} (unresolved)</>}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* quick view filters + windowed ranked list */}
      {count > 0 ? (
        <>
          <FilterBar active={filter} counts={counts} onChange={setFilter} />
          {filteredRows.length > 0 ? (
            <VirtualList key={filter} rows={filteredRows} activeSymbol={activeSymbol} onSelect={onSelectStock} />
          ) : (
            <div style={{
              flex: 1, minHeight: 0, display: 'flex', alignItems: 'center',
              justifyContent: 'center', padding: '32px 18px', textAlign: 'center',
              color: '#94a3b8', fontSize: 12, lineHeight: 1.6,
            }}>
              {filter === 'buy'
                ? 'No stocks in the buy zone right now.'
                : 'No pending or extended setups right now.'}
            </div>
          )}
        </>
      ) : (
        <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
          {!running && (
            <div style={{ padding: '36px 18px', textAlign: 'center', color: '#94a3b8', fontSize: 12, lineHeight: 1.7 }}>
              Run a screen to rank stocks here.<br />
              Click any result to open its full analysis.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
