import React from 'react';

/**
 * Structural UI override: when the setup is broken (verdict Avoid or price
 * below the 200-DMA) the entire active trade-planning space is replaced by
 * this block and the Kite execution module is hidden — no accidental entries
 * on broken charts.
 */
export default function Gatekeeper({ planData }) {
  const structure = planData?.price_action?.signals?.structure;
  const swing = planData?.swing || {};
  const kl = planData?.key_levels || {};
  const trendText = structure?.detail
    || (structure?.state ? `market structure: ${structure.state}` : 'downtrend');

  const reasons = [
    ...(swing.notes || []),
    ...(swing.flags || []),
  ].filter((v, i, a) => a.indexOf(v) === i).slice(0, 3);

  return (
    <div className="card gatekeeper" style={{
      padding: '22px 24px',
      background: 'linear-gradient(135deg, rgba(239,68,68,0.07), rgba(190,18,60,0.05))',
      border: '1px solid rgba(239,68,68,0.4)',
      borderLeft: '5px solid #dc2626',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
        <span style={{ fontSize: 26 }}>🚫</span>
        <div>
          <div style={{ fontSize: 17, fontWeight: 800, color: '#dc2626', letterSpacing: 0.3 }}>
            AVOID: The structural evidence stack is completely against a long trade.
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 3 }}>
            Current trend: <strong style={{ color: '#dc2626' }}>{trendText}</strong>
            {planData?.price != null && kl.ma200 != null && planData.price < kl.ma200 && (
              <> · price ₹{planData.price.toLocaleString('en-IN')} is below the 200-DMA
                 (₹{kl.ma200.toLocaleString('en-IN')})</>
            )}
          </div>
        </div>
      </div>

      {reasons.length > 0 && (
        <ul style={{ margin: '10px 0 0', paddingLeft: 20, fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
          {reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}

      <div style={{
        marginTop: 14, fontSize: 12, color: 'var(--text-muted)',
        borderTop: '1px solid rgba(239,68,68,0.2)', paddingTop: 10,
      }}>
        The trade-planning and execution modules are hidden on broken setups to
        prevent accidental entries. They reappear when the structure repairs
        (price reclaims the 200-DMA / verdict upgrades from Avoid).
      </div>
    </div>
  );
}
