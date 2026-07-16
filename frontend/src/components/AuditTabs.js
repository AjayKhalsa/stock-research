import React, { useState } from 'react';

/**
 * Sticky tabbed audit trail docked at the bottom of the detail panel.
 * Houses the micro-level spreadsheets (technical signals, fundamental
 * audits, news/filings) so the main vertical flow stays decision-focused.
 */

const TABS = [
  { key: 'technicals',   label: '📐 Technicals & Structural Signals' },
  { key: 'fundamentals', label: '🧾 Fundamental Financial Audits' },
  { key: 'news',         label: '📰 News & Filings Log' },
];

export default function AuditTabs({ technicals, fundamentals, news }) {
  const [active, setActive] = useState(null);   // null = all collapsed

  const content = { technicals, fundamentals, news };

  return (
    <div className="audit-tabs">
      {active && (
        <div className="audit-tabs-body">
          <div className="audit-tabs-content">
            {content[active]}
          </div>
        </div>
      )}
      <div className="audit-tabs-bar">
        <span className="audit-tabs-title">Audit Trail</span>
        {TABS.map(t => (
          <button
            key={t.key}
            className={`audit-tab ${active === t.key ? 'active' : ''}`}
            onClick={() => setActive(a => (a === t.key ? null : t.key))}
          >
            {t.label}
          </button>
        ))}
        {active && (
          <button className="audit-tab audit-tab-close" onClick={() => setActive(null)} title="Collapse">
            ✕
          </button>
        )}
      </div>
    </div>
  );
}
