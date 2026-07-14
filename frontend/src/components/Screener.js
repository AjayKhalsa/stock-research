import React, { useRef, useState } from 'react';
import { API_BASE } from '../api';

const STREAM_URL = `${API_BASE}/api/screen-stream`;

// ── helpers ───────────────────────────────────────────────────────────────────

function scoreColor(score) {
  if (score == null)  return '#94a3b8';
  if (score >= 70) return '#10b981';
  if (score >= 55) return '#6366f1';
  if (score >= 40) return '#f59e0b';
  return '#ef4444';
}

function verdictStyle(verdict = '') {
  if (verdict === 'Strong Candidate') return { bg: 'rgba(16,185,129,0.12)', color: '#10b981', border: '#10b981' };
  if (verdict === 'Buy Watch')        return { bg: 'rgba(99,102,241,0.10)', color: '#6366f1', border: '#6366f1' };
  if (verdict === 'Neutral')          return { bg: 'rgba(245,158,11,0.14)', color: '#f59e0b', border: '#f59e0b' };
  return { bg: 'rgba(239,68,68,0.10)', color: '#ef4444', border: '#ef4444' };
}

function pct(v, digits = 1) {
  if (v == null) return '-';
  return `${(v * 100).toFixed(digits)}%`;
}

function num(v, digits = 2) {
  if (v == null) return '-';
  return Number(v).toFixed(digits);
}

function trendLabel(t) {
  if (t === 2)  return { txt: 'Strong Up', color: '#10b981' };
  if (t === 1)  return { txt: 'Up',        color: '#34d399' };
  if (t === -1) return { txt: 'Down',      color: '#ea580c' };
  if (t === -2) return { txt: 'Strong Dn', color: '#ef4444' };
  return { txt: 'Flat', color: '#64748b' };
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

function ZBar({ z }) {
  // z in roughly [-2.5, +2.5]; render a centered bar
  if (z == null) return <span style={{ color: '#94a3b8', fontSize: 12 }}>-</span>;
  const clamped = Math.max(-2.5, Math.min(2.5, z));
  const pctW = Math.abs(clamped) / 2.5 * 50;
  const pos = clamped >= 0;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ position: 'relative', width: 70, height: 8, background: 'var(--border)', borderRadius: 4 }}>
        <div style={{
          position: 'absolute', top: 0, height: 8, borderRadius: 4,
          left: pos ? '50%' : `${50 - pctW}%`, width: `${pctW}%`,
          background: pos ? '#10b981' : '#ef4444',
        }} />
        <div style={{ position: 'absolute', left: '50%', top: -1, width: 1, height: 10, background: '#94a3b8' }} />
      </div>
      <span style={{ fontSize: 11, color: pos ? '#10b981' : '#ef4444', minWidth: 32 }}>
        {z > 0 ? '+' : ''}{z.toFixed(2)}
      </span>
    </div>
  );
}

// ── result row ────────────────────────────────────────────────────────────────

