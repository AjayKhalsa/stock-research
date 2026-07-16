import React from 'react';
import './AlphaThesis.css';

/* ── conviction colour helpers ─────────────────────────────────────────────── */
function convictionColor(score) {
  if (score >= 80) return '#10b981';
  if (score >= 65) return '#34d399';
  if (score >= 50) return '#d97706';
  if (score >= 35) return '#ea580c';
  return '#ef4444';
}

function actionClass(action = '') {
  const a = action.toLowerCase();
  if (a.includes('strong buy') || a.includes('accumulate')) return 'action-buy-strong';
  if (a.includes('buy'))    return 'action-buy';
  if (a.includes('hold'))   return 'action-hold';
  if (a.includes('reduce')) return 'action-reduce';
  return 'action-sell';
}

function confidenceClass(conf = '') {
  if (conf === 'high')   return 'conf-high';
  if (conf === 'medium') return 'conf-med';
  return 'conf-low';
}

/* ── SVG doughnut gauge ────────────────────────────────────────────────────── */
function ConvictionGauge({ score, label }) {
  const color = convictionColor(score);
  const r = 38, cx = 46, cy = 46;
  const circ = 2 * Math.PI * r;
  const dash = Math.max(0, Math.min(1, score / 100)) * circ;

  return (
    <div className="conviction-gauge">
      <svg width={92} height={92}>
        <circle cx={cx} cy={cy} r={r} fill="none"
          stroke="var(--border)" strokeWidth={7} />
        <circle cx={cx} cy={cy} r={r} fill="none"
          stroke={color} strokeWidth={7}
          strokeDasharray={`${dash} ${circ}`}
          strokeLinecap="round"
          transform={`rotate(-90 ${cx} ${cy})`} />
      </svg>
      <div className="gauge-center">
        <div className="gauge-score" style={{ color }}>{score}</div>
        <div className="gauge-label"  style={{ color }}>{label}</div>
      </div>
    </div>
  );
}

/* ── bullet-list helper ────────────────────────────────────────────────────── */
function BulletList({ items, icon, className }) {
  if (!items || items.length === 0) return <p className="alpha-empty">—</p>;
  return (
    <ul className={`alpha-list ${className || ''}`}>
      {items.map((item, i) => (
        <li key={i}>
          {icon && <span className="list-icon">{icon}</span>}
          {item}
        </li>
      ))}
    </ul>
  );
}

/* ── loading skeleton ──────────────────────────────────────────────────────── */
function AlphaSkeleton() {
  return (
    <div className="card alpha-card alpha-skeleton">
      <div className="card-header">
        <span className="card-title">🤖 AI Alpha Thesis</span>
        <span className="alpha-loading-badge">
          <span className="alpha-spinner" /> Analysing with Gemini…
        </span>
      </div>
      <div className="card-body">
        <div className="sk-row">
          <div className="skeleton" style={{ width: 92, height: 92, borderRadius: '50%' }} />
          <div style={{ flex: 1 }}>
            <div className="skeleton" style={{ height: 16, marginBottom: 10, width: '80%' }} />
            <div className="skeleton" style={{ height: 14, marginBottom: 8 }} />
            <div className="skeleton" style={{ height: 14, width: '60%' }} />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── main component ────────────────────────────────────────────────────────── */
export default function AlphaThesis({ data, loading }) {
  if (loading) return <AlphaSkeleton />;
  if (!data)   return null;

  const {
    conviction_score, conviction_label, thesis_summary,
    bull_case, bear_case, red_flags, key_catalysts,
    valuation_view, risk_reward, suggested_action,
    data_confidence, error,
  } = data;

  const hasError = error && error !== null;

  return (
    <div className="card alpha-card">
      <div className="card-header">
        <span className="card-title">🤖 AI Alpha Thesis</span>
        <div className="alpha-meta">
          {data_confidence && (
            <span className={`conf-badge ${confidenceClass(data_confidence)}`}>
              {data_confidence} confidence
            </span>
          )}
          <span className="gemini-badge">Gemini 2.5 Flash</span>
        </div>
      </div>

      {hasError ? (
        <div className="card-body" style={{ textAlign: 'center', padding: '36px 24px' }}>
          <div style={{ fontSize: 30, marginBottom: 10 }}>🤖💤</div>
          <div style={{ fontSize: 14.5, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 6 }}>
            AI Analysis temporarily unavailable
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--text-muted)', lineHeight: 1.6, maxWidth: 380, margin: '0 auto' }}>
            {String(error).includes('429') || String(error).toLowerCase().includes('rate')
              ? 'The Gemini API is rate-limited right now. Please try again in a moment — the quantitative analysis above is unaffected.'
              : 'Please try again in a moment. The quantitative analysis above is unaffected.'}
          </div>
        </div>
      ) : (
        <div className="alpha-body">

          {/* ── top row: gauge + summary ── */}
          <div className="alpha-top">
            {conviction_score != null && (
              <ConvictionGauge score={conviction_score} label={conviction_label} />
            )}
            <div className="alpha-summary-block">
              {thesis_summary && (
                <p className="alpha-thesis-text">{thesis_summary}</p>
              )}
              {suggested_action && (
                <div className={`action-chip ${actionClass(suggested_action)}`}>
                  {suggested_action}
                </div>
              )}
            </div>
          </div>

          {/* ── bull / bear columns ── */}
          <div className="alpha-columns">
            <div className="alpha-col bull-col">
              <div className="col-label bull-label">📈 Bull Case</div>
              <p className="col-text">{bull_case || '—'}</p>
            </div>
            <div className="alpha-col-divider" />
            <div className="alpha-col bear-col">
              <div className="col-label bear-label">📉 Bear Case</div>
              <p className="col-text">{bear_case || '—'}</p>
            </div>
          </div>

          {/* ── red flags + catalysts ── */}
          <div className="alpha-flags-row">
            <div className="alpha-flags-col">
              <div className="col-label flag-label">🚩 Red Flags</div>
              <BulletList items={red_flags} className="flag-list" />
            </div>
            <div className="alpha-flags-col">
              <div className="col-label catalyst-label">⚡ Key Catalysts</div>
              <BulletList items={key_catalysts} className="catalyst-list" />
            </div>
          </div>

          {/* ── valuation + risk/reward ── */}
          <div className="alpha-footer-row">
            {valuation_view && (
              <div className="alpha-footer-item">
                <span className="footer-label">Valuation:</span>
                <span className="footer-text">{valuation_view}</span>
              </div>
            )}
            {risk_reward && (
              <div className="alpha-footer-item">
                <span className="footer-label">Risk / Reward:</span>
                <span className="footer-text">{risk_reward}</span>
              </div>
            )}
          </div>

        </div>
      )}
    </div>
  );
}
