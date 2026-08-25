import React, { useState, useRef, useEffect } from 'react';
import { searchInstruments, resolveSymbols } from '../api';
import './SearchBar.css';

export default function SearchBar({ onSelect }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const timer = useRef(null);
  const requestSeq = useRef(0);

  useEffect(() => {
    const handleClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handleClick);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      clearTimeout(timer.current);
      requestSeq.current += 1;
    };
  }, []);

  const handleChange = (e) => {
    const val = e.target.value;
    setQuery(val);
    clearTimeout(timer.current);
    const seq = ++requestSeq.current;
    if (val.trim().length < 1) { setResults([]); setOpen(false); setLoading(false); return; }
    timer.current = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await searchInstruments(val.trim());
        if (requestSeq.current !== seq) return;
        setResults(data || []);
        setOpen(true);
      } catch {
        if (requestSeq.current !== seq) return;
        setResults([]);
      } finally {
        if (requestSeq.current === seq) setLoading(false);
      }
    }, 300);
  };

  const handleSelect = (item) => {
    clearTimeout(timer.current);
    requestSeq.current += 1;
    setQuery('');
    setOpen(false);
    setResults([]);
    setLoading(false);
    onSelect(item.symbol, item.exchange || 'NSE');
  };

  const handleKeyDown = async (e) => {
    if (e.key === 'Enter' && query.trim()) {
      e.preventDefault();
      if (results.length > 0) {
        handleSelect(results[0]);
        return;
      }
      clearTimeout(timer.current);
      const seq = ++requestSeq.current;
      const raw = query.trim();
      setOpen(false);
      if (/^[A-Za-z0-9&.-]+$/.test(raw)) {
        onSelect(raw.toUpperCase(), 'NSE');
        setQuery('');
        return;
      }
      setLoading(true);
      try {
        const [match] = await resolveSymbols([raw]);
        if (requestSeq.current !== seq) return;
        if (match?.symbol) handleSelect(match);
        else setOpen(true);
      } catch {
        if (requestSeq.current === seq) setOpen(true);
      } finally {
        if (requestSeq.current === seq) setLoading(false);
      }
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  return (
    <div className="search-wrapper" ref={ref}>
      <div className="search-input-wrap">
        <span className="search-icon" aria-hidden="true">
          <svg viewBox="0 0 20 20"><circle cx="8.5" cy="8.5" r="5.5" /><path d="m13 13 4 4" /></svg>
        </span>
        <input
          className="search-input"
          placeholder="Search stock by name or symbol (e.g. RELIANCE, TCS)..."
          value={query}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => results.length > 0 && setOpen(true)}
          autoComplete="off"
          spellCheck={false}
        />
        {loading && <span className="search-spinner" />}
      </div>

      {open && results.length > 0 && (
        <ul className="search-dropdown">
          {results.map((item, i) => (
            <li key={i} className="search-item" onMouseDown={() => handleSelect(item)}>
              <div className="search-item-main">
                <span className="search-symbol">{item.symbol}</span>
                <span className="search-exchange">{item.exchange}</span>
              </div>
              <span className="search-name">{item.name}</span>
            </li>
          ))}
        </ul>
      )}
      {open && results.length === 0 && !loading && query.length > 0 && (
        <ul className="search-dropdown">
          <li className="search-empty">No results — press Enter to search for "{query.toUpperCase()}"</li>
        </ul>
      )}
    </div>
  );
}
