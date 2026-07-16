import React from 'react';
import InfoTip from './InfoTip';
import { METRIC_INFO, GLASS_METRICS } from '../metricInfo';
import './Technicals.css';

function PriceVsMA({ label, price, ma, info }) {
  if (price == null || ma == null) return null;
  const above = price > ma;
  const diff = ((price - ma) / ma * 100).toFixed(2);
  return (
    <div className="tech-ma-row">
      <span className="tech-ma-label">{label}<InfoTip text={info} /></span>
      <span className="tech-ma-value">₹{Number(ma).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
      <span className={`tech-ma-diff ${above ? 'positive' : 'negative'}`}>
        {above ? '▲' : '▼'} {Math.abs(diff)}%
      </span>
    </div>
  );
}

function RSIGauge({ rsi }) {
  if (rsi == null) return null;
  const pct = Math.min(Math.max(rsi, 0), 100);
  let zone = 'neutral';
  let label = 'Neutral';
  if (rsi >= 70) { zone = 'overbought'; label = 'Overbought'; }
  else if (rsi <= 30) { zone = 'oversold'; label = 'Oversold'; }
  else if (rsi >= 55) { label = 'Bullish'; }
  else if (rsi <= 45) { label = 'Bearish'; }

  return (
    <div className="rsi-wrap">
      <div className="rsi-header">
        <span className="rsi-label" style={{ display: 'inline-flex', flexDirection: 'column' }}>
          <span>RSI (Relative Strength Index)
            <InfoTip text={GLASS_METRICS.rsi.tldr} math={GLASS_METRICS.rsi.math} width={290} />
          </span>
          <span style={{ fontSize: 10, fontWeight: 500, color: 'var(--text-muted)' }}>
            {GLASS_METRICS.rsi.subtitle}
          </span>
        </span>
        <span className={`rsi-value rsi-${zone}`}>{rsi} — {label}</span>
      </div>
      <div className="rsi-bar-bg">
        <div className="rsi-bar-fill" style={{ width: `${pct}%`, background: zone === 'overbought' ? 'var(--accent-red)' : zone === 'oversold' ? 'var(--accent-green)' : 'var(--accent-blue)' }} />
        <div className="rsi-zone-30" />
        <div className="rsi-zone-70" />
      </div>
      <div className="rsi-bar-labels">
        <span>Oversold (30)</span>
        <span>Overbought (70)</span>
      </div>
    </div>
  );
}

export default function Technicals({ data, livePrice, dossier }) {
  if (!data || Object.keys(data).length === 0) {
    return (
      <div className="card">
        <div className="card-header"><span className="card-title">Technical Snapshot</span></div>
        <div className="card-body" style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '30px 0' }}>
          Technical data unavailable — price history could not be fetched
        </div>
      </div>
    );
  }

  const price = livePrice ?? data.current_price;
  const trend = data.trend;
  const trendConfig = {
    Uptrend: { icon: '📈', cls: 'positive', desc: 'Price above 50 DMA and 50 DMA > 200 DMA' },
    Downtrend: { icon: '📉', cls: 'negative', desc: 'Price below 50 DMA and 50 DMA < 200 DMA' },
    Sideways: { icon: '↔️', cls: 'neutral', desc: 'Mixed signals between moving averages' },
  };
  const tc = trend ? trendConfig[trend] : null;

  return (
    <div className="card">
      <div className="card-header"><span className="card-title">Technical Snapshot</span></div>
      <div className="card-body">
        {tc && (
          <div className={`trend-banner trend-${tc.cls}`}>
            <span className="trend-icon">{tc.icon}</span>
            <div>
              <div className={`trend-text ${tc.cls}`}>{trend}</div>
              <div className="trend-desc">{tc.desc}</div>
            </div>
          </div>
        )}

        <div className="tech-ma-section">
          <PriceVsMA label="50 DMA" price={price} ma={data.ma50} info={METRIC_INFO.ma50} />
          <PriceVsMA label="200 DMA" price={price} ma={data.ma200} info={METRIC_INFO.ma200} />
          {dossier?.relative_strength?.beta != null && (
            <div className="tech-ma-row">
              <span className="tech-ma-label">Beta vs NIFTY<InfoTip text={METRIC_INFO.beta} /></span>
              <span className="tech-ma-value">{dossier.relative_strength.beta}×</span>
              <span className={`tech-ma-diff ${dossier.relative_strength.beta > 1.3 ? 'negative' : 'neutral'}`}>
                {dossier.relative_strength.beta > 1.3 ? 'amplified' :
                 dossier.relative_strength.beta < 0.8 ? 'defensive' : 'market-like'}
              </span>
            </div>
          )}
        </div>

        <RSIGauge rsi={data.rsi} />
      </div>
    </div>
  );
}
