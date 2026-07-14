import React, { useState } from 'react';
import './NewsFeed.css';

function timeAgo(dateStr) {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days < 30) return `${days}d ago`;
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  } catch { return dateStr; }
}

function ScoreBadge({ score }) {
  if (score == null) return null;
  const s = Number(score);
  const cls = s > 0.1 ? 'score-pos' : s < -0.1 ? 'score-neg' : 'score-neu';
  const sign = s > 0 ? '+' : '';
  return <span className={`score-badge ${cls}`}>{sign}{s.toFixed(2)}</span>;
}

function SentimentTag({ label }) {
  if (!label) return null;
  return <span className={`tag tag-${label.toLowerCase()}`}>{label}</span>;
}

/* ── Google News items ─────────────────────────────────────────────────────── */
function NewsItem({ item }) {
  return (
    <a href={item.link} target="_blank" rel="noopener noreferrer" className="news-item">
      <div className="news-item-top">
        {item.red_flag && <span className="red-flag" title="Risk signal detected">🚩</span>}
        <span className="news-title">{item.title}</span>
      </div>
      <div className="news-meta">
        <span className="news-source">{item.source}</span>
        <span className="news-time">{timeAgo(item.published)}</span>
        <SentimentTag label={item.sentiment} />
        {item.score != null && <ScoreBadge score={item.score} />}
      </div>
    </a>
  );
}

/* ── BSE announcement items ────────────────────────────────────────────────── */
function AnnItem({ item }) {
  return (
    <a
      href={item.link || '#'}
      target={item.link ? '_blank' : '_self'}
      rel="noopener noreferrer"
      className="news-item"
    >
      <div className="news-item-top">
        {item.red_flag && <span className="red-flag" title="Risk signal detected">🚩</span>}
        <span className="news-title">{item.headline || item.title || '—'}</span>
      </div>
      <div className="news-meta">
        <span className="news-source bse-tag">BSE</span>
        {item.category && <span className="news-category">{item.category}</span>}
        <span className="news-time">{timeAgo(item.date)}</span>
        <SentimentTag label={item.label} />
        {item.score != null && <ScoreBadge score={item.score} />}
      </div>
    </a>
  );
}

/* ── overall sentiment bar ─────────────────────────────────────────────────── */
function SentimentBar({ sentiment }) {
  if (!sentiment) return null;
  const { positive = 0, negative = 0, neutral = 0, composite_score, composite_label } = sentiment;
  const total = positive + negative + neutral || 1;
  const cls = composite_label?.toLowerCase() || 'neutral';
  return (
    <div className="sentiment-bar-wrap">
      <div className="sentiment-bar">
        <div className="sb-pos"  style={{ width: `${(positive / total) * 100}%` }} />
        <div className="sb-neu"  style={{ width: `${(neutral  / total) * 100}%` }} />
        <div className="sb-neg"  style={{ width: `${(negative / total) * 100}%` }} />
      </div>
      <div className="sentiment-bar-labels">
        {positive > 0 && <span className="sbl-pos">{positive} pos</span>}
        {neutral  > 0 && <span className="sbl-neu">{neutral} neu</span>}
        {negative > 0 && <span className="sbl-neg">{negative} neg</span>}
        <span className={`sbl-composite tag tag-${cls}`} style={{ marginLeft: 'auto' }}>
          {composite_label} ({composite_score > 0 ? '+' : ''}{composite_score?.toFixed(2)})
        </span>
      </div>
    </div>
  );
}

/* ── main component ────────────────────────────────────────────────────────── */
export default function NewsFeed({ news, announcements, sentiment }) {
  const [tab, setTab] = useState('news');

  const hasAnn = announcements && announcements.length > 0;
  const hasNews = news && news.length > 0;

  if (!hasNews && !hasAnn) {
    return (
      <div className="card">
        <div className="card-header"><span className="card-title">Latest News</span></div>
        <div className="card-body" style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '30px 0' }}>
          No news available
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-header">
        <div className="news-tabs">
          <button
            className={`news-tab ${tab === 'news' ? 'news-tab-active' : ''}`}
            onClick={() => setTab('news')}
          >
            News {hasNews && <span className="tab-count">{news.length}</span>}
          </button>
          <button
            className={`news-tab ${tab === 'bse' ? 'news-tab-active' : ''}`}
            onClick={() => setTab('bse')}
            disabled={!hasAnn}
          >
            BSE Filings {hasAnn && <span className="tab-count">{announcements.length}</span>}
            {!hasAnn && <span className="tab-count">–</span>}
          </button>
        </div>
        {sentiment && tab === 'news' && (
          <span className="news-count">
            {sentiment.red_flags > 0 && <span className="rf-count">🚩 {sentiment.red_flags}</span>}
          </span>
        )}
      </div>

      {sentiment && <SentimentBar sentiment={sentiment} />}

      <div className="news-list">
        {tab === 'news' && (hasNews
          ? news.map((item, i) => <NewsItem key={i} item={item} />)
          : <div className="news-empty">No news items</div>
        )}
        {tab === 'bse' && (hasAnn
          ? announcements.map((item, i) => <AnnItem key={i} item={item} />)
          : <div className="news-empty">No BSE filings — BSE API may be unavailable</div>
        )}
      </div>
    </div>
  );
}
