const SYMBOL_HEADERS = new Set([
  'symbol', 'ticker', 'ticker symbol', 'nse symbol', 'nse code', 'tradingsymbol',
]);

const IGNORED_CELLS = new Set([
  'sr', 'sr.', 's.no', 'stock name', 'company', 'company name', 'links', 'link',
  'price', 'volume', '% chg', 'change', 'change %', 'market cap',
]);

function parseCsvRows(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === ',' && !quoted) {
      row.push(cell.trim());
      cell = '';
    } else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && text[i + 1] === '\n') i += 1;
      row.push(cell.trim());
      if (row.some(Boolean)) rows.push(row);
      row = [];
      cell = '';
    } else {
      cell += char;
    }
  }
  row.push(cell.trim());
  if (row.some(Boolean)) rows.push(row);
  return rows;
}

function cleanSymbol(value) {
  let token = String(value || '').replace(/^\uFEFF/, '').trim();
  if (!token || /^https?:\/\//i.test(token)) return null;

  // Chartink and broker exports commonly include NSE:SYMBOL or SYMBOL.NS.
  token = token.replace(/^NSE\s*:/i, '').replace(/\.NS$/i, '').trim().toUpperCase();
  if (!/[A-Z]/.test(token) || !/^[A-Z0-9&.-]{1,30}$/.test(token)) return null;
  if (IGNORED_CELLS.has(token.toLowerCase())) return null;
  return token;
}

export function parseScreenInput(text) {
  const raw = String(text || '').replace(/^\uFEFF/, '').trim();
  if (!raw) return { tokens: [], source: 'text' };

  const rows = parseCsvRows(raw);
  const headerRowIndex = rows.findIndex(row => row.some(cell =>
    SYMBOL_HEADERS.has(cell.trim().toLowerCase())
  ));

  if (headerRowIndex >= 0) {
    const header = rows[headerRowIndex].map(cell => cell.trim().toLowerCase());
    const symbolIndex = header.findIndex(cell => SYMBOL_HEADERS.has(cell));
    const symbols = rows.slice(headerRowIndex + 1)
      .map(row => cleanSymbol(row[symbolIndex]))
      .filter(Boolean);
    return { tokens: [...new Set(symbols)], source: 'chartink' };
  }

  const tokens = [];
  for (const segment of raw.split(/[,;\n\r\t]+/)) {
    const value = segment.trim().replace(/\s+/g, ' ');
    if (!value || IGNORED_CELLS.has(value.toLowerCase())) continue;
    const symbol = cleanSymbol(value);
    if (symbol) {
      tokens.push(symbol);
    } else if (!/^[-+]?\d[\d,.% ]*$/.test(value) && !/^https?:\/\//i.test(value)) {
      // Keep company names intact so the backend resolver can map them.
      tokens.push(value);
    }
  }
  return { tokens: [...new Set(tokens)], source: 'text' };
}

export function symbolsFromRows(rows) {
  return [...new Set((rows || []).map(row => cleanSymbol(row?.symbol)).filter(Boolean))];
}

export function isTickerOnlyInput(text) {
  const segments = String(text || '')
    .replace(/^\uFEFF/, '')
    .split(/[,;\n\r\t]+/)
    .map(value => value.trim())
    .filter(Boolean);

  if (!segments.length) return false;
  return segments.every(value => {
    const symbol = cleanSymbol(value);
    if (!symbol) return false;
    // A single title-cased word such as "Infosys" may be a company name.
    // Uppercase ticker lists (including NSE:TCS / INFY.NS) are safe to send
    // directly to the screen stream without a separate resolver round trip.
    return value === value.toUpperCase();
  });
}
