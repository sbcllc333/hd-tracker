"""Test 2: SerpApi Walmart for store 1083 — learn the filter codes, then ask for
in-store + sold-by-Walmart + clearance items."""
import json, os, sys, urllib.request, urllib.error, urllib.parse

KEY = os.environ.get("SERPAPI_KEY", "").strip()
if not KEY:
    sys.exit("no SERPAPI_KEY")


def serp(**p):
    p.update(api_key=KEY, store_id="1083")
    try:
        with urllib.request.urlopen("https://serpapi.com/search.json?" + urllib.parse.urlencode(p), timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code} {e.read().decode()[:200]}"}


def show(label, d, n=25):
    print(f"\n=== {label}")
    if d.get("error"):
        print("error:", d["error"]); return
    print("location:", json.dumps((d.get("search_information") or {}).get("location")),
          "| total:", (d.get("search_information") or {}).get("total_results"))
    res = d.get("organic_results") or []
    print(len(res), "results; walmart-sold:", sum(1 for r in res if r.get("seller_name") == "Walmart.com"),
          "| with was-price:", sum(1 for r in res if (r.get("primary_offer") or {}).get("was_price")))
    for r in res[:n]:
        po = r.get("primary_offer") or {}
        print(json.dumps({"id": r.get("us_item_id"), "t": (r.get("title") or "")[:55], "price": po.get("offer_price"),
                          "was": po.get("was_price"), "seller": (r.get("seller_name") or "")[:14], "oos": r.get("out_of_stock")}))


d = serp(engine="walmart", query="clearance", include_filters="true")
flt = d.get("filters") or []
print("=== filters returned:", len(flt))
pick = {}
for f in flt:
    name = (f.get("name") or f.get("title") or f.get("key") or "")
    vals = f.get("values") or f.get("options") or f.get("value") or []
    print("-", json.dumps({k: v for k, v in f.items() if k not in ("values", "options", "value")})[:200])
    for v in (vals if isinstance(vals, list) else [])[:14]:
        print("     ", json.dumps(v)[:230])
        text = json.dumps(v).lower()
        if "clearance" in text and "clearance" not in pick: pick["clearance"] = (f, v)
        if '"walmart"' in text and "retailer" not in pick: pick["retailer"] = (f, v)
        if "in-store" in text and "instore" not in pick: pick["instore"] = (f, v)
print("picked:", {k: json.dumps(v[1])[:160] for k, v in pick.items()})

# try the facet forms Walmart's own site uses
for label, facet in [
    ("clearance + sold by Walmart + in-store",
     "special_offers:Clearance||retailer:Walmart||fulfillment_method_in_store:In-store"),
    ("clearance + in-store", "special_offers:Clearance||fulfillment_method_in_store:In-store"),
]:
    show(label + "  [facet=" + facet + "]", serp(engine="walmart", query="clearance", facet=facet, sort="price_low"))
