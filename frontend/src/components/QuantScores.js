import React, { useState } from 'react';
import InfoTip from './InfoTip';
import { METRIC_INFO, GLASS_METRICS } from '../metricInfo';
import './QuantScores.css';

/* Dual-layer glass-box header: exact industry term + functional subtitle */
function GlassTitle({ term, glass }) {
  return (
    <span className="qs-section-title" style={{ display: 'inline-flex', flexDirection: 'column', gap: 1 }}>
      <span>
        {term}
        <InfoTip text={glass?.tldr} math={glass?.math} width={300} />
      </span>
      {glass?.subtitle && (
        <span style={{ fontSize: 10.5, fontWeight: 500, color: 'var(--text-muted)',
                       textTransform: 'none', letterSpacing: 0.2 }}>
          {glass.subtitle}
        </span>
      )}
    </span>
  );
}

/* ── Piotroski signal metadata ─────────────────────────────────────────────── */
const SIGNAL_META = {
  F1_positive_roa:         { label: 'ROA > 0',      group: 'Profitability' },
  F2_positive_cfo:         { label: 'CFO > 0',      group: 'Profitability' },
  F3_increasing_roa:       { label: 'ΔROA ↑',       group: 'Profitability' },
  F4_quality_earnings:     { label: 'Cash Quality',  group: 'Profitability' },
  F5_decreasing_leverage:  { label: 'Leverage ↓',   group: 'Leverage' },
  F6_improving_liquidity:  { label: 'Liquidity ↑',  group: 'Leverage' },
  F7_no_dilution:          { label: 'No Dilution',  group: 'Leverage' },
  F8_improving_margin:     { label: 'Margin ↑',     group: 'Efficiency' },
  F9_asset_turnover:       { label: 'Turnover ↑',   group: 'Efficiency' },
};

const SIGNAL_ORDER = [
  'F1_positive_roa', 'F2_positive_cfo', 'F3_increasing_roa', 'F4_quality_earnings',
  'F5_decreasing_leverage', 'F6_improving_liquidity', 'F7_no_dilution',
  'F8_improving_margin', 'F9_asset_turnover',
];

function piotroskiColor(score) {
  if (score >= 8) return '#10b981';
  if (score >= 6) return '#34d399';
  if (score >= 4) return '#d97706';
  if (score >= 2) return '#ea580c';
  return '#ef4444';
}

/* ── Altman Z bar ──────────────────────────────────────────────────────────── */
function AltmanBar({ z, zone }) {
  // Clamp display to 0–12 scale
  const MAX = 12;
  const pct  = Math.min(z / MAX, 1) * 100;
  const distressPct = (1.81 / MAX) * 100;   // ~15.1%
  const greyPct     = (2.99 / MAX) * 100;   // ~24.9%

  const markerColor = zone === 'Safe' ? '#10b981' : zone === 'Grey Zone' ? '#d97706' : '#ef4444';

  return (
    <div className="altman-wrap">
      <div className="altman-bar-track">
        {/* colour zones */}
        <div className="az-zone az-distress" style={{ width: `${distressPct}%` }} />
        <div className="az-zone az-grey"
          style={{ left: `${distressPct}%`, width: `${greyPct - distressPct}%` }} />
        <div className="az-zone az-safe"
          style={{ left: `${greyPct}%`, right: 0 }} />
        {/* threshold lines */}
        <div className="az-threshold" style={{ left: `${distressPct}%` }}>
          <div className="az-thresh-line" />
          <div className="az-thresh-label">1.81</div>
        </div>
        <div className="az-threshold" style={{ left: `${greyPct}%` }}>
          <div className="az-thresh-line" />
          <div className="az-thresh-label">2.99</div>
        </div>
        {/* score marker */}
        <div className="az-marker" style={{ left: `${pct}%` }}>
          <div className="az-marker-pin" style={{ background: markerColor }} />
          <div className="az-marker-label" style={{ color: markerColor }}>{z}</div>
        </div>
      </div>
      <div className="altman-zone-labels">
        <span className="az-zone-text az-text-distress">Distress</span>
        <span className="az-zone-text az-text-grey">Grey Zone</span>
        <span className="az-zone-text az-text-safe" style={{ marginLeft: 'auto' }}>Safe</span>
      </div>
    </div>
  );
}

