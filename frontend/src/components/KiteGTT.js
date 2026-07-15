import React, { useState, useMemo } from 'react';
import toast from 'react-hot-toast';

/**
 * Zerodha Kite GTT ticket helper: turns the trade plan's levels into the
 * exact numbers a Kite GTT OCO order form asks for, sized from a fixed
 * risk amount. Pure calculator — no broker connection; every value has a
 * clipboard button for pasting straight into Kite.
 */

function CopyField({ label, value, suffix = '', hint }) {
  const display = value == null || Number.isNaN(value) ? '—' : `${value}${suffix}`;
  const copy = async () => {
    if (value == null || Number.isNaN(value)) return;
    try {
      await navigator.clipboard.writeText(String(value));
      toast.success(`${label} copied: ${display}`, { duration: 1800 });
    } catch {
      toast.error('Clipboard unavailable');
    }
  };
  return (
    <div className="gtt-field" title={hint || ''}>
      <div className="gtt-field-label">{label}</div>
      <div className="gtt-field-row">
        <span className="gtt-field-value">{display}</span>
        <button className="gtt-copy" onClick={copy} title={`Copy ${label}`}>📋</button>
      </div>
    </div>
  );
}

export default function KiteGTT({ plan, livePrice, symbol }) {
  const entry = plan?.entry || {};
  const stop = plan?.stop || {};
  const targets = plan?.targets || [];

  const defaultLimit = livePrice ?? (entry.low != null && entry.high != null
    ? Math.round(((entry.low + entry.high) / 2) * 100) / 100 : null);

  const [riskAmount, setRiskAmount] = useState(5000);
  const [limitPrice, setLimitPrice] = useState(defaultLimit ?? '');
  const [stopPrice, setStopPrice] = useState(stop.price ?? '');
  const [targetPrice, setTargetPrice] = useState(targets[0]?.price ?? '');

  const calc = useMemo(() => {
    const risk = parseFloat(riskAmount);
    const lim = parseFloat(limitPrice);
    const sl = parseFloat(stopPrice);
    const tgt = parseFloat(targetPrice);
    const perShareRisk = lim - sl;
    const qty = risk > 0 && perShareRisk > 0 ? Math.floor(risk / perShareRisk) : null;
    const slPct = lim > 0 && sl > 0 ? (((lim - sl) / lim) * -100).toFixed(2) : null;
    const tgtPct = lim > 0 && tgt > 0 ? (((tgt - lim) / lim) * 100).toFixed(2) : null;
    const capital = qty != null && lim > 0 ? Math.round(qty * lim) : null;
    return { qty, slPct, tgtPct, capital, perShareRisk };
  }, [riskAmount, limitPrice, stopPrice, targetPrice]);

  const numInput = (value, setter, step = '0.05') => (
    <input
      type="number" step={step} value={value}
      onChange={e => setter(e.target.value)}
      className="gtt-input"
    />
  );

  return (
    <div className="card kite-gtt" style={{ padding: 20 }}>
      <div className="tp-header" style={{ marginBottom: 12 }}>
        <div className="tp-title">🪁 Kite GTT Ticket {symbol ? `· ${symbol}` : ''}</div>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Risk-based sizing · OCO stop + target
        </span>
      </div>

      <div className="gtt-grid">
        <div className="gtt-field">
          <div className="gtt-field-label">Risk Amount (₹)</div>
          {numInput(riskAmount, setRiskAmount, '500')}
        </div>
        <div className="gtt-field">
          <div className="gtt-field-label">Limit Price (₹)</div>
          {numInput(limitPrice, setLimitPrice)}
        </div>
        <div className="gtt-field">
          <div className="gtt-field-label">Stop Loss (₹)</div>
          {numInput(stopPrice, setStopPrice)}
        </div>
        <div className="gtt-field">
          <div className="gtt-field-label">Target (₹)</div>
          {numInput(targetPrice, setTargetPrice)}
        </div>
      </div>

      <div className="gtt-grid gtt-outputs">
        <CopyField label="Buy Qty" value={calc.qty}
                   hint="floor(Risk Amount ÷ (Limit − Stop)) — you lose at most the risk amount if the stop fires" />
        <CopyField label="Capital Required" value={calc.capital != null ? calc.capital.toLocaleString('en-IN') : null}
                   hint="Buy Qty × Limit Price" />
        <CopyField label="GTT Stoploss %" value={calc.slPct} suffix="%"
                   hint="((Limit − Stop) / Limit) × −100 — paste into the Kite GTT stoploss trigger" />
        <CopyField label="GTT Target %" value={calc.tgtPct} suffix="%"
                   hint="((Target − Limit) / Limit) × 100 — paste into the Kite GTT target trigger" />
      </div>

      {calc.perShareRisk <= 0 && limitPrice && stopPrice && (
        <div style={{ fontSize: 12, color: '#ef4444', marginTop: 8 }}>
          Stop must be below the limit price for a long position.
        </div>
      )}

      <div style={{ fontSize: 11, fontStyle: 'italic', color: 'var(--text-muted)', marginTop: 12 }}>
        *Manually verify live LTP on the Kite platform before committing execution capital —
        prices here are delayed (~15m).
      </div>
    </div>
  );
}
