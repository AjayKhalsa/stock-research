import React from 'react';
import toast from 'react-hot-toast';

/**
 * Unified Trade Setup card: absolute execution levels with auto-calculated
 * GTT percentage offsets relative to the current close, plus the meta stats
 * that justify the trade (setup strength, R:R, historical base rates).
 * Click the price to copy it; click the % chip to copy the GTT offset.
 */

function fmtINR(v) {
  if (v == null) return '—';
  return `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

function convictionColor(s) {
  if (s == null) return '#94a3b8';
  if (s >= 70) return '#10b981';
  if (s >= 50) return '#6366f1';
  if (s >= 30) return '#f59e0b';
  return '#ef4444';
}

function verdictColors(verdict = '') {
  if (verdict === 'Buy')        return { bg: 'rgba(16,185,129,0.10)', color: '#10b981', border: 'rgba(16,185,129,0.4)' };
  if (verdict === 'Buy on Dip') return { bg: 'rgba(99,102,241,0.10)', color: '#6366f1', border: 'rgba(99,102,241,0.4)' };
  if (verdict === 'Wait')       return { bg: 'rgba(245,158,11,0.12)', color: '#f59e0b', border: 'rgba(245,158,11,0.4)' };
  return { bg: 'rgba(239,68,68,0.08)', color: '#ef4444', border: 'rgba(239,68,68,0.4)' };
}

async function copyValue(value, label) {
  try {
    await navigator.clipboard.writeText(String(value));
    toast.success(`${label} copied: ${value}`, { duration: 1600 });
  } catch {
    toast.error('Clipboard unavailable');
  }
}

function LevelTile({ label, color, children, basis }) {
  return (
    <div className="tp-level">
      <div className="tp-level-label" style={{ color }}>{label}</div>
      {children}
      {basis && <div className="tp-level-basis">{basis}</div>}
    </div>
  );
}

/* Absolute price (click-to-copy) + GTT offset % chip (click-to-copy) */
function PriceWithOffset({ price, refPrice, label }) {
  const offset = refPrice > 0 && price != null
    ? ((price - refPrice) / refPrice * 100) : null;
  const offsetStr = offset != null ? `${offset >= 0 ? '+' : ''}${offset.toFixed(2)}` : null;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <span
        className="tp-level-price"
        style={{ cursor: 'pointer' }}
        title={`Click to copy ${label} price`}
        onClick={() => price != null && copyValue(price, `${label} price`)}
      >
        {fmtINR(price)} <span style={{ fontSize: 11, opacity: 0.6 }}>📋</span>
      </span>
      {offsetStr != null && (
        <span
          onClick={() => copyValue(offsetStr, `${label} GTT offset %`)}
          title={`GTT offset vs current close — click to copy ${offsetStr}%`}
          style={{
            fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 999,
            cursor: 'pointer', border: '1px solid',
            color: offset >= 0 ? '#10b981' : '#ef4444',
            borderColor: offset >= 0 ? 'rgba(16,185,129,0.4)' : 'rgba(239,68,68,0.4)',
            background: offset >= 0 ? 'rgba(16,185,129,0.07)' : 'rgba(239,68,68,0.06)',
          }}
        >
          GTT {offsetStr}%
        </span>
      )}
    </div>
  );
}

export default function TradeSetup({ plan, dossier, livePrice, loading }) {
  if (loading && !plan) {
    return (
      <div className="card" style={{ padding: 20 }}>
        <div className="skeleton" style={{ height: 22, width: '30%', marginBottom: 14 }} />
        <div style={{ display: 'flex', gap: 12 }}>
          {[1, 2, 3, 4].map(i => <div key={i} className="skeleton" style={{ height: 84, flex: 1 }} />)}
        </div>
      </div>
    );
  }
  if (!plan?.entry) return null;

  const entry = plan.entry;
  const stop = plan.stop || {};
  const targets = plan.targets || [];
  const entryMid = (entry.low + entry.high) / 2;
  const refPrice = livePrice ?? entryMid;

  const vc = verdictColors(plan.verdict);
  const strength = dossier?.case?.conviction;
  const br = dossier?.base_rates;

  return (
    <div className="card trade-setup" style={{ padding: 20 }}>
      <div className="tp-header" style={{ marginBottom: 12 }}>
        <div className="tp-title">🎯 Trade Setup</div>
        <span style={{
          fontSize: 12.5, fontWeight: 800, padding: '4px 14px', borderRadius: 999,
          background: vc.bg, color: vc.color, border: `1px solid ${vc.border}`,
        }}>{plan.verdict}</span>
      </div>

      <div className="tp-levels" style={{ marginBottom: 12 }}>
        <LevelTile label="Entry Zone" color="#6366f1" basis={entry.rationale}>
          <div className="tp-level-price">{fmtINR(entry.low)} – {fmtINR(entry.high)}</div>
        </LevelTile>

        <LevelTile label="Stop Loss" color="#ef4444"
                   basis={stop.rationale}>
          <PriceWithOffset price={stop.price} refPrice={refPrice} label="Stop" />
        </LevelTile>

        {targets.map(t => (
          <LevelTile key={t.label} label={`Target ${t.label}`} color="#10b981" basis={t.basis}>
            <PriceWithOffset price={t.price} refPrice={refPrice} label={t.label} />
          </LevelTile>
        ))}
      </div>

      {/* meta stats: the numbers that justify the trade */}
      <div style={{
        display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'center',
        padding: '10px 14px', borderRadius: 10,
        background: 'var(--bg-inset)', border: '1px solid var(--border)',
        fontSize: 12.5, color: 'var(--text-secondary)',
      }}>
        <span>
          Technical Trend Setup Strength{' '}
          <strong style={{ color: convictionColor(strength), fontSize: 14 }}>
            {strength != null ? `${strength}/100` : '—'}
          </strong>
        </span>
        {plan.risk_reward != null && (
          <span>Risk : Reward <strong style={{ color: 'var(--text-primary)' }}>1 : {plan.risk_reward}</strong></span>
        )}
        {br?.n >= 5 && (
          <span title={br.note}>
            📜 <strong style={{ color: 'var(--text-primary)' }}>{br.n}</strong> historical setups detected ·{' '}
            <strong style={{ color: 'var(--text-primary)' }}>{br.win_rate}%</strong> pattern hit rate ·{' '}
            <strong style={{ color: br.expected_r > 0 ? '#10b981' : '#ef4444' }}>
              {br.expected_r > 0 ? '+' : ''}{br.expected_r}R
            </strong> expected value per trade
          </span>
        )}
      </div>

      {plan.invalidation && (
        <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 10 }}>
          ⚠️ {plan.invalidation}
        </div>
      )}
      <div style={{ fontSize: 11, fontStyle: 'italic', color: 'var(--text-muted)', marginTop: 6 }}>
        *GTT offsets are computed against the delayed close (₹{refPrice?.toLocaleString('en-IN')}) —
        verify live LTP on Kite before placing orders.
      </div>
    </div>
  );
}