/* ── DuPont table ──────────────────────────────────────────────────────────── */
function DuPontTable({ trend }) {
  if (!trend || trend.length === 0) return null;
  const rows = [...trend].reverse().slice(0, 4);   // newest first, max 4 rows
  return (
    <table className="dupont-table">
      <thead>
        <tr>
          <th>Year</th>
          <th>NPM %</th>
          <th>Asset T/O</th>
          <th>Eq. Mult.</th>
          <th>ROE %</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td>{r.year || '—'}</td>
            <td>{r.npm_pct != null ? `${r.npm_pct}%` : '—'}</td>
            <td>{r.asset_turnover != null ? r.asset_turnover : '—'}</td>
            <td>{r.equity_multiplier != null ? r.equity_multiplier : '—'}</td>
            <td className={r.roe_computed_pct > 15 ? 'positive' : r.roe_computed_pct < 5 ? 'negative' : ''}>
              {r.roe_computed_pct != null ? `${r.roe_computed_pct}%` : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ── loading skeleton ──────────────────────────────────────────────────────── */
function QuantSkeleton() {
  return (
    <div className="card quant-card">
      <div className="card-header">
        <span className="card-title">📊 Quantitative Scores</span>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Computing…</span>
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {[180, 130, 110].map((h, i) => (
          <div key={i} className="skeleton" style={{ height: h, borderRadius: 6 }} />
        ))}
      </div>
    </div>
  );
}

/* ── main component ────────────────────────────────────────────────────────── */
export default function QuantScores({ data, loading }) {
  const [expandedSignal, setExpandedSignal] = useState(null);
  if (loading) return <QuantSkeleton />;
  if (!data)   return null;

  const { piotroski: pio, altman: alt, dupont: dup, composite_quality_score: cqs } = data;

  const pioScore  = pio?.score ?? 0;
  const pioColor  = piotroskiColor(pioScore);

  return (
    <div className="card quant-card">
      <div className="card-header">
        <span className="card-title">📊 Quantitative Scores</span>
        {cqs != null && (
          <span className="composite-badge" style={{ color: pioColor }}>
            Quality Score: {cqs}/100
            <InfoTip text={METRIC_INFO.quality_score} width={260} />
          </span>
        )}
      </div>

      {/* ── Piotroski ── */}
      <div className="quant-section">
        <div className="qs-section-header">
          <div>
            <GlassTitle term="Piotroski F-Score" glass={GLASS_METRICS.piotroski} />
            <span className="qs-score" style={{ color: pioColor }}>
              {pio?.score ?? '—'}/9
            </span>
          </div>
          <span className="qs-interp">{pio?.interpretation}</span>
        </div>

        <div className="pio-grid">
          {SIGNAL_ORDER.map((key) => {
            const sig  = pio?.signals?.[key];
            const meta = SIGNAL_META[key];
            const pass = sig?.score === 1;
            return (
              <div
                key={key}
                className={`pio-cell ${pass ? 'pio-pass' : 'pio-fail'}`}
                onClick={() => setExpandedSignal(s => (s === key ? null : key))}
                style={{ cursor: 'pointer' }}
                title="Click for the data behind this signal"
              >
                <span className="pio-icon">{pass ? '✓' : '✗'}</span>
                <span className="pio-label">{meta?.label}</span>
                {sig?.value != null && (
                  <span className="pio-val">
                    {typeof sig.value === 'number' ? sig.value.toLocaleString('en-IN', { maximumFractionDigits: 1 }) : sig.value}
                    {sig.unit ? ` ${sig.unit.split(' ')[0]}` : ''}
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* click-to-expand: the exact data behind the selected signal */}
        {expandedSignal && pio?.signals?.[expandedSignal] && (
          <div style={{
            marginTop: 10, padding: '10px 14px', borderRadius: 8,
            background: 'var(--bg-inset)', border: '1px solid var(--border)',
            fontSize: 12, lineHeight: 1.6, color: 'var(--text-secondary)',
          }}>
            <strong style={{ color: pio.signals[expandedSignal].score === 1 ? '#10b981' : '#ef4444' }}>
              {SIGNAL_META[expandedSignal]?.label} — {pio.signals[expandedSignal].score === 1 ? 'PASS' : 'FAIL'}
            </strong>
            <span style={{ color: 'var(--text-muted)' }}> ({SIGNAL_META[expandedSignal]?.group})</span>
            <div>{pio.signals[expandedSignal].description}</div>
            {pio.signals[expandedSignal].value != null && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, marginTop: 3 }}>
                Measured: {String(pio.signals[expandedSignal].value)}
                {pio.signals[expandedSignal].unit ? ` ${pio.signals[expandedSignal].unit}` : ''}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Altman Z ── */}
      {alt && (
        <div className="quant-section">
          <div className="qs-section-header">
            <div>
              <GlassTitle term="Altman Z-Score" glass={GLASS_METRICS.altman} />
              <span className="qs-score" style={{
                color: alt.zone === 'Safe' ? '#10b981' : alt.zone === 'Grey Zone' ? '#d97706' : '#ef4444',
              }}>
                {alt.z_score ?? '—'}
              </span>
              <span className={`altman-zone-chip zone-${(alt.zone || '').toLowerCase().replace(' ', '-')}`}>
                {alt.zone}
              </span>
            </div>
          </div>
          {alt.z_score != null && <AltmanBar z={alt.z_score} zone={alt.zone} />}
          <p className="qs-interp-text">{alt.interpretation}</p>
        </div>
      )}

      {/* ── DuPont ── */}
      {dup && (
        <div className="quant-section quant-section-last">
          <div className="qs-section-header">
            <GlassTitle term="DuPont Decomposition" glass={GLASS_METRICS.dupont} />
          </div>

          {/* Formula display */}
          <div className="dupont-formula">
            <div className="dp-factor">
              <div className="dp-value">
                {dup.net_profit_margin_pct != null ? `${dup.net_profit_margin_pct}%` : '—'}
              </div>
              <div className="dp-factor-label">Net Profit<br/>Margin</div>
            </div>
            <div className="dp-op">×</div>
            <div className="dp-factor">
              <div className="dp-value">
                {dup.asset_turnover != null ? `${dup.asset_turnover}×` : '—'}
              </div>
              <div className="dp-factor-label">Asset<br/>Turnover</div>
            </div>
            <div className="dp-op">×</div>
            <div className="dp-factor">
              <div className="dp-value">
                {dup.equity_multiplier != null ? `${dup.equity_multiplier}×` : '—'}
              </div>
              <div className="dp-factor-label">Equity<br/>Multiplier</div>
            </div>
            <div className="dp-op">=</div>
            <div className="dp-factor dp-roe">
              <div className="dp-value dp-roe-val">
                {dup.roe_dupont_pct != null ? `${dup.roe_dupont_pct}%` : '—'}
              </div>
              <div className="dp-factor-label">ROE<br/>(DuPont)</div>
            </div>
          </div>

          {dup.primary_roe_driver && (
            <p className="dupont-driver">
              <strong>Driver:</strong> {dup.primary_roe_driver}
            </p>
          )}

          <DuPontTable trend={dup.trend} />
        </div>
      )}
    </div>
  );
}
