"""
Kite Bridge - A local FastAPI server that wraps Kite MCP tool calls
and exposes them as REST endpoints for the main backend to consume.
Run this on port 8001.
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import httpx
import asyncio
import json
import os
import sys
from datetime import datetime

# Add parent dir so we can import kite client if needed
app = FastAPI(title="Kite Bridge", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Kite Connect API base - we call it via subprocess/MCP internally
# This bridge uses direct Kite Connect REST API using env-provided credentials

KITE_BASE = "https://api.kite.trade"
ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "")
API_KEY = os.environ.get("KITE_API_KEY", "")


def get_headers():
    return {
        "X-Kite-Version": "3",
        "Authorization": f"token {API_KEY}:{ACCESS_TOKEN}",
    }


@app.get("/instruments/search")
async def search_instruments(q: str, limit: int = 15):
    """Search instruments by name or symbol"""
    # Load instruments from Kite and filter locally
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{KITE_BASE}/instruments",
                headers=get_headers()
            )
            if resp.status_code == 200:
                lines = resp.text.strip().split("\n")
                results = []
                q_lower = q.lower()
                header = lines[0].split(",")
                for line in lines[1:]:
                    parts = line.split(",")
                    if len(parts) < 9:
                        continue
                    tradingsymbol = parts[2].strip('"')
                    name = parts[8].strip('"') if len(parts) > 8 else ""
                    exchange = parts[11].strip('"') if len(parts) > 11 else parts[1].strip('"')
                    instrument_type = parts[9].strip('"') if len(parts) > 9 else ""
                    # Only NSE/BSE equity
                    if exchange not in ("NSE", "BSE"):
                        continue
                    if instrument_type not in ("EQ", ""):
                        continue
                    if q_lower in tradingsymbol.lower() or q_lower in name.lower():
                        results.append({
                            "symbol": tradingsymbol,
                            "name": name,
                            "exchange": exchange,
                            "instrument_type": instrument_type,
                        })
                    if len(results) >= limit:
                        break
                return results
    except Exception as e:
        print(f"Search error: {e}")
    return []


@app.get("/ltp")
async def get_ltp(instruments: str = Query(...)):
    """Get last traded price. instruments = 'NSE:INFY' or comma-separated"""
    inst_list = [i.strip() for i in instruments.split(",")]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{KITE_BASE}/quote/ltp",
                params={"i": inst_list},
                headers=get_headers()
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    raw = data.get("data", {})
                    # Return first instrument's data for single queries
                    if len(inst_list) == 1:
                        key = inst_list[0]
                        item = raw.get(key, {})
                        return {
                            "instrument": key,
                            "last_price": item.get("last_price"),
                            "instrument_token": item.get("instrument_token"),
                        }
                    # Return all for multiple
                    return {k: {"last_price": v.get("last_price")} for k, v in raw.items()}
    except Exception as e:
        print(f"LTP error: {e}")
    return {}


@app.get("/ohlc")
async def get_ohlc(instruments: str = Query(...)):
    """Get OHLC data"""
    inst_list = [i.strip() for i in instruments.split(",")]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{KITE_BASE}/quote/ohlc",
                params={"i": inst_list},
                headers=get_headers()
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    raw = data.get("data", {})
                    if len(inst_list) == 1:
                        key = inst_list[0]
                        item = raw.get(key, {})
                        ohlc = item.get("ohlc", {})
                        last_price = item.get("last_price", 0)
                        prev_close = ohlc.get("close", last_price)
                        day_change = last_price - prev_close if prev_close else 0
                        day_change_pct = (day_change / prev_close * 100) if prev_close else 0
                        return {
                            "instrument": key,
                            "last_price": last_price,
                            "open": ohlc.get("open"),
                            "high": ohlc.get("high"),
                            "low": ohlc.get("low"),
                            "close": ohlc.get("close"),
                            "day_change": round(day_change, 2),
                            "day_change_pct": round(day_change_pct, 2),
                        }
                    return raw
    except Exception as e:
        print(f"OHLC error: {e}")
    return {}


@app.get("/historical")
async def get_historical(
    instrument: str,
    interval: str = "day",
    from_date: str = Query(alias="from", default=None),
    to_date: str = Query(alias="to", default=None)
):
    """Get historical candle data"""
    if not from_date:
        from_date = (datetime.now().replace(hour=0, minute=0, second=0)).strftime("%Y-%m-%d %H:%M:%S")
    if not to_date:
        to_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Need instrument token - first get it
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            ltp_resp = await client.get(
                f"{KITE_BASE}/quote/ltp",
                params={"i": instrument},
                headers=get_headers()
            )
            if ltp_resp.status_code != 200:
                return []
            ltp_data = ltp_resp.json()
            if ltp_data.get("status") != "success":
                return []
            token = ltp_data["data"].get(instrument, {}).get("instrument_token")
            if not token:
                return []

            hist_resp = await client.get(
                f"{KITE_BASE}/instruments/historical/{token}/{interval}",
                params={"from": from_date, "to": to_date},
                headers=get_headers()
            )
            if hist_resp.status_code == 200:
                hist_data = hist_resp.json()
                if hist_data.get("status") == "success":
                    candles = hist_data.get("data", {}).get("candles", [])
                    return [
                        {
                            "date": c[0],
                            "open": c[1],
                            "high": c[2],
                            "low": c[3],
                            "close": c[4],
                            "volume": c[5],
                        }
                        for c in candles
                    ]
    except Exception as e:
        print(f"Historical error: {e}")
    return []


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("kite_bridge:app", host="0.0.0.0", port=8001, reload=False)
