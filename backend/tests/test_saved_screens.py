import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_temp_data = tempfile.TemporaryDirectory()
os.environ["STOCKLENS_DATA_DIR"] = _temp_data.name

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
