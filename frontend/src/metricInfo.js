/**
 * Central dictionary of metric explanations shown in info tooltips.
 * Written for a swing trader, not an accountant — short, practical, plain English.
 */
export const METRIC_INFO = {
  // ── Overview card ──────────────────────────────────────────────────────────
  market_cap:
    'Total value of all the company\'s shares (price × share count). Large caps (>₹50,000 Cr) are stabler; small caps move faster but are riskier.',
  pe_ratio:
    'Price-to-Earnings: how many rupees you pay for ₹1 of annual profit. Lower can mean cheaper — but always compare against the sector average, not in isolation.',
  pb_ratio:
    'Price-to-Book: share price vs the company\'s net asset value per share. Under 1 can signal a bargain (or a business in trouble). Most useful for banks and asset-heavy firms.',
  roe:
    'Return on Equity: profit generated per ₹100 of shareholder money. 15%+ is good, 20%+ is excellent. Consistently high ROE is the hallmark of a quality business.',
  roce:
    'Return on Capital Employed: like ROE but includes debt capital, so it can\'t be juiced by leverage. The best single measure of business quality. 15%+ is good.',
  debt_to_equity:
    'Total borrowings vs shareholder equity. Under 0.5 is comfortable, above 1.5-2 is risky — debt magnifies both gains and crashes. Banks/NBFCs naturally run higher.',
  dividend_yield:
    'Annual dividend as % of the share price. Nice bonus income, but high yield (5%+) sometimes means the market expects trouble ahead.',
  book_value:
    'Net assets per share (what shareholders would theoretically get if the company liquidated today). Compare with price via the P/B ratio.',
  promoter_holding:
    'Percentage of shares owned by the founders/controlling family. High and stable promoter holding = skin in the game. Steady decline is a red flag.',
  promoter_pledge:
    'Percentage of promoter shares pledged as loan collateral. Above ~5-10% is a warning: if the stock falls, lenders can force-sell those shares, accelerating the crash.',

  // ── Quant scores ───────────────────────────────────────────────────────────
  piotroski:
    'Piotroski F-Score (0-9): nine yes/no checks of improving fundamentals — profitability, leverage, and efficiency. 8-9 = excellent, 6-7 = good, below 4 = weak. Stocks scoring high have historically beaten low scorers.',
  altman:
    'Altman Z-Score: bankruptcy-risk model combining working capital, retained earnings, profits, market value and sales. Above 2.99 = safe zone, 1.81-2.99 = grey zone, below 1.81 = distress risk within ~2 years.',
  beneish:
    'Beneish M-Score: detects likely earnings manipulation from 8 accounting ratios. Below -2.22 = clean. Above -1.78 = statistically resembles known manipulators — treat reported profits with suspicion.',
  dupont:
    'DuPont analysis breaks ROE into 3 drivers: profit margin × asset turnover × leverage. It reveals WHERE returns come from — pricing power, efficiency, or just heavy borrowing (the fragile kind).',
  quality_score:
    'Composite 0-100 quality score blending Piotroski (40%), Altman Z (30%) and ROE (30%). A quick single-number read on business quality.',

  // ── Technicals ─────────────────────────────────────────────────────────────
  rsi:
    'Relative Strength Index (14-day): momentum oscillator from 0-100. Above 70 = overbought (pullback risk), below 30 = oversold (bounce candidate). 40-60 = neutral.',
  ma50:
    '50-Day Moving Average: average closing price of the last 50 sessions — the medium-term trend line. Price above it = bullish bias; it often acts as support in uptrends.',
  ma200:
    '200-Day Moving Average: the long-term trend line watched by institutions. Price above = long-term uptrend. The 50 DMA crossing above it ("golden cross") is a classic buy signal.',
  trend:
    'Trend classification from price vs 50 & 200 DMA alignment. Uptrend: price > 50 DMA > 200 DMA. Swing trades work best WITH the trend, not against it.',

  // ── Screener columns ───────────────────────────────────────────────────────
  score:
    'Composite rank score (0-100) vs the other stocks in your list: Momentum 35% + Quality 30% + Value 20% + Low-Risk 15%, from winsorized z-scores. 70+ = top of your list.',
  momentum_z:
    'Momentum vs your list: 3M & 6M returns, 12-1 momentum, closeness to 52-week high, and risk-adjusted return. Positive = stronger price action than the group.',
  quality_z:
    'Quality vs your list: Piotroski, Altman Z, ROE and ROCE combined. Positive = fundamentally stronger than the group.',
  value_z:
    'Value vs your list: earnings yield, inverse P/E, inverse P/B, dividend yield. Positive = cheaper than the group.',
};
