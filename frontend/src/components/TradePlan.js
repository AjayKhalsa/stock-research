import React, { useState } from 'react';
import toast from 'react-hot-toast';
import { createAlertsFromPlan } from '../api';
import './TradePlan.css';

function fmtINR(v) {
  if (v == null) return '—';
  return `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

function verdictColors(verdict = '') {
  if (verdict === 'Buy')        return { bg: 'rgba(16,185,129,0.10)', color: '#10b981', border: 'rgba(16,185,129,0.4)' };
  if (verdict === 'Buy on Dip') return { bg: 'rgba(99,102,241,0.10)', color: '#6366f1', border: 'rgba(99,102,241,0.4)' };
  if (verdict === 'Wait')       return { bg: 'rgba(245,158,11,0.12)', color: '#f59e0b', border: 'rgba(245,158,11,0.4)' };
  return { bg: 'rgba(239,68,68,0.08)', color: '#ef4444', border: 'rgba(239,68,68,0.4)' };
}

function confColor(c) {
  if (c == null) return '#94a3b8';
  if (c >= 70) return '#10b981';
  if (c >= 50) return '#6366f1';
  if (c >= 30) return '#f59e0b';
  return '#ef4444';
}

const HORIZONS = [
  { key: 'swing',      label: 'Swing (days–weeks)' },
  { key: 'positional', label: 'Positional (weeks–months)' },
];

async function copyValue(value, label) {
  try {
    await navigator.clipboard.writeText(String(value));
    toast.success(`${label} copied: ${value}`, { duration: 1600 });
  } catch {
    toast.error('Clipboard unavailable');
  }
}

/* Absolute price (click-to-copy) + GTT offset % chip vs the delayed close */
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
          title={`GTT offset vs delayed close — click to copy ${offsetStr}%`}
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

function paChips(pa) {
  if (!pa) return [];
  const chips = [];
  const add = (label, tone, tip) => chips.push({ label, tone, tip });

  const ms = pa.structure?.state;
  if (ms === 'uptrend')  add('Structure: HH/HL', 'good', pa.structure.detail);
  if (ms === 'downtrend') add('Structure: LH/LL', 'bad', pa.structure.detail);
  if (ms === 'mixed')    add('Structure: mixed', 'warn', pa.structure.detail);

  const obv = pa.obv?.state;
  if (obv === 'confirming') add('OBV confirms', 'good', pa.obv.detail);
  if (obv === 'bearish_divergence') add('OBV divergence ⚠', 'bad', pa.obv.detail);
  if (obv === 'bullish_divergence') add('OBV bull divergence', 'good', pa.obv.detail);
  if (obv === 'confirming_down') add('OBV confirms downtrend', 'bad', pa.obv.detail);

  const dd = pa.distribution_days;
  if (dd != null) add(`${dd} distribution day${dd === 1 ? '' : 's'}/25`, dd >= 4 ? 'bad' : dd <= 1 ? 'good' : 'warn',
                      'Heavy-volume down days — institutional selling footprint (O’Neil)');

  const pp = pa.pocket_pivots || [];
  if (pp.length > 0) add(`Pocket pivot ${pp[pp.length - 1]}`, 'good',
                         'Up-day volume exceeded every down-day volume of the prior 10 sessions');

  const pvc = pa.pullback_volume?.state;
  if (pvc === 'dry_up') add('Pullback vol drying up', 'good', pa.pullback_volume.detail);
  if (pvc === 'expansion') add('Pullback vol expanding ⚠', 'bad', pa.pullback_volume.detail);

  const udr = pa.up_down_volume_ratio;
  if (udr != null) add(`U/D vol ${udr}`, udr >= 1.2 ? 'good' : udr <= 0.8 ? 'bad' : 'warn',
                       'Up-day vs down-day volume over 50 sessions — accumulation vs distribution');

  if (pa.tightness?.contracting) add(pa.tightness.nr7 ? 'VCP + NR7' : 'VCP tightening', 'good',
                                     'Successive pullbacks contracting — tightness precedes strong breakouts');
  if (pa.climax?.state === 'climax') add('Climax volume ⚠', 'bad', pa.climax.detail);
  return chips;
}

const CHIP_TONES = {
  good: { color: '#10b981', border: 'rgba(16,185,129,0.4)' },
  bad:  { color: '#ef4444', border: 'rgba(239,68,68,0.4)' },
  warn: { color: '#f59e0b', border: 'rgba(245,158,11,0.4)' },
};

function TheCase({ dossier }) {
  const [showChecklist, setShowChecklist] = useState(false);
  const { case: c, base_rates: br, trend_template: tt, relative_strength: rs } = dossier;
  const chips = paChips(dossier.price_action);
  if (!c) return null;

  const convColor = confColor(c.conviction);
  const total = (c.bull_points || 0) + (c.bear_points || 0) || 1;

  return (
    <div className="tp-case">
      <div className="tp-case-header">
        <span className="tp-case-title">⚖️ The Case</span>
        <span className="tp-case-final" style={{ color: convColor }}>{c.final_call}</span>
      </div>

      {/* bull vs bear tug-of-war bar */}
      <div className="tp-case-bar" title={`Bull ${c.bull_points} vs Bear ${c.bear_points} — conviction ${c.conviction}/100`}>
        <div className="tp-case-bar-bull" style={{ width: `${(c.bull_points / total) * 100}%` }} />
        <div className="tp-case-bar-bear" style={{ width: `${(c.bear_points / total) * 100}%` }} />
      </div>
      <div className="tp-case-bar-legend">
        <span style={{ color: '#10b981' }}>Bull {c.bull_points}</span>
        <span style={{ color: convColor, fontWeight: 700 }}>Conviction {c.conviction}/100</span>
        <span style={{ color: '#ef4444' }}>Bear {c.bear_points}</span>
      </div>

      {/* base rates: the convincer */}
      {br && (
        <div className={`tp-baserates ${br.expected_r != null && br.expected_r > 0 ? 'good' : br.expected_r != null ? 'bad' : ''}`}>
          <div className="tp-baserates-title">
            📜 What history says about this exact setup on this stock
          </div>
          {br.n >= 5 ? (
            <div className="tp-baserates-stats">
              <span><strong>{br.n}</strong> occurrences</span>
              <span><strong>{br.win_rate}%</strong> hit target first</span>
              <span><strong>{br.expected_r > 0 ? '+' : ''}{br.expected_r}R</strong> expected value/trade</span>
              <span><strong>{br.median_hold}</strong> bars median hold</span>
            </div>
          ) : (
            <div className="tp-baserates-note">{br.note}</div>
          )}
        </div>
      )}

      {/* price action & volume chips */}
      {chips.length > 0 && (
        <div className="tp-pa-strip">
          <span className="tp-pa-title">Price action & volume:</span>
          {chips.map((ch, i) => (
            <span key={i} className="tp-pa-chip" title={ch.tip}
                  style={{ color: CHIP_TONES[ch.tone].color, borderColor: CHIP_TONES[ch.tone].border }}>
              {ch.label}
            </span>
          ))}
        </div>
      )}

      {/* evidence ledger */}
      <div className="tp-ledger">
        {c.ledger.map((e, i) => (
          <div key={i} className="tp-ledger-row">
            <span className={`tp-ledger-pts ${e.side}`}>
              {e.side === 'bull' ? '▲' : '▼'} {e.points}
            </span>
            <span className="tp-ledger-text">{e.text}</span>
          </div>
        ))}
      </div>

      {/* trend template checklist */}
      {tt?.score != null && (
        <div className="tp-checklist">
          <button className="tp-checklist-toggle" onClick={() => setShowChecklist(s => !s)}>
            Trend template (Minervini) — {tt.score}/{tt.max_score} {showChecklist ? '▾' : '▸'}
          </button>
          {showChecklist && tt.items.map((it, i) => (
            <div key={i} className="tp-checklist-item">
              <span style={{ color: it.pass ? '#10b981' : '#ef4444' }}>{it.pass ? '✓' : '✗'}</span>
              <span>{it.label}</span>
              <span className="tp-checklist-detail">{it.detail}</span>
            </div>
          ))}
        </div>
      )}

      {rs?.excess_3m != null && (
        <div className="tp-rs-line">
          vs NIFTY: 1M {rs.excess_1m != null ? `${(rs.excess_1m * 100).toFixed(1)}%` : '—'} ·
          3M {(rs.excess_3m * 100).toFixed(1)}% ·
          6M {rs.excess_6m != null ? `${(rs.excess_6m * 100).toFixed(1)}%` : '—'}
          {rs.rs_line_new_high && <span style={{ color: '#10b981' }}> · RS line at 52w high</span>}
        </div>
      )}
    </div>
  );
}

export default function TradePlan({ data, loading, horizon, onHorizonChange, aiCommentary, symbol, exchange, readOnly = false }) {
  const [arming, setArming] = useState(false);

  if (loading && !data) {
    return (
      <div className="card trade-plan" style={{ padding: 20 }}>
        <div className="skeleton" style={{ height: 22, width: '35%', marginBottom: 14 }} />
        <div className="skeleton" style={{ height: 48, marginBottom: 14 }} />
        <div className="tp-skeleton-row">
          {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 84, flex: 1 }} />)}
        </div>
      </div>
    );
  }
  if (!data) return null;

  if (data.error) {
    return (
      <div className="card trade-plan" style={{ padding: 20 }}>
        <div className="tp-title">🎯 Trade Plan</div>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '10px 0 0' }}>
          Trade plan unavailable: {data.error}
        </p>
      </div>
    );
  }

  const plan = data[horizon];
  if (!plan) return null;

  const vc = verdictColors(plan.verdict);
  const gate = plan.fundamentals_gate;
  const hasLevels = plan.entry != null;

  const handleMonitor = async () => {
    setArming(true);
    try {
      const created = await createAlertsFromPlan({
        symbol: symbol || data.symbol,
        exchange: exchange || data.exchange || 'NSE',
        horizon,
        plan,
      });
      toast.success(`${created.length} alert${created.length !== 1 ? 's' : ''} armed for ${symbol || data.symbol} (${horizon}) — checked on delayed data while the app is open`);
    } catch {
      toast.error('Failed to arm alerts — is the backend running?');
    } finally {
      setArming(false);
    }
  };

  return (
    <div className="card trade-plan" style={{ padding: 20 }}>
      <div className="tp-header">
        <div className="tp-title">🎯 Trade Plan</div>
        <div className="tp-horizon-tabs">
          {HORIZONS.map(h => (
            <button
              key={h.key}
              className={`tp-horizon-tab ${horizon === h.key ? 'active' : ''}`}
              onClick={() => onHorizonChange(h.key)}
            >{h.label}</button>
          ))}
        </div>
      </div>

      <div className="tp-verdict-banner" style={{ background: vc.bg, borderColor: vc.border }}>
        <span className="tp-verdict" style={{ color: vc.color }}>{plan.verdict}</span>
        <span className="tp-setup-label">{plan.setup_label}</span>
        <div className="tp-confidence">
          <span>Confidence</span>
          <div className="tp-conf-track">
            <div className="tp-conf-fill" style={{ width: `${plan.confidence ?? 0}%`, background: confColor(plan.confidence) }} />
          </div>
          <strong style={{ color: confColor(plan.confidence) }}>{plan.confidence ?? '—'}</strong>
        </div>
      </div>

      {plan.evidence?.length > 0 && (
        <div className="tp-evidence">
          {plan.evidence.map((e, i) => <span key={i} className="tp-evidence-chip">{e}</span>)}
        </div>
      )}

      {hasLevels ? (
        <>
          <div className="tp-levels">
            <div className="tp-level">
              <div className="tp-level-label" style={{ color: '#6366f1' }}>Entry Zone</div>
              <div className="tp-level-price">{fmtINR(plan.entry.low)} – {fmtINR(plan.entry.high)}</div>
              <div className="tp-level-basis">{plan.entry.rationale}</div>
            </div>
            <div className="tp-level">
              <div className="tp-level-label" style={{ color: '#ef4444' }}>Stop Loss</div>
              <PriceWithOffset price={plan.stop?.price} refPrice={data.price} label="Stop" />
              <div className="tp-level-basis">
                {plan.stop?.rationale}
                {plan.stop?.risk_pct != null && ` · risk ${plan.stop.risk_pct}% from entry`}
              </div>
            </div>
            {plan.targets?.map(t => (
              <div className="tp-level" key={t.label}>
                <div className="tp-level-label" style={{ color: '#10b981' }}>Target {t.label}</div>
                <PriceWithOffset price={t.price} refPrice={data.price} label={t.label} />
                <div className="tp-level-basis">{t.basis}{t.rr != null && !/\dR\b/.test(t.basis) && ` · ${t.rr}R`}</div>
              </div>
            ))}
          </div>

          <div className="tp-stats-row">
            {data.dossier?.case?.conviction != null && (
              <span>Setup Strength <strong style={{ color: confColor(data.dossier.case.conviction) }}>
                {data.dossier.case.conviction}/100</strong></span>
            )}
            {plan.risk_reward != null && (
              <span>Risk : Reward <strong>1 : {plan.risk_reward}</strong></span>
            )}
            {data.atr != null && <span>ATR(14) <strong>{fmtINR(data.atr)}</strong></span>}
            {data.price != null && <span>Last close <strong>{fmtINR(data.price)}</strong> <span style={{ color: 'var(--text-muted)' }}>({data.as_of})</span></span>}
            {plan.exit_rule && <span>Exit rule: <strong>{plan.exit_rule}</strong></span>}
          </div>

          {plan.invalidation && (
            <div className="tp-invalidation">
              <span>⚠️</span>
              <span>{plan.invalidation}</span>
            </div>
          )}

          <div style={{ fontSize: 11, fontStyle: 'italic', color: 'var(--text-muted)', marginBottom: 12 }}>
            *GTT offsets are computed against the delayed close ({fmtINR(data.price)}) —
            verify live LTP on Kite before placing orders.
          </div>
        </>
      ) : (
        <div className="tp-invalidation">
          <span>🚫</span>
          <span>{plan.notes?.[0] || 'No actionable trade levels for this horizon.'}</span>
        </div>
      )}

      {gate && (
        <div className={`tp-gate ${gate.status}`}>
          <strong>Fundamentals gate: </strong>
          {gate.status === 'pass' ? 'Pass' :
           gate.status === 'soft_fail' ? 'Caution' :
           gate.status === 'hard_fail' ? 'Fail' : 'Unavailable'}
          {gate.reasons?.length > 0 && ` — ${gate.reasons.join(' · ')}`}
        </div>
      )}

      {(plan.notes?.length > 0 || plan.flags?.length > 0) && hasLevels && (
        <ul className="tp-notes">
          {plan.flags?.map((f, i) => <li key={`f${i}`} className="tp-flag">{f}</li>)}
          {plan.notes?.map((n, i) => <li key={`n${i}`}>{n}</li>)}
        </ul>
      )}

      {data.dossier && <TheCase dossier={data.dossier} />}

      {aiCommentary && (
        <div className="tp-ai-note">
          <strong style={{ fontStyle: 'normal' }}>AI take: </strong>{aiCommentary}
        </div>
      )}

      <div className="tp-footer">
        <button
          className="tp-monitor-btn"
          onClick={readOnly ? undefined : handleMonitor}
          disabled={readOnly || arming || !hasLevels}
          title={readOnly ? 'Disabled in the guide — on a real stock this arms entry/stop/target alerts'
                 : hasLevels ? 'Create alerts for entry, stop and targets' : 'No levels to monitor'}
        >
          {arming ? 'Arming…' : '🔔 Monitor this plan'}
        </button>
        <div className="tp-disclaimer">{data.disclaimer}</div>
      </div>
    </div>
  );
}
