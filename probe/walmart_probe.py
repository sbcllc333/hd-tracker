"""Test 3: Walmart store 1083, department by department — how much in-store clearance
does each department have, and does it differ from the keyword search?"""
import json, os, sys, urllib.request, urllib.error, urllib.parse

KEY = os.environ.get("SERPAPI_KEY", "").strip()
FACET = "special_offers:Clearance||retailer:Walmart||fulfillment_method_in_store:In-store"
CATS = {"Electronics": "3944", "Home": "4044", "Toys": "4171", "Clothing": "5438", "Patio & Garden": "5428",
        "Home Improvement": "1072864", "Sports & Outdoors": "4125", "Auto & Tires": "91083", "Baby": "5427",
        "Pets": "5440", "Beauty": "1085666", "Health": "976760", "Food": "976759",
        "Household Essentials": "1115193", "Office & School": "1229749", "Video Games": "2636",
        "Arts & Crafts": "1334134", "Party & Occasions": "2637", "Seasonal": "1085632",
        "Personal Care": "1005862", "Cell Phones": "1105910", "Jewelry": "3891"}


def serp(**p):
    p.update(api_key=KEY, store_id="1083", engine="walmart")
    try:
        with urllib.request.urlopen("https://serpapi.com/search.json?" + urllib.parse.urlencode(p), timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code} {e.read().decode()[:160]}"}


grand = 0
for name, cid in CATS.items():
    d = serp(cat_id=cid, facet=FACET)
    if d.get("error"):
        print(f"{name:22} ERROR {d['error'][:120]}"); continue
    info = d.get("search_information") or {}
    res = d.get("organic_results") or []
    tot = info.get("total_results") or 0
    grand += int(tot or 0)
    print(f"{name:22} total={tot}  page1={len(res)}  store={(info.get('location') or {}).get('store_id')}")
    for r in res[:4]:
        po = r.get("primary_offer") or {}
        print("      ", json.dumps({"t": (r.get("title") or "")[:52], "price": po.get("offer_price"), "was": po.get("was_price"),
                                    "oos": r.get("out_of_stock"), "seller": (r.get("seller_name") or "")[:11]}))
print("\nSUM of department totals:", grand)
acct = json.loads(urllib.request.urlopen("https://serpapi.com/account.json?api_key=" + KEY, timeout=60).read().decode())
print("SerpApi searches left this month:", acct.get("total_searches_left"), "of", acct.get("searches_per_month"),
      "| used:", acct.get("this_month_usage"))
