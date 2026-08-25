import { isTickerOnlyInput, parseScreenInput, symbolsFromRows } from './screenUtils';

test('extracts only symbols from a Chartink CSV export', () => {
  const csv = [
    'Sr.,Stock Name,Symbol,Links,% Chg,Price,Volume',
    '1,"Reliance Industries Ltd",RELIANCE,https://chartink.com/stocks/reliance.html,1.25,1412.5,123456',
    '2,"Mahindra & Mahindra",M&M,https://chartink.com/stocks/m-m.html,-0.4,2980,98765',
  ].join('\n');

  expect(parseScreenInput(csv)).toEqual({
    tokens: ['RELIANCE', 'M&M'],
    source: 'chartink',
  });
});

test('normalizes NSE and Yahoo symbol formats without splitting company names', () => {
  expect(parseScreenInput('NSE:TCS, INFY.NS\nHDFC Bank Limited').tokens).toEqual([
    'TCS', 'INFY', 'HDFC Bank Limited',
  ]);
});

test('derives a deduplicated saved universe from rendered rows', () => {
  expect(symbolsFromRows([
    { symbol: 'tcs' }, { symbol: 'TCS' }, { symbol: 'INFY.NS' }, { symbol: null },
  ])).toEqual(['TCS', 'INFY']);
});

test('recognizes explicit ticker lists that can skip company-name resolution', () => {
  expect(isTickerOnlyInput('RELIANCE, TCS, M&M, NSE:INFY, HDFCBANK.NS')).toBe(true);
  expect(isTickerOnlyInput('Infosys, TCS')).toBe(false);
  expect(isTickerOnlyInput('HDFC Bank Limited\nTCS')).toBe(false);
});
