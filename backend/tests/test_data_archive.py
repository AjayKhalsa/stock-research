import os
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("STOCKLENS_DATA_DIR", tempfile.mkdtemp())

import db  # noqa: E402


class ImmutableArchiveTests(unittest.TestCase):
    SYMBOL = "ARCHIVEQA"
    ISIN = "INE0ARCHIVE01"

    def test_archives_identity_prices_features_financials_and_events_immutably(self):
        before = db.data_archive_status()["counts"]
        universe = [{
            "symbol": self.SYMBOL, "name": "Archive Quality Limited",
            "isin": self.ISIN, "listing_date": "2024-01-01",
        }]
        db.archive_security_master(universe, observed_at=100)
        db.archive_security_master(universe, observed_at=101)

        raw = {self.SYMBOL: {
            "open": 100, "high": 105, "low": 99, "close": 104,
            "volume": 1000, "delivery_volume": 600, "turnover": 104000,
        }}
        db.archive_raw_market_day(
            universe, raw, trading_date="2026-09-04", observed_at=200,
        )
        db.archive_raw_market_day(
            universe, raw, trading_date="2026-09-04", observed_at=201,
        )
        db.archive_raw_market_day(
            universe, {self.SYMBOL: {**raw[self.SYMBOL], "close": 103}},
            trading_date="2026-09-04", observed_at=202,
        )

        history = {self.SYMBOL: [
            {"date": "2026-09-03", "open": 49, "high": 51, "low": 48,
             "close": 50, "raw_close": 100, "adjustment_factor": .5,
             "volume": 900},
            {"date": "2026-09-04", "open": 100, "high": 105, "low": 99,
             "close": 104, "raw_close": 104, "adjustment_factor": 1,
             "volume": 1000},
        ]}
        kwargs = {"observed_at": 300, "isin_by_symbol": {self.SYMBOL: self.ISIN}}
        db.archive_adjusted_histories(history, **kwargs)
        db.archive_adjusted_histories(history, **kwargs)

        feature = {"symbol": self.SYMBOL, "score": 70, "eligible": True}
        feature_kwargs = {
            "feature_date": "2026-09-04", "feature_version": "qa-v1",
            "feature_scope": "full", "observed_at": 400,
            "isin_by_symbol": {self.SYMBOL: self.ISIN},
        }
        db.archive_feature_snapshots([feature], **feature_kwargs)
        db.archive_feature_snapshots([feature], **feature_kwargs)
        db.archive_feature_snapshots([{**feature, "score": 71}], **feature_kwargs)
        db.archive_feature_snapshots(
            [feature], feature_date="2026-09-04", feature_version="preliminary-v1",
            feature_scope="universe", observed_at=400,
            isin_by_symbol={self.SYMBOL: self.ISIN},
        )

        financial = [{
            "symbol": self.SYMBOL, "isin": self.ISIN, "observed_at": 500,
            "origin": "exchange filing",
            "payload": {
                "quarterly_results": [{"quarter": "2026-Q1", "revenue": 100,
                                       "net_profit": 12, "filing_date": "2026-08-01"}],
                "annual_bs": [{"year": "2026", "debt": 20, "cash": 15}],
                "roe": 18, "roce": 20,
                "earnings_date": "2026-11-01",
                "events": [{"event_type": "order_win", "event_date": "2026-08-15",
                            "severity": "positive", "description": "Test order"}],
            },
        }]
        db.archive_financial_payloads(financial)
        db.archive_financial_payloads(financial)

        audit = db.run_data_archive_audit(expected_date="2026-09-04", persist=True)
        after = db.data_archive_status()
        counts = after["counts"]
        self.assertEqual(counts["securities"] - before["securities"], 1)
        self.assertEqual(counts["market_prices_raw"] - before["market_prices_raw"], 2)
        self.assertEqual(counts["market_prices_adjusted"] - before["market_prices_adjusted"], 2)
        self.assertEqual(counts["corporate_actions"] - before["corporate_actions"], 1)
        self.assertEqual(counts["stock_feature_snapshots"] - before["stock_feature_snapshots"], 3)
        self.assertEqual(counts["financial_reports"] - before["financial_reports"], 3)
        self.assertEqual(counts["company_events"] - before["company_events"], 2)
        self.assertTrue(after["immutable_revisions"])
        self.assertEqual(audit["metrics"]["failures"], 0)
        self.assertEqual(audit["status"], "attention")
        self.assertEqual(after["latest_audit"]["as_of_date"], "2026-09-04")


if __name__ == "__main__":
    unittest.main()
