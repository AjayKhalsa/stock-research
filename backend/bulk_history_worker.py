"""Isolated Yahoo bulk-history worker.

The parent web process owns the timeout and terminates this process if Yahoo
hangs, preventing abandoned network threads from exhausting the API server.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta

import yfinance as yf

from price_service import _df_to_candles


def main(input_path: str, output_path: str) -> None:
    with open(input_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    missing = [(str(raw), str(symbol)) for raw, symbol in payload.get("missing", [])]
    days = int(payload.get("days") or 300)
    symbols = [symbol for _raw, symbol in missing]
    fetched: dict[str, list] = {}
    if symbols:
        end = datetime.now()
        start = end - timedelta(days=days + 15)
        frame = yf.download(
            tickers=" ".join(symbols), start=start, end=end, interval="1d",
            auto_adjust=True, group_by="ticker", threads=8, progress=False,
            timeout=15,
        )
        if frame is not None and not frame.empty:
            for raw, symbol in missing:
                try:
                    if len(symbols) == 1:
                        symbol_frame = frame
                    elif (getattr(frame.columns, "nlevels", 1) > 1
                          and symbol in frame.columns.get_level_values(0)):
                        symbol_frame = frame[symbol]
                    elif (getattr(frame.columns, "nlevels", 1) > 1
                          and symbol in frame.columns.get_level_values(1)):
                        symbol_frame = frame.xs(symbol, axis=1, level=1)
                    else:
                        continue
                    candles = _df_to_candles(symbol_frame)
                    if candles:
                        fetched[raw] = candles
                except Exception:
                    continue
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(fetched, handle, separators=(",", ":"))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: bulk_history_worker.py INPUT_JSON OUTPUT_JSON")
    main(sys.argv[1], sys.argv[2])
