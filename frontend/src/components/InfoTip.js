import React from 'react';
import './InfoTip.css';

/**
 * Small "i" icon that reveals an explanation tooltip on hover / keyboard focus.
 * Usage: <InfoTip text="What this metric means" />
 * Two-tier glass-box mode: <InfoTip text={tldr} math={exactFormula} /> renders
 * the TL;DR followed by the exact formula in monospace — the metric stays
 * auditable without cluttering the layout.
 */
export default function InfoTip({ text, math, width = 240 }) {
  if (!text) return null;
  return (
    <span className="itip" tabIndex={0} aria-label={typeof text === 'string' ? text : undefined}>
      <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <rect x="7.2" y="6.9" width="1.6" height="4.8" rx="0.8" fill="currentColor" />
        <circle cx="8" cy="4.7" r="1" fill="currentColor" />
      </svg>
      <span className="itip-pop" style={{ width: math ? Math.max(width, 300) : width }}>
        {text}
        {math && (
          <span style={{
            display: 'block', marginTop: 8, paddingTop: 8,
            borderTop: '1px solid rgba(148,163,184,0.3)',
            fontFamily: 'var(--font-mono)', fontSize: 10.5, lineHeight: 1.6,
            opacity: 0.9, whiteSpace: 'normal', wordBreak: 'break-word',
          }}>
            <strong style={{ fontFamily: 'inherit' }}>The math: </strong>{math}
          </span>
        )}
      </span>
    </span>
  );
}
