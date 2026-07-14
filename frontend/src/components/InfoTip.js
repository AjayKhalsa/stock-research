import React from 'react';
import './InfoTip.css';

/**
 * Small "i" icon that reveals an explanation tooltip on hover / keyboard focus.
 * Usage: <InfoTip text="What this metric means" />
 */
export default function InfoTip({ text, width = 240 }) {
  if (!text) return null;
  return (
    <span className="itip" tabIndex={0} aria-label={text}>
      <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <rect x="7.2" y="6.9" width="1.6" height="4.8" rx="0.8" fill="currentColor" />
        <circle cx="8" cy="4.7" r="1" fill="currentColor" />
      </svg>
      <span className="itip-pop" style={{ width }}>{text}</span>
    </span>
  );
}
