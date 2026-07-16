import React from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import './Shareholding.css';

const COLORS = {
  promoter: '#6366f1',
  fii: '#10b981',
  dii: '#8b5cf6',
  retail: '#f97316',
};

function Delta({ current, prev }) {
  if (current == null || prev == null) return null;
  const diff = current - prev;
  if (Math.abs(diff) < 0.01) return <span className="delta neutral">~</span>;
  const cls = diff > 0 ? 'positive' : 'negative';
  const arrow = diff > 0 ? '▲' : '▼';
  return <span className={`delta ${cls}`}>{arrow} {Math.abs(diff).toFixed(2)}%</span>;
}

/* Insider / substantial-acquisition disclosures fished out of BSE filings */
const DEAL_KEYWORDS = /sast|insider|acquisition of shares|disposal of shares|pledge|invocation|promoter group|bulk deal|block deal/i;

function InstitutionalFootprint({ announcements }) {
  const deals = (announcements || [])
    .filter(a => DEAL_KEYWORDS.test(a.headline || ''))
    .slice(0, 8);

  return (
    <div className="sh-footprint">
      <div className="sh-footprint-title">Institutional Footprint</div>
      {deals.length > 0 ? (
        <div className="sh-deals">
          {deals.map((d, i) => (
            <a key={i} href={d.url || d.link || undefined} target="_blank" rel="noreferrer"
               className="sh-deal-row" title={d.headline}>
              <span className="sh-deal-date">{(d.date || '').slice(0, 10)}</span>
              <span className="sh-deal-text">{d.headline}</span>
            </a>
          ))}
        </div>
      ) : (
        <div className="sh-footprint-empty">
          No insider / SAST / block-deal disclosures in recent BSE filings.
        </div>
      )}
      <div className="sh-footprint-note">
        Named fund-level holders (top MF/FII stakes) need exchange shareholding
        disclosures — not available from current data sources.
      </div>
    </div>
  );
}

export default function Shareholding({ data, announcements }) {
  if (!data || Object.keys(data).length === 0) {
    return (
      <div className="card">
        <div className="card-header"><span className="card-title">Shareholding Pattern</span></div>
        <div className="card-body" style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '40px 0' }}>
          No shareholding data available
        </div>
        <InstitutionalFootprint announcements={announcements} />
      </div>
    );
  }

  const categories = [
    { key: 'promoter', label: 'Promoter' },
    { key: 'fii', label: 'FII' },
    { key: 'dii', label: 'DII' },
    { key: 'retail', label: 'Public/Retail' },
  ].filter(c => data[c.key] != null);

  const pieData = categories.map(c => ({
    name: c.label,
    value: data[c.key],
    color: COLORS[c.key],
  }));

  const pledgePct = data.promoter_pledge;

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Shareholding Pattern</span>
        {data.latest_quarter && (
          <span className="sh-quarter">{data.latest_quarter}</span>
        )}
      </div>
      <div className="card-body sh-body">
        {pieData.length > 0 && (
          <div className="sh-chart">
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={58}
                  outerRadius={86}
                  paddingAngle={3}
                  cornerRadius={6}
                  dataKey="value"
                  animationDuration={700}
                >
                  {pieData.map((entry, i) => (
                    <Cell key={i} fill={entry.color} stroke="transparent" />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(v) => `${Number(v).toFixed(2)}%`}
                  contentStyle={{
                    background: '#ffffff', border: '1px solid var(--border-strong)',
                    borderRadius: 10, fontSize: 12, boxShadow: '0 8px 24px rgba(16,24,40,0.14)',
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            {data.promoter != null && (
              <div className="sh-center-label">
                <div className="sh-center-value">{Number(data.promoter).toFixed(1)}%</div>
                <div className="sh-center-caption">Promoter</div>
              </div>
            )}
          </div>
        )}

        <div className="sh-rows">
          {categories.map(c => (
            <div key={c.key} className="sh-row">
              <div className="sh-dot" style={{ background: COLORS[c.key] }} />
              <span className="sh-label">{c.label}</span>
              <div className="sh-right">
                <span className="sh-value">{Number(data[c.key]).toFixed(2)}%</span>
                <Delta current={data[c.key]} prev={data[`${c.key}_prev`]} />
              </div>
            </div>
          ))}

          {pledgePct != null && (
            <div className="sh-pledge-row">
              <span className="pledge-icon">⚠️</span>
              <span className="sh-label">
                Promoter Pledged Shares
                {data.promoter != null && (
                  <span style={{ fontSize: 10, color: 'var(--text-muted)', display: 'block' }}>
                    of {Number(data.promoter).toFixed(1)}% promoter holding
                  </span>
                )}
              </span>
              <span className={`sh-value ${pledgePct > 5 ? 'negative' : ''}`}>
                {Number(pledgePct).toFixed(2)}%
              </span>
            </div>
          )}
        </div>
      </div>

      <InstitutionalFootprint announcements={announcements} />
    </div>
  );
}
