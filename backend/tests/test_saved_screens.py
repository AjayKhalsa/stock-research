import asyncio
import html
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bs4 import BeautifulSoup


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_temp_data = tempfile.TemporaryDirectory()
os.environ["STOCKLENS_DATA_DIR"] = _temp_data.name

from fastapi.testclient import TestClient  # noqa: E402
from chartink_scraper import _extract_scan_clause  # noqa: E402
from main import app  # noqa: E402
import db  # noqa: E402
from routers import screener as screener_router  # noqa: E402


class SavedScreensApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        _temp_data.cleanup()

    def test_saved_screen_crud_and_validation(self):
        created = self.client.post("/api/screens", json={
            "name": "  Quality   Leaders  ",
            "tickers": ["tcs", "INFY", "TCS"],
            "ranked_data": [
                {"symbol": "TCS", "rank": 1},
                {"symbol": "INFY", "rank": 2},
            ],
        })
        self.assertEqual(created.status_code, 200)
        record = created.json()
        self.assertEqual(record["name"], "Quality Leaders")
        self.assertEqual(record["tickers"], ["TCS", "INFY"])

        listed = self.client.get("/api/screens")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["count"], 2)
        self.assertNotIn("tickers", listed.json()[0])

        loaded = self.client.get(f"/api/screens/{record['id']}")
        self.assertEqual(loaded.json()["tickers"], ["TCS", "INFY"])
        self.assertEqual([row["symbol"] for row in loaded.json()["ranked_data"]], ["TCS", "INFY"])

        invalid = self.client.post("/api/screens", json={"name": "One", "tickers": ["TCS"]})
        self.assertEqual(invalid.status_code, 422)

        deleted = self.client.delete(f"/api/screens/{record['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get(f"/api/screens/{record['id']}").status_code, 404)

    def test_search_merges_local_and_remote_results(self):
        local = [{"symbol": "TCS", "name": "Tata Consultancy", "exchange": "NSE"}]
        remote = [
            {"symbol": "TCS", "name": "Duplicate", "exchange": "NSE"},
            {"symbol": "TATAMOTORS", "name": "Tata Motors", "exchange": "NSE"},
        ]
        with patch("routers.stocks.symbol_resolver.search_local", new=AsyncMock(return_value=local)), \
                patch("routers.stocks.price.search_instruments", new=AsyncMock(return_value=remote)):
            response = self.client.get("/api/search", params={"q": "tata"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["symbol"] for item in response.json()], ["TCS", "TATAMOTORS"])

    def test_fetch_chartink_matches_persists_refreshed_universe(self):
        url = "https://chartink.com/screener/copy-general-scanner-simply-above-mas-3"
        ranked = [
            {"symbol": "INFY", "rank": 1, "score": 82.0},
            {"symbol": "TCS", "rank": 2, "score": 78.0},
        ]
        with patch(
            "routers.screener.chartink_scraper.fetch_screener_tickers",
            new=AsyncMock(return_value=["TCS", "INFY", "TCS"]),
        ), patch(
            "routers.screener._fetch_and_rank",
            new=AsyncMock(return_value=ranked),
        ) as rank_mock:
            response = self.client.post("/api/chartink/fetch", json={"url": url})

        self.assertEqual(response.status_code, 200)
        record = response.json()
        self.assertEqual(record["name"], "Daily Chartink Auto-Run")
        self.assertEqual(record["tickers"], ["INFY", "TCS"])
        self.assertEqual(record["ranked_data"], ranked)
        self.assertEqual(record["count"], 2)
        rank_mock.assert_awaited_once_with(
            ["TCS", "INFY"],
            concurrency=screener_router.AUTO_SCREEN_FETCH_CONCURRENCY,
        )

        invalid = self.client.post(
            "/api/chartink/fetch",
            json={"url": "https://chartink.com.example.com/screener/not-chartink"},
        )
        self.assertEqual(invalid.status_code, 400)

    def test_chartink_ranker_is_price_first_and_skips_bulk_fundamentals(self):
        async def history(instrument, days=450):
            symbol = instrument.split(":", 1)[-1]
            return [{"close": 100.0, "symbol": symbol}] * 30

        def row(symbol, fundamentals, candles):
            self.assertEqual(fundamentals, {})
            return {"symbol": symbol, "score": 50, "candles": len(candles)}

        fundamentals = AsyncMock()
        with patch("routers.screener.price.get_historical", side_effect=history), \
                patch("routers.screener.data_cache.get_fundamentals", fundamentals), \
                patch("routers.screener._build_row", side_effect=row), \
                patch(
                    "routers.screener.swing_engine.cross_sectional_rank",
                    side_effect=lambda rows: sorted(rows, key=lambda item: item["symbol"]),
                ):
            ranked = asyncio.run(screener_router._fetch_and_rank(["TCS", "INFY"], concurrency=2))

        self.assertEqual([item["symbol"] for item in ranked], ["INFY", "TCS"])
        fundamentals.assert_not_called()

    def test_extracts_atlas_query_from_public_chartink_markup(self):
        clause = "( {cash} ( latest close > latest sma( latest close , 20 ) ) )"
        payload = html.escape(json.dumps({"atlas_query": clause}), quote=True)
        markup = f'<html><scanner :scan-json="{payload}"></scanner></html>'
        soup = BeautifulSoup(markup, "lxml")

        self.assertEqual(_extract_scan_clause(markup, soup), clause)

    def test_unavailable_postgres_falls_back_without_hanging_api_startup(self):
        original_pg = db._PG
        original_reason = db._PG_FALLBACK_REASON
        try:
            db._PG = True
            db._PG_FALLBACK_REASON = None
            with patch.object(db, "init", side_effect=[RuntimeError("database unavailable"), None]):
                db._initialize_with_fallback()
            self.assertFalse(db._PG)
            self.assertIn("database unavailable", db._PG_FALLBACK_REASON)
        finally:
            db._PG = original_pg
            db._PG_FALLBACK_REASON = original_reason

    def test_screen_stream_emits_each_symbol_as_it_completes(self):
        async def fundamentals(symbol):
            await asyncio.sleep(0.025 if symbol == "SLOW" else 0.001)
            return {}, {"source": "test"}

        async def history(_instrument, days=450):
            return [{"close": 100.0}] * 30

        def row(symbol, _fundamentals, _history):
            return {"symbol": symbol, "score": 50}

        with patch("routers.screener.data_cache.get_fundamentals", side_effect=fundamentals), \
                patch("routers.screener.price.get_historical", side_effect=history), \
                patch("routers.screener._build_row", side_effect=row), \
                patch("routers.screener.swing_engine.cross_sectional_rank", side_effect=lambda rows: rows):
            response = self.client.get(
                "/api/screen-stream", params={"symbols": "SLOW,FAST"}
            )

        self.assertEqual(response.status_code, 200)
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        batches = [event for event in events if event.get("type") == "batch"]
        self.assertEqual([event["symbol"] for event in batches], ["FAST", "SLOW"])
        self.assertEqual([event["done"] for event in batches], [1, 2])
        self.assertEqual([event["total"] for event in batches], [2, 2])

    def test_cors_accepts_local_preview_ports(self):
        response = self.client.options(
            "/api/health",
            headers={
                "Origin": "http://127.0.0.1:3001",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://127.0.0.1:3001",
        )


if __name__ == "__main__":
    unittest.main()
