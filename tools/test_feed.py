#!/usr/bin/env python3
"""Tests for the daily deep-clearance feed (no network: Apify calls are faked)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feed as F
import leads_lib as L

CFG = {"stores": [
    {"id": "0275", "name": "Orange Park (Wells Rd)", "short": "Orange Park", "zip": "32073", "retailer": "homedepot"},
    {"id": "6346", "name": "Lane Ave / Normandy", "short": "Normandy", "zip": "32205", "retailer": "homedepot"},
    {"id": "6864", "name": "Lake City", "short": "Lake City", "zip": "32025", "retailer": "homedepot"},
], "walmart_enabled": False}
STORES = CFG["stores"]


def row(pid, price, was, pct=None, store="6346", **kw):
    r = {"type": "product", "itemId": pid, "title": f"Item {pid}", "brand": "Vigoro", "model": "M1",
         "storeSku": "100" + pid[-4:], "upc": "0123456" + pid[-5:], "price": price, "regularPrice": was,
         "discountPercent": pct, "storeQuantity": 3, "isClearance": True, "storeId": store,
         "image": "https://images.thdstatic.com/x_400.jpg", "url": f"https://www.homedepot.com/p/Item/{pid}?x=1",
         "department": "Garden"}
    r.update(kw)
    return r


class FakeApify:
    """Answers the Apify REST calls feed.py makes."""
    def __init__(self, by_kind, used=1.0, cap=5.0, fail=False):
        self.by_kind, self.used, self.cap, self.fail, self.calls = by_kind, used, cap, fail, []

    def __call__(self, method, path, params=None, body=None):
        self.calls.append((method, path, params, body))
        if path == "/users/me/limits":
            return {"data": {"current": {"monthlyUsageUsd": self.used}, "limits": {"maxMonthlyUsageUsd": self.cap}}}
        if method == "POST":
            if self.fail:
                raise RuntimeError("HTTP Error 402: Payment Required")
            kind = "category" if body.get("categoryUrls") else "keywords"
            store = body["storeIds"][0]
            self.last = (kind, store)
            return {"data": {"id": "run1", "status": "SUCCEEDED", "defaultDatasetId": "ds1", "usageTotalUsd": 0.05}}
        if path.startswith("/datasets/"):
            kind, store = self.last
            return [dict(r, storeId=store) for r in self.by_kind.get(kind, [])]
        if path.startswith("/actor-runs/"):
            return {"data": {"id": "run1", "status": "SUCCEEDED", "defaultDatasetId": "ds1", "usageTotalUsd": 0.05}}
        raise AssertionError(path)


class HelperTests(unittest.TestCase):
    def test_pct_off(self):
        self.assertEqual(F.pct_off(0.10, 16.97), 99)
        self.assertEqual(F.pct_off(5, 10, 50.4), 50)
        self.assertEqual(F.pct_off(10, None), 0)
        self.assertEqual(F.pct_off(12, 10), 0)

    def test_penny_stage(self):
        self.assertEqual(F.penny_stage(0.01), "penny")
        self.assertEqual(F.penny_stage(4.03), "near")
        self.assertEqual(F.penny_stage(0.50), "near")
        self.assertEqual(F.penny_stage(12.97), "")

    def test_parse_row(self):
        it = F.parse_row(row("317848340", 0.10, 16.97, aisle="12", bay="004"), "6346")
        self.assertEqual(it["pct"], 99)
        self.assertEqual(it["sku"], "1008340")
        self.assertEqual(it["link"], "https://www.homedepot.com/p/Item/317848340")
        self.assertEqual((it["aisle"], it["bay"]), ("12", "004"))
        self.assertEqual(it["qty"], 3)
        self.assertIsNone(F.parse_row({"type": "product", "itemId": "", "price": 1}, "6346"))
        self.assertEqual(F.parse_row(row("1", 5, 10, storeId="275"), "0275")["store_id"], "0275")


class LedgerTests(unittest.TestCase):
    def test_merge_scan_adds_updates_and_drops(self):
        fd = F.empty_feed()
        a = F.parse_row(row("11111", 2.0, 10.0), "6346")
        b = F.parse_row(row("22222", 3.0, 10.0), "6346")
        other = F.parse_row(row("33333", 1.0, 10.0, store="0275"), "0275")
        F.merge_scan(fd, "0275", [other], "2026-11-20", "t")
        res = F.merge_scan(fd, "6346", [a, b], "2026-11-20", "t")
        self.assertEqual(res, {"kept": 2, "new": 2, "dropped": 0})
        a2 = dict(a, price=1.0)
        res = F.merge_scan(fd, "6346", [a2], "2026-11-23", "t")
        self.assertEqual(res, {"kept": 1, "new": 0, "dropped": 1})
        it = fd["items"]["6346:11111"]
        self.assertEqual(it["first_seen"], "2026-11-20")
        self.assertEqual(it["last_seen"], "2026-11-23")
        self.assertEqual(it["history"], [["2026-11-20", 2.0], ["2026-11-23", 1.0]])
        self.assertIn("0275:33333", fd["items"])          # other store untouched

    def test_seed_from_old_ledger(self):
        tmp = Path(tempfile.mkdtemp()) / "ledger.json"
        tmp.write_text(json.dumps({"items": {
            "6346:1": {"source": "apify", "missed": 0, "store_id": "6346", "pid": "1", "title": "A", "price": 0.1,
                       "was": 16.97, "pct": 99, "qty": 0.0, "last_seen": "2026-11-17", "first_clearance": "2026-11-12",
                       "history": [["2026-11-12", 0.1]]},
            "6346:2": {"source": "serpapi", "store_id": "6346", "pid": "2", "price": 5, "was": 6},
            "wm1:3": {"source": "apify", "missed": 0, "store_id": "wm1", "pid": "3", "price": 1, "was": 9},
            "6346:4": {"source": "apify", "missed": 2, "store_id": "6346", "pid": "4", "price": 1, "was": 9},
        }}))
        fd = F.empty_feed()
        self.assertEqual(F.seed_from_old_ledger(fd, tmp), 1)
        self.assertEqual(fd["scans"]["6346"]["date"], "2026-11-17")
        self.assertEqual(F.seed_from_old_ledger(fd, tmp), 0)   # only once

    def test_output_filters_and_ranks(self):
        fd = F.empty_feed()
        items = [F.parse_row(row("1", 4.0, 10.0), "6346"), F.parse_row(row("2", 0.03, 10.0), "6346"),
                 F.parse_row(row("3", 8.0, 10.0), "6346")]
        F.merge_scan(fd, "6346", items, "2026-11-20", "t")
        old = F.parse_row(row("9", 1.0, 10.0, store="0275"), "0275")
        F.merge_scan(fd, "0275", [old], "2026-11-01", "t")
        deals, meta = F.deals_for_output(fd, CFG, STORES, "2026-11-23")
        self.assertEqual([d["pid"] for d in deals], ["2", "1"])   # 20% off dropped, 23-day-old dropped
        self.assertEqual(deals[0]["stage"], "near")
        self.assertEqual(deals[0]["id"], "hd-6346-2")
        self.assertEqual(meta["stores"]["6346"]["count"], 2)
        self.assertEqual(meta["stores"]["6864"], {"last_scan": None, "count": 0})


class UpdateTests(unittest.TestCase):
    def test_no_token_fetches_nothing(self):
        fd = F.empty_feed()
        fake = FakeApify({})
        st = F.update(fd, CFG, STORES, "2026-11-23", call=fake, token="")
        self.assertFalse(st["ok"])
        self.assertIn("No APIFY_TOKEN", st["note"])
        self.assertEqual(fake.calls, [])

    def test_scans_oldest_stores_and_falls_back_to_keywords(self):
        fd = F.empty_feed()
        fd["scans"]["0275"] = {"date": "2026-11-22"}
        fake = FakeApify({"category": [], "keywords": [row("5", 0.5, 20.0), row("6", 9.0, 10.0)]})
        st = F.update(fd, CFG, STORES, "2026-11-23", call=fake, sleep=lambda s: None, token="t")
        self.assertTrue(st["ok"], st)
        posted = [(c[3]["storeIds"][0], "categoryUrls" in c[3]) for c in fake.calls if c[0] == "POST"]
        # never-scanned stores first (6346, 6864), category pass then keyword pass each
        self.assertEqual(posted, [("6346", True), ("6346", False), ("6864", True), ("6864", False)])
        self.assertIn("6346:5", fd["items"])
        self.assertNotIn("6346:6", fd["items"])            # 10% off is not kept
        body = [c for c in fake.calls if c[0] == "POST"][0]
        self.assertEqual(body[3]["minDiscountPercent"], 50)
        self.assertTrue(body[3]["onlyClearance"])
        self.assertLessEqual(body[2]["maxTotalChargeUsd"], 0.2)

    def test_stops_at_budget(self):
        fd = F.empty_feed()
        fake = FakeApify({"category": [row("5", 0.5, 20.0)]}, used=4.45)
        st = F.update(fd, CFG, STORES, "2026-11-23", call=fake, token="t")
        self.assertFalse(st["ok"])
        self.assertIn("credit", st["note"])
        self.assertFalse([c for c in fake.calls if c[0] == "POST"])

    def test_failed_run_keeps_last_scan(self):
        fd = F.empty_feed()
        F.merge_scan(fd, "6346", [F.parse_row(row("1", 1.0, 10.0), "6346")], "2026-11-20", "t")
        fake = FakeApify({}, fail=True)
        st = F.update(fd, CFG, STORES, "2026-11-23", call=fake, token="t", only=["6346"])
        self.assertFalse(st["ok"])
        self.assertIn("6346:1", fd["items"])
        self.assertEqual(fd["scans"]["6346"]["date"], "2026-11-20")


class BudgetTests(unittest.TestCase):
    def test_partial_scan_keeps_unseen_items(self):
        fd = F.empty_feed()
        F.merge_scan(fd, "6346", [F.parse_row(row("1", 1.0, 10.0), "6346")], "2026-11-20", "t")
        F.merge_scan(fd, "6346", [F.parse_row(row("2", 1.0, 10.0), "6346")], "2026-11-23", "t", complete=False)
        self.assertIn("6346:1", fd["items"])
        self.assertIn("6346:2", fd["items"])

    def test_daily_allowance_spreads_credit(self):
        fd = F.empty_feed()
        cfg = dict(CFG, feed={"stores_per_day": 3, "max_cost_per_store_usd": 0.2})
        # $4.30 used, budget $4.50, 8 days left: only one store today
        fake = FakeApify({"category": [row("5", 0.5, 20.0)]}, used=4.2)
        F.update(fd, cfg, STORES, "2026-11-23", call=fake, sleep=lambda s: None, token="t")
        self.assertEqual(len([c for c in fake.calls if c[0] == "POST"]), 1)

    def test_cycle_end_from_limits(self):
        def call(m, p, *a):
            return {"data": {"current": {"monthlyUsageUsd": 2}, "limits": {"maxMonthlyUsageUsd": 5},
                             "monthlyUsageCycle": {"startAt": "2026-11-10T00:00:00Z", "endAt": "2026-12-10T00:00:00Z"}}}
        self.assertEqual(F.month_usage(call, "2026-11-23"), (2.0, 5.0, 17))


class BuildTests(unittest.TestCase):
    def test_build_output_has_deals_and_leads(self):
        fd = F.empty_feed()
        F.merge_scan(fd, "6346", [F.parse_row(row("1", 0.1, 16.97), "6346")], L.today(), "t")
        book = L.empty_book()
        L.upsert_lead(book, {"sku": "X-1", "reported_price": 0.01, "source": "community"})
        out = L.build_output(book, feed=fd)
        self.assertEqual(len(out["deals"]), 1)
        self.assertEqual(out["deals"][0]["pct"], 99)
        self.assertEqual(len(out["items"]), 1)
        self.assertEqual(out["feed"]["min_pct"], 50)

    def test_service_worker_and_assets_bumped(self):
        docs = Path(__file__).resolve().parents[1] / "docs"
        sw = (docs / "sw.js").read_text()
        html = (docs / "index.html").read_text()
        self.assertIn("penny-run-v18", sw)
        self.assertIn("app.js?v=18", sw)
        self.assertIn("app.js?v=18", html)
        self.assertIn("app.css?v=18", html)


if __name__ == "__main__":
    unittest.main()
