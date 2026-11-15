"""Test: can we get clearance data for Walmart #1083 (6830 Normandy Blvd, Jacksonville)?"""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse


def http(method, url, headers=None, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, repr(e)


# ---- A. SerpApi Walmart search, pinned to store 1083
key = os.environ.get("SERPAPI_KEY", "").strip()
for q in (["clearance"] if key else []):
    s, t = http("GET", "https://serpapi.com/search.json?" + urllib.parse.urlencode(
        {"engine": "walmart", "query": q, "store_id": "1083", "api_key": key}))
    print(f"\n=== SerpApi walmart '{q}': HTTP {s}")
    try:
        d = json.loads(t)
    except Exception:
        print(t[:300]); continue
    if d.get("error"):
        print("error:", d["error"]); continue
    print("location:", json.dumps((d.get("search_information") or {}).get("location")))
    res = d.get("organic_results") or []
    print(len(res), "results; fields:", sorted(res[0].keys()) if res else None)
    for r in res[:12]:
        po = r.get("primary_offer") or {}
        print(json.dumps({"id": r.get("us_item_id"), "t": (r.get("title") or "")[:50], "price": po.get("offer_price"),
                          "was": po.get("was_price"), "seller": r.get("seller_name"), "oos": r.get("out_of_stock"),
                          "badges": r.get("badges") or r.get("badge"), "pickup": r.get("pickup")}))

# ---- B. Apify crawloop/walmart-scraper, ZIP 32205 + store 1083
tok = os.environ.get("APIFY_TOKEN", "").strip()
H = {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}
if tok:
    s, t = http("POST", "https://api.apify.com/v2/acts/crawloop~walmart-scraper/runs?timeout=600&maxTotalChargeUsd=0.2", H,
                {"keywords": ["clearance"], "zip": "32205", "storeId": "1083", "scrapeMode": "overview",
                 "sort": "best_match", "maxItems": 40, "maxPages": 1,
                 "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"],
                                        "apifyProxyCountry": "US"}})
    print(f"\n=== Apify crawloop start: HTTP {s} {t[:300] if s not in (200, 201) else ''}")
    if s in (200, 201):
        r = json.loads(t)["data"]
        for _ in range(50):
            time.sleep(10)
            r = json.loads(http("GET", f"https://api.apify.com/v2/actor-runs/{r['id']}", H)[1])["data"]
            if r.get("status") not in ("READY", "RUNNING"):
                break
        print("finished:", r.get("status"), "| cost:", r.get("usageTotalUsd"), "| charged:", json.dumps(r.get("chargedEventCounts")))
        s, t = http("GET", f"https://api.apify.com/v2/actor-runs/{r['id']}/log", H)
        print("log tail:\n" + "\n".join(t.splitlines()[-6:])[:900])
        items = json.loads(http("GET", f"https://api.apify.com/v2/datasets/{r['defaultDatasetId']}/items?clean=true&limit=200", H)[1])
        print(len(items), "rows; fields:", sorted(items[0].keys()) if items else None)
        if items:
            print("first:", json.dumps(items[0])[:900])
        print("stores:", {i.get("storeId") for i in items}, "| with was-price:", sum(1 for i in items if i.get("originalPrice")))
        for i in items[:25]:
            print(json.dumps({"id": i.get("usItemId"), "t": (i.get("title") or "")[:50], "price": i.get("price"),
                              "was": i.get("originalPrice"), "seller": i.get("sellerName"), "stock": i.get("availability"),
                              "pickup": i.get("pickupAvailable"), "store": i.get("storeId")}))
