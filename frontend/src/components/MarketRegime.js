import React, { useState, useEffect } from 'react';
import { getMarketRegime } from '../api';

const STYLES = {
  risk_on:  { bg: 'rgba(16,185,129,0.08)',  border: 'rgba(16,185,129,0.35)',  color: '#10b981', icon: '🟢' },
  neutral:  { bg: 'rgba(245,158,11,0.08)',  border: 'rgba(245,158,11,0.35)',  color: '#f59e0b', icon: '🟡' },
  risk_off: { bg: 'rgba(239,68,68,0.07)',   border: 'rgba(239,68,68,0.35)',   color: '#ef4444', icon: '🔴' },
};

export default function MarketRegime() {
  const [regime, setRegime] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    getMarketRegime().then(r => { if (alive) setRegime(r); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  if (!regime || regime.regime === 'Unknown') return null;
  const s = STYLES[regime.regime] || STYLES.neutral;

  return (
    <div
      onClick={() => setOpen(o => !o)}
      style={{
        display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        padding: '8px 14px', borderRadius: 10, marginBottom: 14, cursor: 'pointer',
        background: s.bg, border: `1px solid ${s.border}`, fontSize: 12.5,
      }}
      title="Market regime: the first filter institutions apply — most long setups fail when the index is in a downtrend"
    >
      <span>{s.icon}</span>
      <strong style={{ color: s.color }}>Market: {regime.label}</strong>
      <span style={{ color: 'var(--text-secondary)' }}>
        NIFTY {regime.nifty?.toLocaleString('en-IN')}
        {regime.drawdown_pct != null && ` · ${regime.drawdown_pct}% off 52w high`}
        {regime.vol_percentile != null && ` · vol ${regime.vol_percentile}th pctile`}
        {regime.distribution_days != null && ` · ${regime.distribution_days} distribution day${regime.distribution_days === 1 ? '' : 's'}/25`}
      </span>
      <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: 11 }}>
        {open ? '▾' : 'why does this matter? ▸'}
      </span>
      {open && (
        <div style={{ flexBasis: '100%', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          {regime.guidance}
        </div>
      )}
    </div>
  );
}
