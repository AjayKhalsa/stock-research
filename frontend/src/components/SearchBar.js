import React, { useState, useRef, useEffect } from 'react';
import { searchInstruments } from '../api';
import './SearchBar.css';

export default function SearchBar({ onSelect }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const timer = useRef(null);

  useEffect(() => {
    const handleClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const handleChange = (e) => {
    const val = e.target.value;
    setQuery(val);
    clearTimeout(timer.current);
    if (val.length < 1) { setResults([]); setOpen(false); return; }
    timer.current = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await searchInstruments(val);
        setResults(data || []);
        setOpen(true);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
  };

  const handleSelect = (item) => {
    setQuery('');
    setOpen(false);
    setResults([]);
    onSelect(item.symbol, item.exchange || 'NSE');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && query.trim()) {
      setOpen(false);
      onSelect(query.trim().toUpperCase(), 'NSE');
      setQuery('');
    }
  };

  return (
    <div className="search-wrapper" ref={ref}>
      <div className="search-input-wrap">
        <span className="search-icon">🔍</span>
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
