import React, { useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell
} from 'recharts';
import './QuarterlyResults.css';

function growthPct(current, prev) {
  if (current == null || prev == null || prev === 0) return null;
  return ((current - prev) / Math.abs(prev)) * 100;
}

function GrowthBadge({ current, prev }) {
  const pct = growthPct(current, prev);
  if (pct == null) return null;
  const cls = pct >= 0 ? 'positive' : 'negative';
  const arrow = pct >= 0 ? '▲' : '▼';
  return <span className={`growth-badge ${cls}`}>{arrow} {Math.abs(pct).toFixed(1)}%</span>;
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="tooltip-label">{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color }}>
          {p.name}: {p.dataKey === 'opm'
            ? `${Number(p.value).toFixed(1)}%`
            : `₹${Number(p.value).toLocaleString('en-IN')} Cr`}
        </div>
      ))}
    </div>
  );
};

export default function QuarterlyResults({ data }) {
  const [metric, setMetric] = useState('revenue');

  if (!data || data.length === 0) {
    return (
      <div className="card">
        <div className="card-header"><span className="card-title">Quarterly Results</span></div>
        <div className="card-body" style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '40px 0' }}>
          No quarterly data available
        </div>
      </div>
    );
  }

  // Backend delivers quarters oldest -> newest; keep chronological for the chart
  // and for YoY lookups (index - 4 = same quarter one year earlier).
  const chartData = data.map((q, i) => {
    const prev = data[i - 1];
    return {
      quarter: q.quarter,
      revenue: q.revenue,
      net_profit: q.net_profit,
      ebitda: q.ebitda,
      opm: q.opm,
      rev_growth: prev ? growthPct(q.revenue, prev.revenue) : null,
      profit_growth: prev ? growthPct(q.net_profit, prev.net_profit) : null,
    };
  });

  const metricMap = {
    revenue: { key: 'revenue', label: 'Revenue', color: '#6366f1' },
    net_profit: { key: 'net_profit', label: 'Net Profit', color: '#10b981' },
    ebitda: { key: 'ebitda', label: 'EBITDA', color: '#8b5cf6' },
    opm: { key: 'opm', label: 'OPM %', color: '#0ea5e9' },
  };
  const selected = metricMap[metric];

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Quarterly Results</span>
        <div className="metric-tabs">
          {Object.entries(metricMap).map(([k, v]) => (
            <button
              key={k}
              className={`metric-tab ${metric === k ? 'active' : ''}`}
              onClick={() => setMetric(k)}
            >
              {v.label}
            </button>
          ))}
        </div>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={210}>
          <BarChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }} barCategoryGap="28%">
            <defs>
              <linearGradient id="qrGradUp" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={selected.color} stopOpacity={0.95} />
                <stop offset="100%" stopColor={selected.color} stopOpacity={0.45} />
              </linearGradient>
              <linearGradient id="qrGradDown" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ef4444" stopOpacity={0.85} />
                <stop offset="100%" stopColor="#ef4444" stopOpacity={0.35} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="4 8" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="quarter" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 11 }} tickLine={false} axisLine={false} width={55}
              tickFormatter={v => v >= 1000 ? `${(v/1000).toFixed(1)}k` : v} />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(99,102,241,0.05)' }} />
            <Bar dataKey={selected.key} name={selected.label} radius={[8, 8, 2, 2]} animationDuration={650}>
              {chartData.map((entry, index) => {
                const prev = chartData[index - 1];
                const isGreen = prev == null || (entry[selected.key] ?? 0) >= (prev[selected.key] ?? 0);
                return <Cell key={index} fill={isGreen ? 'url(#qrGradUp)' : 'url(#qrGradDown)'} />;
              })}
            </Bar>
          </BarChart>
        </ResponsiveContainer>

        <div className="qr-table-wrap">
          <table className="qr-table">
            <thead>
              <tr>
                <th>Quarter</th>
                <th>Revenue (Cr)</th>
                <th>Net Profit (Cr)</th>
                <th>OPM %</th>
                <th>Rev YoY</th>
                <th>Profit YoY</th>
              </tr>
            </thead>
            <tbody>
              {[...chartData].reverse().map((q, i) => {
                const yoyIdx = chartData.findIndex(x => x.quarter === q.quarter) - 4;
                const yoyQ = yoyIdx >= 0 ? chartData[yoyIdx] : null;
                return (
                  <tr key={i}>
                    <td className="qr-quarter">{q.quarter}</td>
                    <td>{q.revenue != null ? Number(q.revenue).toLocaleString('en-IN') : '—'}</td>
                    <td className={q.net_profit > 0 ? 'positive' : q.net_profit < 0 ? 'negative' : ''}>
                      {q.net_profit != null ? Number(q.net_profit).toLocaleString('en-IN') : '—'}
                    </td>
                    <td>{q.opm != null ? `${Number(q.opm).toFixed(1)}%` : '—'}</td>
                    <td>{yoyQ ? <GrowthBadge current={q.revenue} prev={yoyQ.revenue} /> : '—'}</td>
                    <td>{yoyQ ? <GrowthBadge current={q.net_profit} prev={yoyQ.net_profit} /> : '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
