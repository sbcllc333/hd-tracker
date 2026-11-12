"""Test Apify actor s_actors/home-depot-scraper: clearance items at one Jacksonville store."""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse

TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
if not TOKEN:
    sys.exit("APIFY_TOKEN secret is missing or empty")
BASE = "https://api.apify.com/v2"
ACTOR = "s_actors~home-depot-scraper"


def call(method, path, params=None, body=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, repr(e)


def run(label, inp, cap):
    s, t = call("POST", f"/acts/{ACTOR}/runs", {"timeout": 900, "maxTotalChargeUsd": cap}, inp)
    print(f"\n=== {label}: start HTTP {s} {t[:300] if s not in (200, 201) else ''}")
    if s not in (200, 201):
        return
    r = json.loads(t)["data"]
    for _ in range(64):
        time.sleep(10)
        s, t = call("GET", f"/actor-runs/{r['id']}")
        r = json.loads(t)["data"]
        if r.get("status") not in ("READY", "RUNNING"):
            break
    print("finished:", r.get("status"), "| cost USD:", r.get("usageTotalUsd"),
          "| seconds:", (r.get("stats") or {}).get("runTimeSecs"), "| charged:", json.dumps(r.get("chargedEventCounts")))
    s, t = call("GET", f"/actor-runs/{r['id']}/log")
    print("log tail:\n" + "\n".join(t.splitlines()[-8:])[:1200])
    s, t = call("GET", f"/datasets/{r['defaultDatasetId']}/items", {"limit": 2000, "clean": "true"})
    try:
        items = json.loads(t)
    except Exception:
        print("items error:", s, t[:300]); return
    print(f"{len(items)} rows")
    if not items:
        return
    print("fields:", sorted(items[0].keys()))
    print("first row:", json.dumps(items[0])[:1500])
    by = {}
    for i in items:
        by[i.get("query")] = by.get(i.get("query"), 0) + 1
    print("rows per search:", by)
    print("clearance:", sum(1 for i in items if i.get("isClearance")),
          "| with store qty:", sum(1 for i in items if i.get("storeQuantity")),
          "| stores:", {i.get("storeName") for i in items})
    for i in sorted(items, key=lambda x: -(x.get("discountPercent") or 0))[:30]:
        print(json.dumps({"id": i.get("itemId"), "t": (i.get("title") or "")[:55], "price": i.get("price"),
                          "reg": i.get("regularPrice"), "off": i.get("discountPercent"), "clr": i.get("isClearance"),
                          "qty": i.get("storeQuantity"), "sku": i.get("storeSku"), "q": i.get("query")}))


common = {"mode": "search", "storeIds": ["0275"], "zipCode": "32073", "maxStores": 1,
          "onlyChanges": False, "maxConcurrency": 3}
run("clearance only, 7 departments, Orange Park",
    dict(common, keywords=["plumbing", "electrical", "garden", "clearance", "appliances", "lighting", "tools"],
         maxProductsPerSearch=240, onlyClearance=True, minDiscountPercent=0), 0.60)
run("any 40%+ discount, 2 departments, Orange Park",
    dict(common, keywords=["tools", "lighting"], maxProductsPerSearch=240,
         onlyClearance=False, onlyInStock=True, minDiscountPercent=40), 0.30)
