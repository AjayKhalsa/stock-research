import React from 'react';

/**
 * Multi-factor Z-score report card: the four winsorized factor composites
 * behind the screener's rank, with their model weights. Explains WHY the
 * composite verdict differs from the eye test (e.g. chart screams buy but
 * Value is deeply negative). Only renders when the stock was opened from a
 * screener run — z-scores are cross-sectional (relative to that list).
 */

const FACTORS = [
  { key: 'z_momentum', label: 'Momentum', weight: '35%',
    desc: '3M/6M returns, 12-1 momentum, 52w-high proximity, risk-adjusted return' },
  { key: 'z_quality',  label: 'Quality',  weight: '30%',
    desc: 'Piotroski F-Score, Altman Z-Score, Beneish M-Score, ROE, ROCE' },
  { key: 'z_value',    label: 'Value',    weight: '20%',
    desc: 'Earnings yield, inverse P/E, inverse P/B, dividend yield' },
  { key: 'z_low_risk', label: 'Low-Risk', weight: '15%',
    desc: 'ATR volatility, annualized volatility, leverage vs the group' },
];

function zColor(z) {
  if (z == null) return '#94a3b8';
  if (z >= 1)    return '#10b981';
  if (z >= 0.3)  return '#34d399';
  if (z >= -0.3) return '#f59e0b';
  return '#ef4444';
}

function FactorBar({ z }) {
  const clamped = z == null ? 0 : Math.max(-2.5, Math.min(2.5, z));
  const pctW = Math.abs(clamped) / 2.5 * 50;
  const pos = clamped >= 0;
  return (
    <div style={{ position: 'relative', flex: 1, height: 12, background: 'var(--bg-inset)', borderRadius: 6, border: '1px solid var(--border)' }}>
      {z != null && (
        <div style={{
          position: 'absolute', top: 1, bottom: 1, borderRadius: 5,
          left: pos ? '50%' : `${50 - pctW}%`, width: `${pctW}%`,
          background: zColor(z), transition: 'width 0.4s ease',
        }} />
      )}
      <div style={{ position: 'absolute', left: '50%', top: -2, width: 1, height: 16, background: '#94a3b8' }} />
    </div>
  );
}

export default function FactorReportCard({ row }) {
  if (!row) return null;
  const hasAny = FACTORS.some(f => row[f.key] != null);
  if (!hasAny) return null;

  return (
    <div className="card" style={{ padding: 20 }}>
      <div className="tp-header" style={{ marginBottom: 4 }}>
        <div className="tp-title">🧮 Factor Report Card</div>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Winsorized z-scores vs your screened list · composite {row.score ?? '—'}/100 (rank #{row.rank ?? '—'})
        </span>
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginBottom: 14 }}>
        Positive = stronger than the group on that factor; 0 = group average. This is the
        arithmetic behind the screener verdict — when it disagrees with the chart, the
        factor bars show exactly which lens is dragging.
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {FACTORS.map(f => {
          const z = row[f.key];
          return (
            <div key={f.key} title={f.desc}
                 style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ width: 100, fontSize: 12.5, fontWeight: 700, color: 'var(--text-primary)' }}>
                {f.label}
                <span style={{ fontWeight: 500, color: 'var(--text-muted)', fontSize: 10.5 }}> · {f.weight}</span>
              </span>
              <FactorBar z={z} />
              <span style={{ width: 48, textAlign: 'right', fontSize: 12, fontWeight: 700,
                             color: zColor(z), fontVariantNumeric: 'tabular-nums' }}>
                {z == null ? '—' : `${z > 0 ? '+' : ''}${z.toFixed(2)}σ`}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
