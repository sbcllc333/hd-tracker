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

s, t = call("POST", f"/acts/{ACTOR}/runs", {"memory": 512, "timeout": 3600, "maxTotalChargeUsd": 1.5}, {
    "storeId": STORE, "parallelRequests": 6, "maxResults": 0,
    "proxyConfig": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"],
                    "apifyProxyCountry": "US"}})
print("=== start run: HTTP", s, t[:600])
if s not in (200, 201):
    sys.exit(0)
run = json.loads(t)["data"]
rid = run["id"]
for _ in range(244):
    time.sleep(15)
    s, t = call("GET", f"/actor-runs/{rid}")
    run = json.loads(t)["data"]
    if run.get("status") not in ("READY", "RUNNING"):
        break
print("=== finished:", run.get("status"), "| cost USD:", run.get("usageTotalUsd"),
      "| seconds:", (run.get("stats") or {}).get("runTimeSecs"))
print("usage:", json.dumps(run.get("usageUsd")))

s, t = call("GET", f"/actor-runs/{rid}/log")
L = t.splitlines()
print("=== log:", len(L), "lines |", sum("Error" in x for x in L), "errors |", sum("Fetching products" in x for x in L), "fetches")
print("\n".join(L[-12:])[:1500])

items, off = [], 0
while True:
    s, t = call("GET", f"/datasets/{run['defaultDatasetId']}/items", {
        "limit": 1000, "offset": off, "clean": "true",
        "fields": "itemId,identifiers,pricing,isClearanceItem,categoryTitle,categoryPath"})
    try:
        page = json.loads(t)
    except Exception:
        print("items error:", s, t[:500])
        break
    items += page
    off += 1000
    if len(page) < 1000:
        break


def now(it):
    p = it.get("pricing") or {}
    return (p.get("clearance") or {}).get("value") or p.get("value")


clr = [i for i in items if i.get("isClearanceItem")]
cats = {i.get("categoryTitle") for i in items}
cents = lambda v: int(round(float(v) * 100)) % 100 if v else -1
print(f"=== {len(items)} items, {len(clr)} flagged clearance, {len(cats)} categories")
print("prices ending .03:", sum(1 for i in clr if cents(now(i)) == 3),
      "| .06:", sum(1 for i in clr if cents(now(i)) == 6),
      "| .01:", sum(1 for i in items if now(i) and float(now(i)) <= 0.01))


def pct(i):
    return ((i.get("pricing") or {}).get("clearance") or {}).get("percentageOff") or 0


for it in sorted(clr, key=pct, reverse=True)[:40]:
    p = it.get("pricing") or {}
    print(json.dumps({"id": it.get("itemId"),
                      "name": (it.get("identifiers") or {}).get("productLabel", "")[:60],
                      "was": p.get("original"), "now": now(it), "off%": pct(it),
                      "cat": it.get("categoryTitle")}))
