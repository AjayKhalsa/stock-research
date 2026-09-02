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
import paper_test_service  # noqa: E402
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
        async def histories(instruments, days=450):
            return {
                instrument: [{"close": 100.0, "symbol": instrument.split(":", 1)[-1]}] * 30
                for instrument in instruments
            }

        def row(symbol, fundamentals, candles):
            self.assertEqual(fundamentals, {})
            return {"symbol": symbol, "score": 50, "candles": len(candles)}

        fundamentals = AsyncMock()
        with patch("routers.screener.price.get_historical_multiple", side_effect=histories), \
                patch("routers.screener.price.get_historical", new=AsyncMock()) as single_history, \
                patch("routers.screener.data_cache.get_fundamentals", fundamentals), \
                patch("routers.screener._build_row", side_effect=row), \
                patch(
                    "routers.screener.swing_engine.cross_sectional_rank",
                    side_effect=lambda rows: sorted(rows, key=lambda item: item["symbol"]),
                ):
            ranked = asyncio.run(screener_router._fetch_and_rank(["TCS", "INFY"], concurrency=2))

        self.assertEqual([item["symbol"] for item in ranked], ["INFY", "TCS"])
        fundamentals.assert_not_called()
        single_history.assert_not_called()

    def test_all_nse_job_uses_official_universe_and_persists_ranked_screen(self):
        universe = [
            {"symbol": "TCS", "name": "Tata Consultancy Services"},
            {"symbol": "INFY", "name": "Infosys"},
            {"symbol": "TCS", "name": "Duplicate"},
        ]
        ranked = [
            {"symbol": "INFY", "rank": 1},
            {"symbol": "TCS", "rank": 2},
        ]
        with patch(
            "routers.screener.symbol_resolver.get_nse_equity_universe",
            new=AsyncMock(return_value=universe),
        ), patch(
            "routers.screener._fetch_and_rank",
            new=AsyncMock(return_value=ranked),
        ) as rank_mock:
            asyncio.run(screener_router._run_auto_screen())

        rank_mock.assert_awaited_once_with(
            ["TCS", "INFY"],
            concurrency=screener_router.AUTO_SCREEN_FETCH_CONCURRENCY,
            track_status=True,
        )
        saved = next(
            item for item in db.screens_all()
            if item["name"] == screener_router.AUTO_SCREEN_NAME
        )
        record = db.screen_get(saved["id"])
        self.assertEqual(record["tickers"], ["INFY", "TCS"])
        self.assertEqual(record["ranked_data"], ranked)

    def test_manual_nse_scan_starts_in_background(self):
        with patch.object(
            screener_router, "_run_auto_screen", new=AsyncMock()
        ) as run_mock:
            response = self.client.post("/api/nse/fetch")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["screen_name"], "All NSE Daily Scan")
        run_mock.assert_awaited_once_with()

    def test_extracts_atlas_query_from_public_chartink_markup(self):
        clause = "( {cash} ( latest close > latest sma( latest close , 20 ) ) )"
        payload = html.escape(json.dumps({"atlas_query": clause}), quote=True)
        markup = f'<html><scanner :scan-json="{payload}"></scanner></html>'
        soup = BeautifulSoup(markup, "lxml")

        self.assertEqual(_extract_scan_clause(markup, soup), clause)

    def test_unavailable_postgres_fails_closed_by_default(self):
        original_pg = db._PG
        original_reason = db._PG_FALLBACK_REASON
        original_allow = db._ALLOW_EPHEMERAL_FALLBACK
        try:
            db._PG = True
            db._PG_FALLBACK_REASON = None
            db._ALLOW_EPHEMERAL_FALLBACK = False
            with patch.object(db, "init", side_effect=RuntimeError("database unavailable")):
                with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                    db._initialize_with_fallback()
            self.assertTrue(db._PG)
            self.assertIn("database unavailable", db._PG_FALLBACK_REASON)
        finally:
            db._PG = original_pg
            db._PG_FALLBACK_REASON = original_reason
            db._ALLOW_EPHEMERAL_FALLBACK = original_allow

    def test_ephemeral_database_fallback_requires_explicit_opt_in(self):
        original_pg = db._PG
        original_reason = db._PG_FALLBACK_REASON
        original_allow = db._ALLOW_EPHEMERAL_FALLBACK
        try:
            db._PG = True
            db._PG_FALLBACK_REASON = None
            db._ALLOW_EPHEMERAL_FALLBACK = True
            with patch.object(db, "init", side_effect=[RuntimeError("database unavailable"), None]):
                db._initialize_with_fallback()
            self.assertFalse(db._PG)
            self.assertIn("database unavailable", db._PG_FALLBACK_REASON)
        finally:
            db._PG = original_pg
            db._PG_FALLBACK_REASON = original_reason
            db._ALLOW_EPHEMERAL_FALLBACK = original_allow

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

    def test_watchlist_retains_user_note_and_point_in_time_metadata(self):
        created = self.client.post("/api/watchlist", json={
            "symbol": "HDFCBANK", "name": "HDFC Bank",
            "note": "Wait for a clean close above resistance",
            "snapshot_id": "snapshot-watch-1",
        })
        self.assertEqual(created.status_code, 200)
        row = next(item for item in created.json() if item["symbol"] == "HDFCBANK")
        self.assertEqual(row["added_snapshot_id"], "snapshot-watch-1")
        self.assertEqual(row["note"], "Wait for a clean close above resistance")

        updated = self.client.patch("/api/watchlist/HDFCBANK", json={
            "note": "Only act inside the planned entry zone",
        })
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["note"], "Only act inside the planned entry zone")
        self.client.delete("/api/watchlist/HDFCBANK")

    def test_paper_trade_snapshot_combines_stats_and_recent_log(self):
        created = self.client.post("/api/paper-trades", json={
            "symbol": "tcs",
            "entry_price": 100,
            "stop_loss": 95,
            "target_t1": 107.5,
            "target_t2": 112.5,
            "score": 81,
            "setup_type": "Breakout",
        })
        self.assertEqual(created.status_code, 200)

        response = self.client.get("/api/paper-trades/snapshot")
        self.assertEqual(response.status_code, 200)
        snapshot = response.json()
        self.assertGreaterEqual(snapshot["stats"]["total_trades"], 1)
        self.assertGreaterEqual(snapshot["stats"]["active_count"], 1)
        self.assertEqual(snapshot["trades"][0]["symbol"], "TCS")
        self.assertIn("Server-Timing", response.headers)

    def test_paper_test_arms_then_uses_daily_entry_and_actual_structural_r(self):
        created = self.client.post("/api/paper-trades", json={
            "symbol": "reliance", "entry_price": 101,
            "entry_low": 100, "entry_high": 102, "stop_loss": 95,
            "target_t1": 110, "target_t2": 118,
            "signal_date": "2026-01-01", "snapshot_id": "snap-1",
            "model_version": "swing-test", "action_at_add": "WAIT_FOR_ENTRY",
            "invalidation": "Close below 95",
        })
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["status"], "ARMED")
        history = [
            {"date": "2026-01-02", "open": 99, "high": 101, "low": 99, "close": 100},
            {"date": "2026-01-05", "open": 104, "high": 111, "low": 103, "close": 109},
        ]
        with patch.object(paper_test_service.price, "get_historical",
                          new=AsyncMock(return_value=history)):
            evaluated = self.client.post("/api/paper-trades/evaluate")
        self.assertEqual(evaluated.status_code, 200)
        result = evaluated.json()["results"][0]
        self.assertEqual(result["status"], "WIN_T1")
        self.assertEqual(result["pnl_r"], 1.14)
        self.assertEqual(result["trade"]["model_version"], "swing-test")
        self.assertEqual(result["trade"]["outcome_date"], "2026-01-05")
        self.assertEqual(result["trade"]["exit_price"], 110.0)
        self.assertEqual(result["trade"]["mfe_r"], 1.29)
        self.assertEqual(result["trade"]["mae_r"], 0.0)
        stats = self.client.get("/api/paper-trades/stats").json()
        self.assertGreaterEqual(stats["resolved_count"], 1)
        self.assertIn("expectancy_r", stats)
        self.assertIn("profit_factor", stats)

    def test_paper_test_rejects_invalid_geometry(self):
        response = self.client.post("/api/paper-trades", json={
            "symbol": "BADPLAN", "entry_price": 100, "entry_low": 99,
            "entry_high": 101, "stop_loss": 100, "target_t1": 110,
        })
        self.assertEqual(response.status_code, 400)

    def test_paper_test_excludes_ambiguous_entry_bar(self):
        trade = self.client.post("/api/paper-trades", json={
            "symbol": "AMBIG", "entry_price": 101, "entry_low": 100,
            "entry_high": 102, "stop_loss": 95, "target_t1": 110,
            "signal_date": "2026-02-01",
        }).json()
        result = paper_test_service._evaluate_trade(trade, [{
            "date": "2026-02-02", "high": 111, "low": 94, "close": 104,
        }])
        self.assertEqual(result["status"], "AMBIGUOUS")
        self.assertEqual(result["trade"]["pnl_r"], 0.0)

    def test_paper_test_uses_stop_first_on_later_conflict_bar(self):
        trade = self.client.post("/api/paper-trades", json={
            "symbol": "CONFLICT", "entry_price": 101, "entry_low": 100,
            "entry_high": 102, "stop_loss": 95, "target_t1": 110,
            "signal_date": "2026-03-01",
        }).json()
        result = paper_test_service._evaluate_trade(trade, [
            {"date": "2026-03-02", "high": 101, "low": 99, "close": 100},
            {"date": "2026-03-03", "high": 111, "low": 94, "close": 107},
        ])
        self.assertEqual(result["status"], "STOPPED_OUT")
        self.assertEqual(result["trade"]["pnl_r"], -1.0)
        self.assertEqual(result["trade"]["mae_r"], 1.0)

    def test_paper_test_expires_an_untouched_entry_after_ten_sessions(self):
        trade = self.client.post("/api/paper-trades", json={
            "symbol": "UNTOUCHED", "entry_price": 101, "entry_low": 100,
            "entry_high": 102, "stop_loss": 95, "target_t1": 110,
            "signal_date": "2026-04-01",
        }).json()
        candles = [{"date": f"2026-04-{day:02d}", "high": 106, "low": 103,
                    "close": 104} for day in range(2, 12)]
        result = paper_test_service._evaluate_trade(trade, candles)
        self.assertEqual(result["status"], "EXPIRED")
        self.assertEqual(result["trade"]["armed_sessions"], 10)

    def test_auto_screen_requires_bearer_secret_and_starts_once(self):
        with patch.object(screener_router.config, "CRON_SECRET_KEY", "test-secret"), \
                patch.object(screener_router, "_run_auto_screen", new=AsyncMock()) as run_mock:
            denied = self.client.post("/api/auto-screen")
            self.assertEqual(denied.status_code, 403)

            started = self.client.post(
                "/api/auto-screen",
                headers={"Authorization": "Bearer test-secret"},
            )
            self.assertEqual(started.status_code, 200)
            self.assertEqual(started.json()["status"], "started")
            self.assertEqual(started.json()["screen_name"], "All NSE Daily Scan")
            run_mock.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
