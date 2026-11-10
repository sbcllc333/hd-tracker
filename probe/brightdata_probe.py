"""One-off test: can Bright Data's free plan return Home Depot products
for a Jacksonville zip code? Uses at most ~10 records of the free allowance."""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse

KEY = os.environ.get("BRIGHTDATA_KEY", "").strip()
if not KEY:
    sys.exit("BRIGHTDATA_KEY secret is missing or empty")
BASE = "https://api.brightdata.com"
DS = "gd_lmusivh019i7g97q2n"  # Home Depot US


def call(method, path, params=None, body=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # network trouble
        return 0, repr(e)


def show(label, status, text, limit=1500):
    print(f"\n=== {label}: HTTP {status}\n{text[:limit]}")


# 1. Which Home Depot scrapers does this account see?
s, t = call("GET", "/datasets/list")
try:
    hd = [d for d in json.loads(t) if "depot" in json.dumps(d).lower()]
    show("home depot scrapers", s, json.dumps(hd, indent=1))
except Exception:
    show("datasets list", s, t)


def records_from(text):
    text = text.strip()
    try:
        j = json.loads(text)
        return j if isinstance(j, list) else [j]
    except Exception:
        return [json.loads(l) for l in text.splitlines() if l.strip().startswith("{")]


def run(label, params, body):
    p = {"dataset_id": DS, "include_errors": "true", "format": "json"}
    p.update(params)
    s, t = call("POST", "/datasets/v3/trigger", p, body)
    show(label + " trigger", s, t)
    if s != 200:
        return None
    snap = json.loads(t).get("snapshot_id")
    for _ in range(40):  # up to ~10 minutes
        time.sleep(15)
        s, t = call("GET", f"/datasets/v3/progress/{snap}")
        st = ""
        try:
            st = json.loads(t).get("status", "")
        except Exception:
            pass
        print("  progress:", s, st)
        if st in ("ready", "failed"):
            break
    s, t = call("GET", f"/datasets/v3/snapshot/{snap}", {"format": "json"})
    if s != 200:
        show(label + " result", s, t)
        return None
    recs = records_from(t)
    print(f"\n=== {label}: {len(recs)} records")
    if recs:
        print("fields:", sorted(recs[0].keys()))
        for r in recs[:5]:
            keep = {k: v for k, v in r.items() if any(w in k.lower() for w in (
                "name", "title", "price", "avail", "stock", "store", "zip",
                "sku", "product_id", "model", "discontin", "error", "warning", "url"))}
            print(json.dumps(keep)[:900])
    return recs


# 2. Keyword search, localized to Orange Park (Wells Rd) zip
kw = run("keyword search",
         {"type": "discover_new", "discover_by": "keyword"},
         {"input": [{"keyword": "clearance plumbing", "zipcode": "32073"}],
          "limit_per_input": 5})
if kw is None:  # maybe the field names differ; the error text above will say
    kw = run("keyword search (keyword only)",
             {"type": "discover_new", "discover_by": "keyword"},
             {"input": [{"keyword": "clearance plumbing"}], "limit_per_input": 5})

# 3. One known product page, two different zips, to see if results are store-specific
url = "https://www.homedepot.com/p/Con-Tact-Shelf-and-Storage-Clear-Shelf-Drawer-Liner-06F-C8Q01-06/100572514"
run("single product, two zips", {},
    [{"url": url, "zipcode": "32073"}, {"url": url, "zipcode": "32218"}])
