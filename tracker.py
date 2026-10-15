"""
Home Depot Discontinued Tracker
--------------------------------
Once a day:
  1. Pulls Home Depot product listings for the searches in config.json (via SerpApi).
  2. Saves today's list to data/snapshots/YYYY-MM-DD.json.
  3. Compares with the last saved day and finds items that disappeared.
  4. Double-checks a few of those items to see if Home Depot marks them
     discontinued / no longer available.
  5. Writes docs/index.html — the page you open to see the results.

Needs one secret: SERPAPI_KEY (your SerpApi key).
Run:  python tracker.py          (real run)
      python tracker.py --demo   (fake data, no key needed, for testing)
"""

import html
import json
import os
import random
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG = json.loads((ROOT / "config.json").read_text())
SNAP_DIR = ROOT / "data" / "snapshots"
LOG_FILE = ROOT / "data" / "discontinued_log.json"
REPORT = ROOT / "docs" / "index.html"
API = "https://serpapi.com/search.json"
PAGE_SIZE = 24

DEAD_WORDS = ("discontinued", "no longer available", "no longer sold",
              "not available", "product not found", "page not found")


# ---------- talking to SerpApi ----------

def serpapi(params):
    params = dict(params, api_key=os.environ["SERPAPI_KEY"])
    url = API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode())


def stores():
    return [s for s in CONFIG["stores"] if s.get("on", True)]


def fetch_page(store, query, page):
    """One SerpApi search = one page of up to 24 items at one store."""
    params = {"engine": "home_depot", "q": query, "store_id": store["id"],
              "nao": page * PAGE_SIZE, "ps": PAGE_SIZE}
    data = serpapi(params)
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data.get("products", [])


def sold_in_store(p):
    """True = sold in the store, False = online only, None = can't tell (kept, to be safe)."""
    pickup = p.get("pickup")
    if not pickup:
        return None
    if isinstance(pickup, dict):
        if pickup.get("quantity") is not None or pickup.get("store_name") or pickup.get("out_of_stock"):
            return True
        if pickup.get("free_ship_to_store"):
            return False
        return None
    text = str(pickup).lower()
    if "ship to store" in text and "in stock" not in text:
        return False
    return True


def ends_in_03(price):
    try:
        return f"{float(price):.2f}".endswith(".03")
    except (TypeError, ValueError):
        return False


def fetch_listings():
    """Returns {"STOREID:PRODUCTID": item} — each store tracked separately."""
    items = {}
    searches_used = 0
    skip_online = CONFIG.get("skip_online_only", True)
    for store in stores():
        for query in CONFIG["searches"]:
            for page in range(CONFIG["pages_per_search"]):
                try:
                    products = fetch_page(store, query, page)
                    searches_used += 1
                except Exception as e:
                    print(f"  ! {store['name']} '{query}' page {page + 1} failed: {e}")
                    break
                for p in products:
                    pid = str(p.get("product_id") or "")
                    if not pid:
                        continue
                    if skip_online and sold_in_store(p) is False:
                        continue
                    items[f"{store['id']}:{pid}"] = {
                        "pid": pid,
                        "store": store["name"],
                        "store_id": store["id"],
                        "title": p.get("title", ""),
                        "brand": p.get("brand", ""),
                        "model": p.get("model_number", ""),
                        "price": p.get("price"),
                        "link": p.get("link", ""),
                        "search": query,
                    }
                print(f"  {store['name']} '{query}' page {page + 1}: {len(products)} items")
                if len(products) < PAGE_SIZE:
                    break
    return items, searches_used


def check_product(pid, store_id):
    """Ask Home Depot (via SerpApi) about one product at one store. Returns a status label."""
    try:
        data = serpapi({"engine": "home_depot_product", "product_id": pid, "store_id": store_id})
    except Exception as e:
        return "Couldn't check", str(e)
    text = json.dumps(data).lower()
    if data.get("error"):
        return "Gone from site", data["error"]
    if any(w in text for w in DEAD_WORDS):
        return "Discontinued", "Home Depot marks it no longer available"
    return "Still listed", "Dropped from search results but product page still exists"


# ---------- demo data (no key needed) ----------

