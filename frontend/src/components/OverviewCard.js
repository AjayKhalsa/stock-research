import React, { useState, useMemo } from 'react';
import {
  ComposedChart, Area, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, ReferenceArea,
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
      {p.volume > 0 && (
        <div style={{ fontSize: 11, color: p.upDay ? '#10b981' : '#ef4444' }}>
          Vol {p.volume >= 1e7 ? `${(p.volume / 1e7).toFixed(1)} Cr` : `${(p.volume / 1e5).toFixed(1)} L`}
        </div>
      )}
    </div>
  );
};

function PriceChart({ history, levels }) {
  const [range, setRange] = useState('6M');

  const { slice, up, changePct, hasVolume } = useMemo(() => {
    const days = RANGES.find(r => r.key === range)?.days ?? 126;
    const s = history.slice(-days).map((c, i, arr) => ({
      ...c,
      upDay: i === 0 ? true : c.close >= arr[i - 1].close,
    }));
    const first = s[0]?.close, last = s[s.length - 1]?.close;
    const isUp = last >= first;
    const chg = first ? ((last - first) / first) * 100 : 0;
    const hv = s.some(c => (c.volume || 0) > 0);
    return { slice: s, up: isUp, changePct: chg, hasVolume: hv };
  }, [history, range]);

  // Trade-plan levels (entry zone / stop / targets) drawn as reference marks.
  // Extend the y-domain so stop and targets stay visible in context.
  const { entry, stop, targets, yDomain } = useMemo(() => {
    const e = levels?.entry, st = levels?.stop, tg = levels?.targets || [];
    const levelVals = [
      e?.low, e?.high, st?.price, ...tg.map(t => t.price),
    ].filter(v => v != null);
    if (!levelVals.length) return { entry: e, stop: st, targets: tg, yDomain: ['auto', 'auto'] };
    return {
      entry: e, stop: st, targets: tg,
      yDomain: [
        (dataMin) => Math.min(dataMin, ...levelVals) * 0.995,
        (dataMax) => Math.max(dataMax, ...levelVals) * 1.005,
      ],
    };
  }, [levels]);

  if (!history || history.length < 5) return null;

  const color = up ? '#10b981' : '#ef4444';
  const gid = up ? 'pcGradUp' : 'pcGradDown';
  const first = slice[0]?.close;
  const levelLabel = (text, fill) => ({
    value: text, position: 'insideTopRight', fill, fontSize: 10, fontWeight: 700,
  });

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
        <ComposedChart data={slice} margin={{ top: 8, right: 0, left: 0, bottom: 0 }}>
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
            domain={yDomain}
            tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
            tickLine={false} axisLine={false}
            width={58}
            tickFormatter={(v) => v >= 1000 ? `${(v / 1000).toFixed(1)}k` : Math.round(v)}
          />
          {hasVolume && (
            <YAxis
              yAxisId="vol"
              orientation="right"
              domain={[0, (dataMax) => dataMax * 6]}
              hide
            />
          )}
          <Tooltip content={<ChartTooltip />} cursor={{ stroke: 'var(--border-strong)', strokeDasharray: '4 4' }} />
          {first != null && (
            <ReferenceLine y={first} stroke="var(--text-muted)" strokeDasharray="4 6" strokeOpacity={0.5} />
          )}
          {/* Target channel: entry baseline up to the last target (light green) */}
          {entry?.low != null && targets.length > 0 && targets[targets.length - 1].price != null && (
            <ReferenceArea
              y1={(entry.low + entry.high) / 2} y2={targets[targets.length - 1].price}
              fill="rgba(16,185,129,0.07)" stroke="none"
            />
          )}
          {/* Risk channel: entry baseline down to the hard stop (light red) */}
          {entry?.low != null && stop?.price != null && (
            <ReferenceArea
              y1={stop.price} y2={(entry.low + entry.high) / 2}
              fill="rgba(239,68,68,0.07)" stroke="none"
            />
          )}
          {entry?.low != null && entry?.high != null && (
            <ReferenceArea
              y1={entry.low} y2={entry.high}
              fill="rgba(99,102,241,0.10)" stroke="rgba(99,102,241,0.35)" strokeDasharray="3 3"
              label={levelLabel('Entry', '#6366f1')}
            />
          )}
          {stop?.price != null && (
            <ReferenceLine
              y={stop.price} stroke="#ef4444" strokeDasharray="4 4" strokeWidth={1.5}
              label={levelLabel(`Stop ${stop.price}`, '#ef4444')}
            />
          )}
          {targets.map(t => t.price != null && (
            <ReferenceLine
              key={t.label}
              y={t.price} stroke="#10b981" strokeDasharray="4 4" strokeWidth={1.5}
              label={levelLabel(`${t.label} ${t.price}`, '#10b981')}
            />
          ))}
          {hasVolume && (
            <Bar yAxisId="vol" dataKey="volume" isAnimationActive={false} barSize={3}>
              {slice.map((c, i) => (
                <Cell key={i} fill={c.upDay ? 'rgba(16,185,129,0.35)' : 'rgba(239,68,68,0.35)'} />
              ))}
            </Bar>
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
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function convictionColor(s) {
  if (s == null) return '#94a3b8';
  if (s >= 70) return '#10b981';
  if (s >= 50) return '#6366f1';
  if (s >= 30) return '#f59e0b';
  return '#ef4444';
}

/* Dual-conviction chips: two explicit lenses instead of one ambiguous rating */
function DualConviction({ synthesis }) {
  if (!synthesis?.lenses) return null;
  const trade = synthesis.lenses.find(l => l.key === 'trade');
  const biz = synthesis.lenses.find(l => l.key === 'business');
  if (!trade && !biz) return null;
  const chip = (label, score, tip) => (
    <span title={tip} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      fontSize: 11.5, fontWeight: 700, padding: '4px 12px', borderRadius: 999,
      background: 'var(--bg-inset)', border: '1px solid var(--border)',
      color: 'var(--text-secondary)', whiteSpace: 'nowrap',
    }}>
      {label}
      <strong style={{ color: convictionColor(score), fontSize: 13 }}>
        {score != null ? `${score}/100` : '—'}
      </strong>
    </span>
  );
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
      {chip('Technical Trend Setup Strength', trade?.score,
            'Structural price velocity, setup quality, base rates, relative strength — the days-to-weeks lens')}
      {chip('Fundamental Corporate Health', biz?.score,
            'Piotroski, Altman Z, ROE composite — the quarters-to-years lens')}
    </div>
  );
}

export default function OverviewCard({ data, planLevels, synthesis, demo = false }) {
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
        {!demo && (
          <button className="btn btn-ghost btn-sm" onClick={handleAddWatchlist} disabled={adding}>
            {adding ? '...' : '+ Watchlist'}
          </button>
        )}
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
        <span style={{
          fontSize: 10.5, fontWeight: 700, padding: '3px 10px', borderRadius: 999,
          background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.4)',
          color: '#b45309', whiteSpace: 'nowrap', alignSelf: 'center',
        }} title="Quotes come from Yahoo Finance and lag the exchange by ~15 minutes. Verify live LTP on your broker before acting.">
          ⚠️ Delayed Data: Yahoo Finance (~15m lag)
        </span>
      </div>

      <DualConviction synthesis={synthesis} />

      {data.price_history?.length > 4 && <PriceChart history={data.price_history} levels={planLevels} />}

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
