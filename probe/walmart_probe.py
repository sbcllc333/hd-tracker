"""Read why the Apify actor rejects a large maxProductsPerSearch (validation only, no run starts)."""
import json, os, urllib.request, urllib.error
TOK = os.environ["APIFY_TOKEN"].strip()
H = {"Authorization": "Bearer " + TOK, "Content-Type": "application/json"}
body = {"mode": "search", "keywords": ["tools"], "storeIds": ["0275"], "zipCode": "32073", "maxStores": 1,
        "maxProductsPerSearch": 6000, "onlyClearance": True, "minDiscountPercent": 0, "onlyChanges": False, "maxConcurrency": 3}
req = urllib.request.Request("https://api.apify.com/v2/acts/s_actors~home-depot-scraper/runs?maxTotalChargeUsd=0.01&timeout=30",
                             data=json.dumps(body).encode(), method="POST", headers=H)
try:
    r = urllib.request.urlopen(req, timeout=60); d = json.loads(r.read())["data"]
    print("started?!", d["id"]); urllib.request.urlopen(urllib.request.Request(
        f"https://api.apify.com/v2/actor-runs/{d['id']}/abort", method="POST", headers=H), timeout=60)
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:600])
