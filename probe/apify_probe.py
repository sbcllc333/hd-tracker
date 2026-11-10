"""One-off test: can Apify's free plan pull clearance items for one
Jacksonville Home Depot store? Capped at 60 items to keep the cost tiny."""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse

TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
if not TOKEN:
    sys.exit("APIFY_TOKEN secret is missing or empty")
BASE = "https://api.apify.com/v2"
ACTOR = "scrapyspider~home-depot-clearance-scraper"
STORE = os.environ.get("STORE_ID", "0275")  # Orange Park (Wells Rd)


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


s, t = call("GET", "/users/me/limits")
print("=== account limits: HTTP", s, t[:700])

s, t = call("POST", f"/acts/{ACTOR}/runs", {"memory": 512, "timeout": 900}, {
    "storeId": STORE, "parallelRequests": 3, "maxResults": 60,
    "proxyConfig": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"],
                    "apifyProxyCountry": "US"}})
print("=== start run: HTTP", s, t[:600])
if s not in (200, 201):
    sys.exit(0)
run = json.loads(t)["data"]
rid = run["id"]
for _ in range(64):
    time.sleep(15)
    s, t = call("GET", f"/actor-runs/{rid}")
    run = json.loads(t)["data"]
    print("  status:", run.get("status"))
    if run.get("status") not in ("READY", "RUNNING"):
        break
print("=== finished:", run.get("status"), "| cost USD:", run.get("usageTotalUsd"),
      "| seconds:", (run.get("stats") or {}).get("runTimeSecs"))
print("usage:", json.dumps(run.get("usageUsd")))

s, t = call("GET", f"/actor-runs/{rid}/log")
print("=== last log lines\n" + "\n".join(t.splitlines()[-25:])[:3000])

s, t = call("GET", f"/datasets/{run['defaultDatasetId']}/items", {"limit": 200, "clean": "true"})
try:
    items = json.loads(t)
except Exception:
    items = []
    print("items error:", s, t[:500])
print(f"=== {len(items)} items")
if items:
    print("fields:", sorted(items[0].keys()))
    print("first item:", json.dumps(items[0])[:2500])
    for it in items[:25]:
        p = it.get("pricing") or {}
        c = p.get("clearance") or {}
        print(json.dumps({"id": it.get("itemId"),
                          "name": (it.get("identifiers") or {}).get("productLabel", "")[:60],
                          "was": p.get("original"), "now": c.get("value") or p.get("value"),
                          "cat": it.get("categoryTitle")}))
