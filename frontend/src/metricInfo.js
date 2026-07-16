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
    'Altman Z″-Score (emerging-market model): bankruptcy-risk score from working capital, retained earnings, EBIT and book equity vs liabilities. Above 2.6 = safe zone, 1.1-2.6 = grey zone, below 1.1 = distress risk within ~2 years. Not meaningful for banks/NBFCs.',
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

  // ── Beta ───────────────────────────────────────────────────────────────────
  beta:
    'Beta vs NIFTY: how much the stock moves per 1% move in the index (1-year daily returns). 1.0 = moves with the market, >1.3 = amplified swings both ways, <0.8 = defensive.',

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

/**
 * Glass-box metric metadata: exact industry term + functional subtitle +
 * two-tier tooltip (TL;DR for the read, The Math for the audit).
 * Nothing is renamed or dumbed down — the formula is always one hover away.
 */
export const GLASS_METRICS = {
  altman: {
    subtitle: 'Bankruptcy & Solvency Risk',
    tldr: 'Predicts the probability of financial distress. A score above 2.6 positions the firm inside the "Safe Zone"; below 1.1 flags distress risk within ~2 years. Uses the emerging-market Z″ model — industry-neutral, but not valid for banks/NBFCs.',
    math: 'Z″ = 6.56·X₁ + 3.26·X₂ + 6.72·X₃ + 1.05·X₄  where X₁ = Working Capital/Total Assets, X₂ = Retained Earnings/TA, X₃ = EBIT/TA, X₄ = Book Value of Equity/Total Liabilities. Zones: >2.6 Safe · 1.1–2.6 Grey · ≤1.1 Distress',
  },
  piotroski: {
    subtitle: 'Operational Efficiency Health',
    tldr: 'A 9-point checklist testing the absolute operational trajectory across profitability, capital-structure liquidity, and operating efficiency. 8-9 = excellent, ≤3 = deteriorating. Click any ✗ badge for the exact data behind the failure.',
    math: 'F = Σ of 9 binary signals: ROA>0, CFO>0, ΔROA↑, CFO/TA>ROA (accruals), Δleverage↓, Δcurrent ratio↑, no dilution, Δgross margin↑, Δasset turnover↑',
  },
  dupont: {
    subtitle: 'ROE Profitability Drivers',
    tldr: 'Deconstructs Return on Equity into three clean variables to show exactly how the business generates its returns — pricing power, asset efficiency, or leverage (the fragile kind).',
    math: 'ROE = Net Profit Margin × Asset Turnover × Financial Leverage = (NI/Sales) × (Sales/TA) × (TA/Equity)',
  },
  rsi: {
    subtitle: 'Momentum Speedometer',
    tldr: 'Measures the velocity and magnitude of recent price shifts. Sustained above 70 flags an Overbought condition where price is running historically hot; below 30 = Oversold.',
    math: 'RSI = 100 − [100 / (1 + RS)]  where RS = avg gain / avg loss over a 14-period Wilder-smoothed lookback',
  },
  beneish: {
    subtitle: 'Earnings Manipulation Screen',
    tldr: 'Statistical forensic test for cooked books. Above −1.78 = the accounting profile resembles known manipulators; treat reported profits with suspicion.',
    math: 'M = −4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI',
  },
};