def demo_listings(day_offset):
    random.seed(42)
    base = {}
    for s in stores():
        for i in range(20):
            pid = str(300000000 + i)
            base[f"{s['id']}:{pid}"] = {
                "pid": pid, "store": s["name"], "store_id": s["id"],
                "title": f"Demo Product {i}", "brand": random.choice(["RYOBI", "DEWALT", "Milwaukee", "HDX"]),
                "model": f"M{i:04d}",
                "price": (int(random.uniform(9, 99)) + 0.03) if i % 7 == 0 else round(random.uniform(9, 399), 2),
                "link": "https://www.homedepot.com", "search": "demo"}
    if day_offset == 1:            # "today": a few items vanished, a few new
        for key in random.sample(sorted(base), 6):
            del base[key]
        s = stores()[0]
        base[f"{s['id']}:300000099"] = dict(base.get(f"{s['id']}:300000001", {}) or {},
                                           pid="300000099", store=s["name"], store_id=s["id"],
                                           title="New Demo Product 99", brand="RYOBI", model="M0099",
                                           price=49.97, link="https://www.homedepot.com", search="demo")
    return base


# ---------- saving + comparing ----------

def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def previous_snapshot(today_str):
    snaps = sorted(p for p in SNAP_DIR.glob("*.json") if p.stem < today_str)
    return (snaps[-1].stem, load_json(snaps[-1], {})) if snaps else (None, None)


def main():
    demo = "--demo" in sys.argv
    if not demo and not os.environ.get("SERPAPI_KEY"):
        sys.exit("SERPAPI_KEY is not set.")
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)

    today = date.today()
    if demo:   # make a fake "yesterday" first so there is something to compare
        (SNAP_DIR / f"{today - timedelta(days=1)}.json").write_text(json.dumps(demo_listings(0)))
        items, used = demo_listings(1), 0
    else:
        print("Pulling today's listings...")
        items, used = fetch_listings()

    today_str = today.isoformat()
    if not items:
        sys.exit("Got zero items today — not saving (probably an API problem).")
    (SNAP_DIR / f"{today_str}.json").write_text(json.dumps(items, indent=1))

    prev_day, prev = previous_snapshot(today_str)
    log = load_json(LOG_FILE, [])
    gone, new = [], []

    if prev is not None and not demo:
        # Only compare departments we still track, so changing the list doesn't look like a mass discontinue.
        prev = {k: v for k, v in prev.items() if v.get("search") in CONFIG["searches"]}

    # Prices ending in .03 — often the last markdown before a penny.
    point03 = []
    for key, it in items.items():
        if ends_in_03(it.get("price")):
            was = (prev or {}).get(key)
            fresh = not (was and ends_in_03(was.get("price")))
            point03.append(dict(it, id=key, status="New .03 today" if fresh else ".03"))
    point03.sort(key=lambda r: (r["status"] != "New .03 today", r["store"], r["title"]))

    if prev is not None:
        # A store that returned nothing today had a failed pull — don't count its items as gone.
        stores_ok = {it["store_id"] for it in items.values()}
        gone_ids = [k for k in prev if k not in items and prev[k].get("store_id") in stores_ok]
        new = [dict(items[pid], id=pid) for pid in items if pid not in prev]
        # If more than half vanished at once, it's almost surely a bad pull, not real.
        if prev and len(gone_ids) > 0.5 * len(prev):
            print(f"  ! {len(gone_ids)} of {len(prev)} items missing — looks like a bad pull, skipping.")
            gone_ids = []
        limit = CONFIG["double_check_limit"]
        checked = 0
        for key in gone_ids:
            item = prev[key]
            if demo:
                status, note = random.choice([("Discontinued", "Demo"), ("Still listed", "Demo")])
            elif checked < limit:
                status, note = check_product(item["pid"], item["store_id"])
                checked += 1
                used += 1
            else:
                status, note = "Not checked", "Over the daily double-check limit"
            row = dict(item, id=key, status=status, note=note,
                       last_seen=prev_day, noticed=today_str)
            gone.append(row)
            if status in ("Discontinued", "Gone from site"):
                log.append(row)
        LOG_FILE.write_text(json.dumps(log, indent=1))

    write_report(today_str, prev_day, items, gone, new, log, used, demo, point03)
    print(f"Done. {len(items)} items today, {len(gone)} disappeared, {len(new)} new, "
          f"{len(point03)} priced .03. "
          f"SerpApi searches used: {used}")


# ---------- the page ----------

def money(v):
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return ""


def rows(items, show_status=True, date_key=None):
    if not items:
        return '<p class="empty">Nothing here.</p>'
    out = []
    for it in items:
        badge = ""
        if show_status:
            cls = {"Discontinued": "bad", "Gone from site": "bad", "New .03 today": "bad",
                   "Still listed": "ok"}.get(it.get("status"), "meh")
            badge = f'<span class="badge {cls}">{html.escape(it.get("status", ""))}</span>'
        when = f'<span class="when">{html.escape(it.get(date_key, ""))}</span>' if date_key else ""
        store = f'<span class="store">{html.escape(it.get("store", ""))}</span>'
        out.append(
            f'<a class="item" href="{html.escape(it.get("link") or "#")}" target="_blank" rel="noopener">'
            f'<div class="t">{html.escape(it.get("title", ""))}</div>'
            f'<div class="m">{html.escape(it.get("brand") or "")} · Model {html.escape(it.get("model") or "?")}'
            f' · {money(it.get("price"))}</div>'
            f'<div class="b">{store}{badge}{when}</div></a>')
    return "\n".join(out)


