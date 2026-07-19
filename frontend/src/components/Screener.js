import React, { useRef, useState } from 'react';
import { API_BASE, resolveSymbols } from '../api';

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

function planVerdictStyle(verdict = '') {
  if (verdict === 'Buy')        return { bg: 'rgba(16,185,129,0.12)', color: '#10b981', border: '#10b981' };
  if (verdict === 'Buy on Dip') return { bg: 'rgba(99,102,241,0.10)', color: '#6366f1', border: '#6366f1' };
  if (verdict === 'Wait')       return { bg: 'rgba(245,158,11,0.14)', color: '#f59e0b', border: '#f59e0b' };
  return { bg: 'rgba(239,68,68,0.10)', color: '#ef4444', border: '#ef4444' };
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

/* Tiny centered z-score bar for the compact master rows */
function MiniZ({ z, label }) {
  const clamped = z == null ? 0 : Math.max(-2.5, Math.min(2.5, z));
  const pctW = Math.abs(clamped) / 2.5 * 50;
  const pos = clamped >= 0;
  return (
    <div title={`${label}: ${z == null ? '-' : (z > 0 ? '+' : '') + z.toFixed(2)}`}
         style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <span style={{ fontSize: 9, color: '#94a3b8', width: 10 }}>{label}</span>
      <div style={{ position: 'relative', width: 44, height: 5, background: 'var(--border)', borderRadius: 3 }}>
        {z != null && (
          <div style={{
            position: 'absolute', top: 0, height: 5, borderRadius: 3,
            left: pos ? '50%' : `${50 - pctW}%`, width: `${pctW}%`,
            background: pos ? '#10b981' : '#ef4444',
          }} />
        )}
        <div style={{ position: 'absolute', left: '50%', top: -1, width: 1, height: 7, background: '#cbd5e1' }} />
      </div>
    </div>
  );
}

// ── compact master row ────────────────────────────────────────────────────────

function MasterRow({ r, active, onSelect }) {
  const vs = verdictStyle(r.verdict);
  const ps = planVerdictStyle(r.plan_verdict);
  return (
    <div
      onClick={() => onSelect(r.symbol, r)}
      style={{
        display: 'flex', flexDirection: 'column', gap: 6,
        padding: '9px 12px', cursor: 'pointer',
        borderBottom: '1px solid var(--border)',
        background: active ? 'linear-gradient(135deg, rgba(99,102,241,0.10), rgba(139,92,246,0.06))' : 'transparent',
        borderLeft: active ? '3px solid #6366f1' : '3px solid transparent',
        transition: 'background 0.15s ease',
      }}
      onMouseEnter={e => { if (!active) e.currentTarget.style.background = 'var(--bg-hover)'; }}
      onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent'; }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 11, color: '#94a3b8', width: 18 }}>{r.rank}</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: active ? '#6366f1' : '#0f172a' }}>{r.symbol}</span>
        <span style={{ fontSize: 15, fontWeight: 700, color: scoreColor(r.score), marginLeft: 'auto' }}>
          {r.score != null ? r.score : '-'}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <span style={{
          padding: '2px 7px', borderRadius: 5, fontSize: 10, fontWeight: 700,
          background: vs.bg, color: vs.color, border: `1px solid ${vs.border}`, whiteSpace: 'nowrap',
        }}>{r.verdict}</span>
        {r.plan_verdict && (
          <span title={r.plan_setup_label || ''} style={{
            padding: '2px 7px', borderRadius: 5, fontSize: 10, fontWeight: 700,
            background: ps.bg, color: ps.color, border: `1px solid ${ps.border}`, whiteSpace: 'nowrap',
          }}>Plan: {r.plan_verdict}</span>
        )}
        {r.flags?.length > 0 && (
          <span title={r.flags.join('\n')} style={{ fontSize: 10, color: '#ea580c', marginLeft: 'auto' }}>
            ⚑ {r.flags.length}
          </span>
        )}
      </div>
      <div style={{ display: 'flex', gap: 10 }}>
        <MiniZ z={r.z_momentum} label="M" />
        <MiniZ z={r.z_quality} label="Q" />
        <MiniZ z={r.z_value} label="V" />
      </div>
    </div>
  );
}

// ── main master-panel component ───────────────────────────────────────────────

const EXAMPLE = 'RELIANCE, TCS, INFY, HDFCBANK, ITC, LT, SUNPHARMA';

export default function Screener({ onSelectStock, activeSymbol }) {
  const [input,      setInput]      = useState('');
  const [running,    setRunning]    = useState(false);
  const [logLines,   setLogLines]   = useState([]);
  const [progress,   setProgress]   = useState({ done: 0, total: 0 });
  const [results,    setResults]    = useState(null);
  const [error,      setError]      = useState(null);
  const [resolving,  setResolving]  = useState(false);
  const [resolution, setResolution] = useState(null);
  const [showInput,  setShowInput]  = useState(true);

  const esRef = useRef(null);
  const fileRef = useRef(null);

  // Newlines/commas/semicolons separate entries; ALL-CAPS multi-word segments
  // are space-separated symbols (old behavior); lowercase = company name.
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
        setError(`Could not resolve: ${unresolved.map(r => `"${r.query}"`).join(', ')} — screening the rest.`);
      }
    } catch {
      syms = tokens.filter(t => !t.includes(' ')).map(t => t.toUpperCase());
    } finally {
      setResolving(false);
    }

    if (syms.length < 2) {
      setError('Fewer than 2 entries resolved to NSE symbols — nothing to rank.');
      return;
    }

    setResults(null);
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
          setShowInput(false);   // collapse input to give the list room
        } else if (msg.type === 'done') {
          setRunning(false);
          es.close(); esRef.current = null;
        } else if (msg.type === 'error') {
          setError(msg.text || 'Screen failed.');
          setRunning(false);
          es.close(); esRef.current = null;
        }
      } catch (err) {
        console.error('[screener] bad SSE payload', err);
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

  const busy = running || resolving;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>

      {/* panel header */}
      <div style={{
        padding: '14px 14px 10px', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
      }}>
        <span style={{ fontSize: 13, fontWeight: 800, color: '#0f172a' }}>📊 Master Screener</span>
        {results && (
          <span style={{ fontSize: 11, color: '#94a3b8' }}>{results.length} ranked</span>
        )}
        <button
          onClick={() => setShowInput(s => !s)}
          style={{
            marginLeft: 'auto', background: 'none', border: '1px solid var(--border-strong)',
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
              {resolving ? <><Spinner /> Resolving…</>
                : running ? <><Spinner /> {progress.done}/{progress.total}…</>
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
                      ? <>{r.query.slice(0, 22)} → <strong style={{ color: '#0f172a' }}>{r.symbol}</strong></>
                      : <>{r.query.slice(0, 26)} ✗</>}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ranked list — its own scroll container so selection never resets scroll */}
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {results?.map(r => (
          <MasterRow key={r.symbol} r={r} active={r.symbol === activeSymbol} onSelect={onSelectStock} />
        ))}
        {!results && !running && (
          <div style={{ padding: '36px 18px', textAlign: 'center', color: '#94a3b8', fontSize: 12, lineHeight: 1.7 }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>📊</div>
            Run a screen to rank stocks here.<br />
            Click any result to open its full analysis →
          </div>
        )}
      </div>
    </div>
  );
}