function ResultRow({ r, onSelectStock, techAvailable }) {
  const [open, setOpen] = useState(false);
  const vs = verdictStyle(r.verdict);
  const trend = trendLabel(r.trend_score);

  return (
    <>
      <tr
        onClick={() => setOpen(o => !o)}
        style={{ cursor: 'pointer', borderBottom: '1px solid var(--border)', background: open ? 'var(--bg-hover)' : 'transparent' }}
      >
        <td style={{ padding: '10px 8px', color: '#64748b', fontSize: 13 }}>{r.rank}</td>
        <td style={{ padding: '10px 8px' }}>
          <button
            onClick={(e) => { e.stopPropagation(); onSelectStock(r.symbol); }}
            style={{
              background: 'none', border: 'none', padding: 0, cursor: 'pointer',
              color: '#6366f1', fontSize: 14, fontWeight: 700, textDecoration: 'underline',
            }}
          >{r.symbol}</button>
          <div style={{ fontSize: 11, color: '#64748b', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {r.company_name}
          </div>
        </td>
        <td style={{ padding: '10px 8px' }}>
          <span style={{
            fontSize: 16, fontWeight: 700, color: scoreColor(r.score),
          }}>{r.score != null ? r.score : '-'}</span>
        </td>
        <td style={{ padding: '10px 8px' }}>
          <span style={{
            padding: '3px 8px', borderRadius: 6, fontSize: 11, fontWeight: 700,
            background: vs.bg, color: vs.color, border: `1px solid ${vs.border}`,
            whiteSpace: 'nowrap',
          }}>{r.verdict}</span>
        </td>
        <td style={{ padding: '10px 8px' }}><ZBar z={r.z_momentum} /></td>
        <td style={{ padding: '10px 8px' }}><ZBar z={r.z_quality} /></td>
        <td style={{ padding: '10px 8px' }}><ZBar z={r.z_value} /></td>
        <td style={{ padding: '10px 8px', fontSize: 12, color: r.ret_3m > 0 ? '#10b981' : '#ef4444' }}>
          {pct(r.ret_3m)}
        </td>
        <td style={{ padding: '10px 8px', fontSize: 12, color: trend.color, whiteSpace: 'nowrap' }}>{trend.txt}</td>
        <td style={{ padding: '10px 8px', fontSize: 12, color: '#0f172a' }}>
          {r.piotroski_score != null ? `${r.piotroski_score}/9` : '-'}
        </td>
        <td style={{ padding: '10px 8px' }}>
          {r.flags?.length > 0
            ? <span style={{ fontSize: 12, color: '#ea580c' }} title={r.flags.join('\n')}>{r.flags.length} flag{r.flags.length > 1 ? 's' : ''}</span>
            : <span style={{ fontSize: 12, color: '#10b981' }}>clean</span>}
        </td>
      </tr>

      {open && (
        <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-card)' }}>
          <td colSpan={11} style={{ padding: '14px 18px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16 }}>

              <div>
                <div style={detailHead}>Momentum</div>
                <DetailLine label="1M / 3M / 6M" value={`${pct(r.ret_1m)} / ${pct(r.ret_3m)} / ${pct(r.ret_6m)}`} />
                <DetailLine label="12-1 momentum" value={pct(r.mom_12_1)} />
                <DetailLine label="52w-high proximity" value={r.prox_52w != null ? `${(r.prox_52w * 100).toFixed(0)}%` : '-'} />
                <DetailLine label="Risk-adj momentum" value={num(r.risk_adj_mom)} />
                <DetailLine label="Volume surge (20/60d)" value={r.vol_ratio != null ? `${r.vol_ratio}x` : '-'} />
              </div>

              <div>
                <div style={detailHead}>Technicals</div>
                <DetailLine label="RSI(14)" value={num(r.rsi, 1)} />
                <DetailLine label="MACD histogram" value={num(r.macd_hist, 2)} />
                <DetailLine label="ATR %" value={r.atr_pct != null ? `${r.atr_pct}%` : '-'} />
                <DetailLine label="Ann. volatility" value={pct(r.vol_ann, 0)} />
              </div>

              <div>
                <div style={detailHead}>Fundamentals</div>
                <DetailLine label="Piotroski" value={r.piotroski_score != null ? `${r.piotroski_score}/9` : '-'} />
                <DetailLine label="Altman Z" value={`${num(r.altman_z)} (${r.altman_zone || '-'})`} />
                <DetailLine label="Beneish M" value={num(r.beneish_m, 3)} />
                <DetailLine label="ROE / ROCE" value={`${num(r.roe, 1)}% / ${num(r.roce, 1)}%`} />
                <DetailLine label="P/E / P/B" value={`${num(r.pe_ratio, 1)} / ${num(r.pb_ratio, 1)}`} />
                <DetailLine label="Earnings yield" value={pct(r.earnings_yield)} />
                <DetailLine label="D/E" value={num(r.debt_to_equity)} />
              </div>

              {techAvailable && r.price != null && (
                <div>
                  <div style={detailHead}>Swing Levels (ATR-based)</div>
                  <DetailLine label="Last price" value={`₹${r.price?.toLocaleString('en-IN')}`} />
                  <DetailLine label="Stop (2 ATR)" value={r.stop != null ? `₹${r.stop.toLocaleString('en-IN')}` : '-'} color="#ef4444" />
                  <DetailLine label="Target (3 ATR)" value={r.target != null ? `₹${r.target.toLocaleString('en-IN')}` : '-'} color="#10b981" />
                  <DetailLine label="Reward : Risk" value="1.5 : 1" />
                </div>
              )}

            </div>

            {r.flags?.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div style={{ ...detailHead, color: '#ea580c' }}>Flags</div>
                {r.flags.map((f, i) => (
                  <div key={i} style={{ fontSize: 12, color: '#ea580c', marginBottom: 3 }}>! {f}</div>
                ))}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

const detailHead = {
  fontSize: 11, fontWeight: 700, color: '#6366f1',
  textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6,
};

function DetailLine({ label, value, color }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 12, marginBottom: 3 }}>
      <span style={{ color: '#64748b' }}>{label}</span>
      <span style={{ color: color || '#0f172a', fontWeight: 500 }}>{value}</span>
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────────

const EXAMPLE = 'RELIANCE, TCS, INFY, HDFCBANK, TATAMOTORS, ITC, LT, SUNPHARMA';

export default function Screener({ onSelectStock }) {
  const [input,      setInput]      = useState('');
  const [running,    setRunning]    = useState(false);
  const [logLines,   setLogLines]   = useState([]);
  const [progress,   setProgress]   = useState({ done: 0, total: 0 });
  const [results,    setResults]    = useState(null);
  const [techAvail,  setTechAvail]  = useState(true);
  const [error,      setError]      = useState(null);

  const esRef = useRef(null);
  const fileRef = useRef(null);

  const parseSymbols = (text) =>
    [...new Set(
      text.split(/[\s,;\n\r\t]+/).map(s => s.trim().toUpperCase()).filter(Boolean)
    )];

  const handleFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const syms = parseSymbols(String(reader.result));
      setInput(syms.join(', '));
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const handleRun = () => {
    const syms = parseSymbols(input);
    if (syms.length < 2) {
      setError('Enter at least 2 symbols to rank them against each other.');
      return;
    }
    if (running) return;

    setError(null);
    setResults(null);
    setLogLines([]);
    setProgress({ done: 0, total: syms.length });
    setRunning(true);

    const es = new EventSource(`${STREAM_URL}?symbols=${encodeURIComponent(syms.join(','))}`);
    esRef.current = es;

    es.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'log') {
          setLogLines(prev => [...prev.slice(-80), msg.text]);
          const m = msg.text.match(/\((\d+)\/(\d+)\)/);
          if (m) setProgress({ done: parseInt(m[1], 10), total: parseInt(m[2], 10) });
        } else if (msg.type === 'result') {
          setResults(msg.data);
          setTechAvail(msg.technicals_available);
        } else if (msg.type === 'done') {
          setRunning(false);
          es.close(); esRef.current = null;
        } else if (msg.type === 'error') {
          setError(msg.text || 'Screen failed.');
          setRunning(false);
          es.close(); esRef.current = null;
        }
      } catch (_) {}
    };

    es.onerror = () => {
      if (esRef.current) {
        setError('Connection lost - is the backend running?');
        setRunning(false);
        es.close(); esRef.current = null;
      }
    };
  };

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 8px' }}>

      {/* header */}
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ margin: '0 0 6px', fontSize: 22, color: '#0f172a' }}>
          Swing Screener
        </h2>
        <p style={{ margin: 0, fontSize: 13, color: '#64748b' }}>
          Paste a list of NSE symbols. Every stock gets Piotroski, Altman Z, Beneish M,
          earnings yield, multi-horizon momentum, RSI, ATR volatility and trend - then all
          are ranked against each other with winsorized z-score composites weighted for swing trading
          (Momentum 35% · Quality 30% · Value 20% · Low-Risk 15%).
        </p>
      </div>

      {/* input panel */}
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 14, padding: 16, marginBottom: 20,
      }}>
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder={`Symbols separated by comma, space or newline, e.g.\n${EXAMPLE}`}
          rows={3}
          style={{
            width: '100%', boxSizing: 'border-box', resize: 'vertical',
            background: 'var(--bg-inset)', color: '#0f172a',
            border: '1px solid var(--border-strong)', borderRadius: 8,
            padding: '10px 12px', fontSize: 13,
            fontFamily: 'var(--font-mono)',
          }}
        />
        <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            onClick={handleRun}
            disabled={running}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '8px 20px', borderRadius: 8, fontSize: 13, fontWeight: 600,
              cursor: running ? 'not-allowed' : 'pointer',
              background: running ? 'var(--bg-hover)' : 'linear-gradient(135deg, #2f6feb, #5b4ee9)',
              border: running ? '1px solid var(--border-strong)' : '1px solid transparent',
              boxShadow: running ? 'none' : '0 2px 12px rgba(47,111,235,0.4)',
              color: running ? '#64748b' : '#fff',
            }}
          >
            {running
              ? <><Spinner /> Screening {progress.done}/{progress.total}...</>
              : 'Run Screen'}
          </button>

          <button
            onClick={() => fileRef.current?.click()}
            disabled={running}
            style={{
              padding: '8px 14px', borderRadius: 8, fontSize: 13,
              cursor: running ? 'not-allowed' : 'pointer',
              background: 'var(--bg-hover)', border: '1px solid var(--border-strong)', color: '#64748b',
            }}
          >
            Upload .txt / .csv
          </button>
          <input ref={fileRef} type="file" accept=".txt,.csv" onChange={handleFile} style={{ display: 'none' }} />

          <button
            onClick={() => setInput(EXAMPLE)}
            disabled={running}
            style={{
              padding: '8px 14px', borderRadius: 8, fontSize: 13,
              cursor: 'pointer', background: 'none',
              border: '1px dashed var(--border-strong)', color: '#94a3b8',
            }}
          >
            Try example
          </button>

          <span style={{ fontSize: 12, color: '#94a3b8', marginLeft: 'auto' }}>
            {parseSymbols(input).length} symbols · max 60
          </span>
        </div>

        {/* progress bar + last log line while running */}
        {running && (
          <div style={{ marginTop: 12 }}>
            <div style={{ height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{
                height: 6, borderRadius: 3, background: 'linear-gradient(90deg, #2f6feb, #a78bfa)',
                width: `${progress.total ? progress.done / progress.total * 100 : 0}%`,
                transition: 'width 0.3s',
              }} />
            </div>
            <div style={{
              marginTop: 8, fontSize: 12, color: '#64748b',
              fontFamily: 'var(--font-mono)',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {logLines[logLines.length - 1] || 'Starting...'}
            </div>
          </div>
        )}

        {error && (
          <div style={{ marginTop: 10, fontSize: 13, color: '#ef4444' }}>
            {error}
          </div>
        )}
      </div>

      {/* results */}
      {results && (
        <div style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 14, overflow: 'hidden',
        }}>
          <div style={{
            padding: '12px 16px', borderBottom: '1px solid var(--border)',
            display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
          }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>
              {results.length} stocks ranked
            </span>
            {!techAvail && (
              <span style={{ fontSize: 12, color: '#f59e0b' }}>
                Kite not connected - ranked on fundamentals only (no momentum/technicals)
              </span>
            )}
            <span style={{ fontSize: 12, color: '#94a3b8', marginLeft: 'auto' }}>
              Click a row for details · click a symbol to open full research
            </span>
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 900 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-strong)' }}>
                  {[
                    { h: '#' },
                    { h: 'Symbol' },
                    { h: 'Score', tip: 'Composite rank score (0-100) vs the other stocks in your list: Momentum 35% + Quality 30% + Value 20% + Low-Risk 15%. 70+ = top of your list.' },
                    { h: 'Verdict', tip: 'Overall call. Strong Candidate needs score 70+, an uptrend and Piotroski 6+. Manipulation or distress flags force Avoid regardless of score.' },
                    { h: 'Momentum', tip: 'Price-strength z-score vs your list: 3M/6M returns, 12-1 momentum, 52-week-high proximity, risk-adjusted return. Positive = stronger than the group.' },
                    { h: 'Quality', tip: 'Fundamental-strength z-score vs your list: Piotroski, Altman Z, ROE, ROCE. Positive = higher quality than the group.' },
                    { h: 'Value', tip: 'Cheapness z-score vs your list: earnings yield, inverse P/E, inverse P/B, dividend yield. Positive = cheaper than the group.' },
                    { h: '3M Ret', tip: 'Total price return over the last 3 months (63 trading days).' },
                    { h: 'Trend', tip: 'Price vs 50 & 200-day moving averages. Strong Up = price > 50 DMA > 200 DMA. Swing trades work best with the trend.' },
                    { h: 'Pio', tip: 'Piotroski F-Score (0-9): nine checks of improving fundamentals. 8-9 excellent, 6-7 good, below 4 weak.' },
                    { h: 'Flags', tip: 'Hard warnings: Beneish manipulation risk, Altman distress zone, weak Piotroski, overbought RSI, or trading below the 200 DMA.' },
                  ].map(({ h, tip }) => (
                    <th key={h} title={tip} style={{
                      padding: '10px 8px', textAlign: 'left', fontSize: 11,
                      fontWeight: 600, color: '#64748b',
                      textTransform: 'uppercase', letterSpacing: 0.5,
                      cursor: tip ? 'help' : 'default',
                      textDecoration: tip ? 'underline dotted rgba(100,116,139,0.5)' : 'none',
                      textUnderlineOffset: 3,
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.map(r => (
                  <ResultRow key={r.symbol} r={r} onSelectStock={onSelectStock} techAvailable={techAvail} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* empty state */}
      {!results && !running && (
        <div style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 14, padding: '40px 24px', textAlign: 'center',
        }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>📊</div>
          <h3 style={{ color: '#0f172a', margin: '0 0 8px' }}>No screen run yet</h3>
          <p style={{ color: '#64748b', margin: 0, fontSize: 13 }}>
            Paste your stock list above and hit <strong style={{ color: '#0f172a' }}>Run Screen</strong>.
            Takes ~2-4 seconds per stock.
          </p>
        </div>
      )}
    </div>
  );
}
