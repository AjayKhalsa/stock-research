import React from 'react';
import './TradePlan.css';

const PATTERN_STYLES = {
  aligned_bull:      { bg: 'rgba(16,185,129,0.10)', color: '#10b981', border: 'rgba(16,185,129,0.4)' },
  momentum_trade:    { bg: 'rgba(99,102,241,0.10)', color: '#6366f1', border: 'rgba(99,102,241,0.4)' },
  quality_watch:     { bg: 'rgba(245,158,11,0.12)', color: '#f59e0b', border: 'rgba(245,158,11,0.4)' },
  no_edge:           { bg: 'rgba(239,68,68,0.08)',  color: '#ef4444', border: 'rgba(239,68,68,0.4)' },
  hard_disqualified: { bg: 'rgba(239,68,68,0.10)',  color: '#ef4444', border: 'rgba(239,68,68,0.5)' },
  mixed:             { bg: 'var(--bg-inset)',       color: 'var(--text-secondary)', border: 'var(--border-strong)' },
};

function scoreColor(s) {
  if (s == null) return '#94a3b8';
  if (s >= 70) return '#10b981';
  if (s >= 50) return '#6366f1';
  if (s >= 30) return '#f59e0b';
  return '#ef4444';
}

const HORIZON_LABELS = { swing: 'Swing (days–weeks)', positional: 'Positional (weeks–months)', long_term: 'Long-term (investment)' };

export default function BottomLine({ synthesis, loading, alphaLoading }) {
  if (loading && !synthesis) {
    return (
      <div className="card" style={{ padding: 20 }}>
        <div className="skeleton" style={{ height: 22, width: '30%', marginBottom: 14 }} />
        <div style={{ display: 'flex', gap: 12 }}>
          {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 90, flex: 1 }} />)}
        </div>
      </div>
    );
  }
  if (!synthesis) return null;

  const ps = PATTERN_STYLES[synthesis.pattern] || PATTERN_STYLES.mixed;

  return (
    <div className="card bottom-line" style={{ padding: 20 }}>
      <div className="bl-header">
        <span className="tp-title">🧭 Bottom Line</span>
        <span className="bl-pattern" style={{ background: ps.bg, color: ps.color, borderColor: ps.border }}>
          {synthesis.pattern_label}
        </span>
      </div>

      {/* three lenses */}
      <div className="bl-lenses">
        {synthesis.lenses.map(l => (
          <div key={l.key} className="bl-lens" title={l.detail || ''}>
            <div className="bl-lens-label">{l.label}</div>
            <div className="bl-lens-score" style={{ color: scoreColor(l.score) }}>
              {l.score != null ? l.score
                : l.key === 'ai' && (alphaLoading || l.verdict === 'pending') ? '…' : '—'}
            </div>
            <div className="bl-lens-verdict" style={{ color: scoreColor(l.score) }}>
              {l.key === 'ai' && l.verdict === 'pending' && alphaLoading ? 'analyzing…' : l.verdict}
            </div>
            <div className="bl-lens-question">{l.question}</div>
            {l.detail && <div className="bl-lens-detail">{l.detail}</div>}
          </div>
        ))}
      </div>

      {/* per-horizon directives */}
      <div className="bl-directives">
        {Object.entries(synthesis.directives).map(([k, text]) => (
          <div key={k} className="bl-directive">
            <span className="bl-directive-label">{HORIZON_LABELS[k] || k}</span>
            <span className="bl-directive-text">{text}</span>
          </div>
        ))}
      </div>

      {/* reconciliation */}
      <div className="bl-reconciliation">{synthesis.reconciliation}</div>

      {/* AI dissent */}
      {synthesis.dissent && (
        <div className="tp-ai-note" style={{ marginTop: 10, marginBottom: 0 }}>
          <strong style={{ fontStyle: 'normal' }}>⚠ Dissenting view: </strong>
          {synthesis.dissent.reason}
        </div>
      )}
    </div>
  );
}
