#!/usr/bin/env python3
"""Unit tests for the free rebuild: build, paste import, demotion, CLI."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import leads_lib as L
import add_lead


class DemotionTests(unittest.TestCase):
    def test_two_not_there_dates_demotes(self):
        trips = [
            {"lead_id": "a", "store_id": "0275", "mark": "gone", "date": "2026-11-01"},
            {"lead_id": "a", "store_id": "0275", "mark": "gone", "date": "2026-11-08"},
        ]
        self.assertTrue(L.is_demoted(trips))
        self.assertEqual(L.not_there_dates(trips), {"2026-11-01", "2026-11-08"})

    def test_same_day_taps_count_as_one_trip(self):
        trips = [
            {"lead_id": "a", "store_id": "0275", "mark": "gone", "date": "2026-11-01"},
            {"lead_id": "a", "store_id": "6346", "mark": "gone", "date": "2026-11-01"},
        ]
        self.assertFalse(L.is_demoted(trips))

    def test_later_found_or_penny_lifts_demotion(self):
        trips = [
            {"lead_id": "a", "store_id": "0275", "mark": "gone", "date": "2026-11-01"},
            {"lead_id": "a", "store_id": "0275", "mark": "gone", "date": "2026-11-08"},
            {"lead_id": "a", "store_id": "0275", "mark": "penny", "date": "2026-11-10"},
        ]
        self.assertFalse(L.is_demoted(trips, confirmed=False))
        self.assertTrue(L.is_confirmed({"confirmed_at_register": False}, trips))

    def test_confirmed_flag_never_demoted(self):
        trips = [
            {"lead_id": "a", "store_id": "0275", "mark": "gone", "date": "2026-11-01"},
            {"lead_id": "a", "store_id": "0275", "mark": "gone", "date": "2026-11-08"},
        ]
        self.assertFalse(L.is_demoted(trips, confirmed=True))


class PasteAndBuildTests(unittest.TestCase):
    def test_parse_paste_variants(self):
        text = """
# comment
SKU, price, name
564-184, 0.01, Wire shelf, from a trip
100123456789, $0.01, Something with a UPC
PREVIEW-9  0.01  Tabless spaces
"""
        leads = L.parse_paste(text)
        self.assertEqual(len(leads), 3)
        self.assertEqual(leads[0]["sku"], "564-184")
        self.assertEqual(leads[0]["reported_price"], 0.01)
        self.assertEqual(leads[0]["name"], "Wire shelf")
        self.assertEqual(leads[1]["upc"], "100123456789")
        self.assertEqual(leads[2]["sku"], "PREVIEW-9")

    def test_no_ten_dollar_floor(self):
        lead = L.normalize_lead({"sku": "X", "reported_price": 0.01, "source": "community"})
        self.assertEqual(lead["reported_price"], 0.01)

    def fixture_book(self):
        book = L.empty_book()
        L.upsert_lead(book, {
            "id": "ld_fix01", "sku": "FIX-001", "name": "Unconfirmed community",
            "stores": ["0275"], "source": "community", "reported_price": 0.01,
            "reported_at": "2026-11-22",
        })
        L.upsert_lead(book, {
            "id": "ld_fix02", "sku": "FIX-002", "name": "Confirmed trip",
            "stores": ["0226"], "source": "my_trip", "reported_price": 0.01,
            "reported_at": "2026-11-20", "confirmed_at_register": True,
        })
        L.upsert_lead(book, {
            "id": "ld_fix03", "sku": "FIX-003", "name": "Missed twice",
            "stores": ["6351"], "source": "community", "reported_price": 0.01,
            "reported_at": "2026-11-18",
        })
        L.add_trip(book, {"lead_id": "ld_fix02", "store_id": "0226", "mark": "penny", "date": "2026-11-20"})
        L.add_trip(book, {"lead_id": "ld_fix03", "store_id": "6351", "mark": "gone", "date": "2026-11-15"})
        L.add_trip(book, {"lead_id": "ld_fix03", "store_id": "6351", "mark": "gone", "date": "2026-11-19"})
        return book

    def test_build_sort_and_preview_book(self):
        out = L.build_output(self.fixture_book())
        ids = [i["id"] for i in out["items"]]
        self.assertIn("ld_fix02", ids)
        # confirmed first, then newer unconfirmed, demoted last
        self.assertEqual(ids[0], "ld_fix02")
        self.assertEqual(ids[-1], "ld_fix03")
        by = {i["id"]: i for i in out["items"]}
        self.assertTrue(by["ld_fix02"]["confirmed"])
        self.assertTrue(by["ld_fix03"]["demoted"])
        self.assertFalse(by["ld_fix01"]["confirmed"])
        self.assertEqual(out["walmart_enabled"], False)
        self.assertNotIn("score", by["ld_fix01"])
        stores = {s["id"] for s in out["stores"]}
        self.assertTrue(stores)
        self.assertFalse(any(s.startswith("wm") for s in stores))

    def test_empty_book_builds_zero_items(self):
        out = L.build_output(L.empty_book())
        self.assertEqual(out["items"], [])
        self.assertEqual(out["walmart_enabled"], False)

    def test_add_lead_cli(self):
        tmp = Path(tempfile.mkdtemp())
        dest = tmp / "leads.json"
        L.save_book(L.empty_book(), dest)
        # point the CLI at a temp book
        old = L.LEADS_PATH
        try:
            L.LEADS_PATH = dest
            add_lead.main([
                "--sku", "CLI-1", "--price", "0.01", "--name", "CLI item",
                "--store", "0275", "--source", "my_trip", "--no-build",
            ])
            book = L.load_book(dest)
            self.assertEqual(len(book["leads"]), 1)
            self.assertEqual(book["leads"][0]["sku"], "CLI-1")
            self.assertEqual(book["leads"][0]["stores"], ["0275"])
        finally:
            L.LEADS_PATH = old


if __name__ == "__main__":
    unittest.main()