def write_report(today, prev_day, items, gone, new, log, used, demo, point03):
    confirmed = [g for g in gone if g["status"] in ("Discontinued", "Gone from site")]
    other = [g for g in gone if g not in confirmed]
    compare = f"Compared with {prev_day}" if prev_day else "First day — nothing to compare yet. Check back tomorrow."
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HD Discontinued</title>
<style>
:root {{ --bg:#f6f4f1; --card:#fff; --ink:#1d1b19; --mute:#6b655e; --line:#e4dfd8;
        --orange:#f96302; --bad:#b3261e; --ok:#2e7d32; --meh:#7a6a00; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#141210; --card:#1f1c19; --ink:#f1ece6; --mute:#a69e95; --line:#332e29; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
header {{ background:var(--orange); color:#fff; padding:18px 16px 14px; }}
header h1 {{ margin:0; font-size:20px; }}
header p {{ margin:4px 0 0; opacity:.9; font-size:13px; }}
main {{ max-width:720px; margin:0 auto; padding:12px 16px 40px; }}
.stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin:4px 0 16px; }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px; text-align:center; }}
.stat b {{ display:block; font-size:22px; }}
.stat span {{ font-size:12px; color:var(--mute); }}
h2 {{ font-size:16px; margin:22px 0 8px; }}
h2 small {{ color:var(--mute); font-weight:400; }}
.item {{ display:block; background:var(--card); border:1px solid var(--line); border-radius:10px;
        padding:10px 12px; margin:6px 0; color:inherit; text-decoration:none; }}
.t {{ font-weight:600; }}
.m {{ color:var(--mute); font-size:13px; margin-top:2px; }}
.b {{ margin-top:6px; display:flex; gap:8px; align-items:center; }}
.badge {{ font-size:12px; font-weight:600; padding:2px 8px; border-radius:99px; color:#fff; }}
.bad {{ background:var(--bad); }} .ok {{ background:var(--ok); }} .meh {{ background:var(--meh); }}
.when {{ font-size:12px; color:var(--mute); }}
.store {{ font-size:12px; font-weight:600; padding:2px 8px; border-radius:99px;
         border:1px solid var(--orange); color:var(--orange); }}
.empty {{ color:var(--mute); font-style:italic; }}
details {{ margin-top:8px; }} summary {{ cursor:pointer; font-weight:600; }}
.demo {{ background:#fff3cd; color:#5c4400; padding:8px 12px; border-radius:8px; margin-bottom:10px; font-size:13px; }}
footer {{ color:var(--mute); font-size:12px; margin-top:28px; }}
</style></head><body>
<header><h1>Jacksonville Home Depot — Discontinued Watch</h1>
<p>{today} · {compare}</p></header>
<main>
{'<div class="demo">DEMO DATA — not real Home Depot items.</div>' if demo else ''}
<div class="stats">
  <div class="stat"><b>{len(items)}</b><span>tracked today</span></div>
  <div class="stat"><b>{len(confirmed)}</b><span>discontinued today</span></div>
  <div class="stat"><b>{len(point03)}</b><span>priced .03</span></div>
  <div class="stat"><b>{len(new)}</b><span>new today</span></div>
</div>

<h2>Discontinued since yesterday</h2>
{rows(confirmed)}

<h2>Prices ending in .03 <small>(often next stop is a penny)</small></h2>
{rows(point03)}

<h2>Disappeared, not confirmed <small>({len(other)})</small></h2>
{rows(other)}

<details><summary>New items today ({len(new)})</summary>{rows(new, show_status=False)}</details>
<details><summary>All discontinued, every day ({len(log)})</summary>
{rows(list(reversed(log)), date_key="noticed")}</details>

<footer>Stores: {html.escape(", ".join(s["name"] for s in stores()))} ·
Searches tracked: {html.escape(", ".join(CONFIG["searches"]))} ·
SerpApi searches used this run: {used} · Updated {datetime.now():%b %d, %Y %I:%M %p}</footer>
</main></body></html>"""
    REPORT.write_text(page)


if __name__ == "__main__":
    main()
