import React, { useState, useMemo } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import toast from 'react-hot-toast';
import { addToWatchlist } from '../api';
import InfoTip from './InfoTip';
import { METRIC_INFO } from '../metricInfo';
import './OverviewCard.css';

function fmt(val, decimals = 2) {
  if (val == null) return '—';
  return Number(val).toLocaleString('en-IN', { maximumFractionDigits: decimals });
}

function fmtPct(val) {
  if (val == null) return '—';
  const n = Number(val);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

const RANGES = [
  { key: '1M', days: 21 },
  { key: '3M', days: 63 },
  { key: '6M', days: 126 },
  { key: '1Y', days: 252 },
];

const ChartTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="pc-tooltip">
      <div className="pc-tooltip-date">{p.date}</div>
      <div className="pc-tooltip-price">₹{Number(p.close).toLocaleString('en-IN')}</div>
    </div>
  );
};

function PriceChart({ history }) {
  const [range, setRange] = useState('6M');

  const { slice, up, changePct } = useMemo(() => {
    const days = RANGES.find(r => r.key === range)?.days ?? 126;
    const s = history.slice(-days);
    const first = s[0]?.close, last = s[s.length - 1]?.close;
    const isUp = last >= first;
    const chg = first ? ((last - first) / first) * 100 : 0;
    return { slice: s, up: isUp, changePct: chg };
  }, [history, range]);

  if (!history || history.length < 5) return null;

  const color = up ? '#10b981' : '#ef4444';
  const gid = up ? 'pcGradUp' : 'pcGradDown';
  const first = slice[0]?.close;

  return (
    <div className="pc-wrap">
      <div className="pc-header">
        <span className={`pc-range-change ${up ? 'positive' : 'negative'}`}>
          {up ? '▲' : '▼'} {Math.abs(changePct).toFixed(2)}%
          <span className="pc-range-label"> past {range}</span>
        </span>
        <div className="pc-range-tabs">
          {RANGES.map(r => (
            <button
              key={r.key}
              className={`pc-range-tab ${range === r.key ? 'active' : ''}`}
              onClick={() => setRange(r.key)}
            >{r.key}</button>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={230}>
        <AreaChart data={slice} margin={{ top: 8, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="pcGradUp" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity={0.28} />
              <stop offset="100%" stopColor="#10b981" stopOpacity={0.01} />
            </linearGradient>
            <linearGradient id="pcGradDown" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ef4444" stopOpacity={0.24} />
              <stop offset="100%" stopColor="#ef4444" stopOpacity={0.01} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="date"
            tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
            tickLine={false} axisLine={false}
            minTickGap={70}
            tickFormatter={(d) => {
              const dt = new Date(d);
              return dt.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' });
            }}
          />
          <YAxis
            domain={['auto', 'auto']}
            tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
            tickLine={false} axisLine={false}
            width={58}
            tickFormatter={(v) => v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v}
          />
          <Tooltip content={<ChartTooltip />} cursor={{ stroke: 'var(--border-strong)', strokeDasharray: '4 4' }} />
          {first != null && (
            <ReferenceLine y={first} stroke="var(--text-muted)" strokeDasharray="4 6" strokeOpacity={0.5} />
          )}
          <Area
            type="monotone"
            dataKey="close"
            stroke={color}
            strokeWidth={2.4}
            fill={`url(#${gid})`}
            dot={false}
            activeDot={{ r: 5, strokeWidth: 3, stroke: '#fff', fill: color }}
            animationDuration={600}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function OverviewCard({ data }) {
  const [adding, setAdding] = useState(false);

  const handleAddWatchlist = async () => {
    setAdding(true);
    try {
      await addToWatchlist({ symbol: data.symbol, exchange: data.exchange, name: data.company_name });
      toast.success(`${data.symbol} added to watchlist`);
    } catch {
      toast.error('Failed to add to watchlist');
    } finally {
      setAdding(false);
    }
  };

  const changeClass = data.day_change_pct > 0 ? 'positive' : data.day_change_pct < 0 ? 'negative' : 'neutral';

  const metrics = [
    { label: 'Market Cap', value: data.market_cap ? `₹${data.market_cap} Cr` : '—', info: METRIC_INFO.market_cap },
    { label: 'P/E Ratio', value: fmt(data.pe_ratio), info: METRIC_INFO.pe_ratio },
    { label: 'P/B Ratio', value: fmt(data.pb_ratio), info: METRIC_INFO.pb_ratio },
    { label: 'ROE', value: data.roe != null ? `${fmt(data.roe)}%` : '—', info: METRIC_INFO.roe },
    { label: 'ROCE', value: data.roce != null ? `${fmt(data.roce)}%` : '—', info: METRIC_INFO.roce },
    { label: 'Debt/Equity', value: fmt(data.debt_to_equity), info: METRIC_INFO.debt_to_equity },
    { label: 'Div Yield', value: data.dividend_yield != null ? `${fmt(data.dividend_yield)}%` : '—', info: METRIC_INFO.dividend_yield },
    { label: 'Book Value', value: fmt(data.book_value), info: METRIC_INFO.book_value },
  ];

  const promoterHolding = data.shareholding?.promoter;
  const pledgePct = data.shareholding?.promoter_pledge;

  return (
    <div className="card overview-card">
      <div className="ov-header">
        <div>
          <div className="ov-company">{data.company_name}</div>
          <div className="ov-symbol">
            <span>{data.symbol}</span>
            <span className="ov-exchange">{data.exchange}</span>
          </div>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={handleAddWatchlist} disabled={adding}>
          {adding ? '...' : '+ Watchlist'}
        </button>
      </div>

      <div className="ov-price-row">
        <div className="ov-price">
          ₹{data.live_price != null ? fmt(data.live_price) : '—'}
        </div>
        {data.day_change != null && (
          <div className={`ov-change ${changeClass}`}>
            {data.day_change >= 0 ? '▲' : '▼'} ₹{Math.abs(data.day_change).toFixed(2)} ({fmtPct(data.day_change_pct)})
          </div>
        )}
      </div>

      {data.price_history?.length > 4 && <PriceChart history={data.price_history} />}

      <div className="ov-range-row">
        {data.open != null && <span>Open <strong>₹{fmt(data.open)}</strong></span>}
        {data.high != null && <span>High <strong className="positive">₹{fmt(data.high)}</strong></span>}
        {data.low != null && <span>Low <strong className="negative">₹{fmt(data.low)}</strong></span>}
        {data.week_high_52 != null && <span>52W High <strong className="positive">₹{fmt(data.week_high_52)}</strong></span>}
        {data.week_low_52 != null && <span>52W Low <strong className="negative">₹{fmt(data.week_low_52)}</strong></span>}
      </div>

      <div className="ov-metrics">
        {metrics.map((m) => (
          <div key={m.label} className="ov-metric">
            <div className="ov-metric-label">{m.label}<InfoTip text={m.info} /></div>
            <div className="ov-metric-value">{m.value ?? '—'}</div>
          </div>
        ))}
        {promoterHolding != null && (
          <div className="ov-metric">
            <div className="ov-metric-label">Promoter %<InfoTip text={METRIC_INFO.promoter_holding} /></div>
            <div className="ov-metric-value">{fmt(promoterHolding)}%</div>
          </div>
        )}
        {pledgePct != null && (
          <div className="ov-metric">
            <div className="ov-metric-label">Pledged %<InfoTip text={METRIC_INFO.promoter_pledge} /></div>
            <div className={`ov-metric-value ${pledgePct > 5 ? 'negative' : ''}`}>
              {fmt(pledgePct)}%
              {pledgePct > 5 && <span className="pledge-warn" title="High pledge!"> ⚠️</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
