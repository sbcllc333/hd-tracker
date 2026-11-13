"""
Penny Run — clearance tracker for a few Home Depot stores
----------------------------------------------------------
Runs once a day (GitHub Actions). Each day it scans ONE store, so every store
is scanned every 4 days and the whole thing fits in SerpApi's free plan.

  1. Picks the store that was scanned longest ago.
  2. Asks Apify for that store's clearance items in each department
     (falls back to SerpApi if Apify can't run).
  3. Updates data/ledger.json: a running history per item per store
     (first seen on clearance, every price change, stock count).
  4. Asks Bright Data whether the most promising items are discontinued.
  5. Scores every item 0-100 for how close it looks to a penny.
  6. Writes docs/data.json, which the app (docs/index.html) reads.

Secrets: APIFY_TOKEN (main source), SERPAPI_KEY (backup), BRIGHTDATA_KEY (optional).
Run:  python tracker.py           real run
      python tracker.py --demo    fake data, no keys, for testing the app
      python tracker.py --rebuild only rewrite docs/data.json from the ledger
      python tracker.py --store normandy   scan that store now instead of the next in line
"""

import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
CONFIG = json.loads((ROOT / "config.json").read_text())
DATA = ROOT / "data"
LEDGER = DATA / "ledger.json"
SNAP_DIR = DATA / "snapshots"          # old daily snapshots, used once to seed the ledger
OUT = ROOT / "docs" / "data.json"
SERP = "https://serpapi.com/search.json"
APIFY = "https://api.apify.com/v2"
APIFY_ACTOR = "s_actors~home-depot-scraper"
BRIGHT = "https://api.brightdata.com"
BRIGHT_DATASET = "gd_lmusivh019i7g97q2n"   # Bright Data "Home Depot US"
TZ = ZoneInfo("America/New_York")
PAGE_SIZE = 24


class OutOfSearches(Exception):
    """SerpApi says the monthly or hourly allowance is used up."""


# ---------- small helpers ----------

def today():
    return datetime.now(TZ).date()


def num(v):
    """'$1,234.50' -> 1234.5 ; None/garbage -> None"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace("$", "").replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def days_between(a, b):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return 0


def ending(price):
    return int(round(price * 100)) % 100 if price is not None else None


def clean_link(link, pid):
    """SerpApi sometimes returns an internal host; always send people to the public site."""
    if link and "/p/" in link:
        return "https://www.homedepot.com" + link[link.index("/p/"):].split("?")[0]
    return f"https://www.homedepot.com/p/{pid}"


def stores():
    return [s for s in CONFIG["stores"] if s.get("on", True)]


def load_ledger():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"items": {}, "tokens": {}, "sweeps": {}, "log": []}


# ---------- SerpApi ----------

def serpapi(params):
    params = dict(params, api_key=os.environ["SERPAPI_KEY"])
    url = SERP + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise OutOfSearches("SerpApi free searches are used up")
        raise RuntimeError(f"SerpApi HTTP {e.code}")
    err = data.get("error")
    if err:
        low = err.lower()
        if "run out of searches" in low or "searches limit" in low or "hourly" in low:
            raise OutOfSearches(err)
        if "hasn't returned any results" in low or "no results" in low:
            return {"products": [], "filters": data.get("filters", [])}
        raise RuntimeError(err)
    return data


def find_discount_tokens(data):
    """Look through the filters SerpApi returned and pick the token for the
    deepest 'NN% off or more' filter that meets config min_percent_off."""
    want = CONFIG.get("min_percent_off", 40)
    found = []

    def walk(node):
        if isinstance(node, dict):
            name, token = node.get("name"), node.get("value")
            if isinstance(name, str) and isinstance(token, str) and "%" in name and "off" in name.lower():
                digits = "".join(c for c in name.split("%")[0] if c.isdigit())
                if digits:
                    found.append((int(digits), token))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data.get("filters", []))
    ok = sorted(t for t in found if t[0] >= want)
    if ok:
        return ok[0][1]
    return sorted(found)[-1][1] if found else None


def search(store, dept, token=None):
    params = {"engine": "home_depot", "q": dept, "store_id": store["id"], "ps": PAGE_SIZE}
    if CONFIG.get("min_price"):
        params["lowerbound"] = CONFIG["min_price"]
    if token:
        params["hd_filter_tokens"] = token
        params["hd_sort"] = "price_low_to_high"
    return serpapi(params)


def in_store(p):
    """True = on the shelf at the store, False = online only, None = unknown."""
    pickup = p.get("pickup")
    if not pickup:
        return None
    if isinstance(pickup, dict):
        if pickup.get("quantity") is not None or pickup.get("store_name"):
            return True
        if pickup.get("free_ship_to_store"):
            return False
        return None
    text = str(pickup).lower()
    if "ship to store" in text and "in stock" not in text:
        return False
    return True


def parse_product(p, store, dept):
    pid = str(p.get("product_id") or "")
    price = num(p.get("price"))
    if not pid or price is None:
        return None
    if price < float(CONFIG.get("min_price") or 0):
        return None
    if CONFIG.get("skip_online_only", True) and in_store(p) is False:
        return None
    was = num(p.get("price_was"))
    pct = num(p.get("percentage_off"))
    if pct is None and was and was > price:
        pct = round((was - price) / was * 100)
    pickup = p.get("pickup") if isinstance(p.get("pickup"), dict) else {}
    thumb = ""
    t = p.get("thumbnails") or p.get("thumbnail")
    while isinstance(t, list) and t:
        t = t[0]
    if isinstance(t, str):
        thumb = t
    return {"pid": pid, "store_id": store["id"], "title": p.get("title", ""),
            "brand": p.get("brand", "") or "", "model": p.get("model_number", "") or "",
            "price": price, "was": was if was and was > price else None,
            "pct": int(pct) if pct else None, "badge": p.get("price_badge") or "",
            "qty": num(pickup.get("quantity")), "thumb": thumb,
            "link": clean_link(p.get("link", ""), pid), "dept": dept}


def sweep_store(ledger, store, day):
    """Scan every department at one store. Returns (items_seen, searches_used, per-dept log)."""
    seen, used, log = {}, 0, []
    tokens = ledger.setdefault("tokens", {})
    for dept in CONFIG["searches"]:
        entry = {"dept": dept, "count": 0, "filtered": False, "error": ""}
        try:
            known = tokens.get(dept)
            if isinstance(known, str):               # older format
                known = {"t": known, "on": day}
            if known and days_between(known.get("on", day), day) > 30:
                known = None                         # relearn the filter code monthly
            products = []
            if known:
                token = known["t"]
                products = search(store, dept, token).get("products", [])
                used += 1
            else:
                base = search(store, dept)           # plain search: also tells us the filter codes
                used += 1
                products = list(base.get("products", []))
                token = find_discount_tokens(base)
                if token:
                    tokens[dept] = {"t": token, "on": day}
                    products += search(store, dept, token).get("products", [])
                    used += 1
            data = {"products": products}
            entry["filtered"] = bool(token)
            for p in data.get("products", []):
                item = parse_product(p, store, dept)
                if item:
                    seen[f"{store['id']}:{item['pid']}"] = item
                    entry["count"] += 1
        except OutOfSearches:
            raise
        except Exception as e:
            entry["error"] = str(e)[:140]
        print(f"  {store['name']} / {dept}: {entry['count']} items"
              + (" (discount filter)" if entry["filtered"] else "")
              + (f"  ! {entry['error']}" if entry["error"] else ""))
        log.append(entry)
    return seen, used, log


def update_ledger(ledger, store, seen, dept_log, day):
    items = ledger["items"]
    ok_depts = {d["dept"] for d in dept_log if not d["error"]}
    for key, new in seen.items():
        old = items.get(key)
        if not old:
            old = items[key] = {"first_seen": day, "history": [], "missed": 0}
        hist = old.setdefault("history", [])
        if not hist or hist[-1][1] != new["price"]:
            if hist:
                old["prev_price"], old["price_changed_on"] = hist[-1][1], day
            hist.append([day, new["price"]])
        if (new["pct"] or new.get("clearance")) and not old.get("first_clearance"):
            old["first_clearance"] = day
        if new["was"] is None and old.get("was") and old["was"] > new["price"]:
            new["was"] = old["was"]              # keep the last known regular price
        for k in ("thumb", "brand", "model", "sku", "upc"):
            if not new.get(k) and old.get(k):
                new[k] = old[k]
        old.update(new)
        if old.get("missed"):
            old["returned_on"] = day
        old["last_seen"], old["missed"] = day, 0
    for key, old in items.items():
        if old.get("store_id") == store["id"] and key not in seen \
                and old.get("dept") in ok_depts and old.get("last_seen") != day:
            old["missed"] = old.get("missed", 0) + 1
            if old["missed"] == 1:
                old["missing_since"] = day


# ---------- Apify: store clearance (main source) ----------

def apify(method, path, params=None, body=None):
    url = APIFY + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(
        url, data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={"Authorization": "Bearer " + os.environ["APIFY_TOKEN"].strip(),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def apify_sweep(store):
    """One run = every department at one store, clearance items only.
    Returns (items_seen, dept_log, cost_usd). Raises on failure."""
    cfg = CONFIG.get("apify", {})
    run = apify("POST", f"/acts/{APIFY_ACTOR}/runs",
                {"timeout": 1200, "maxTotalChargeUsd": cfg.get("max_cost_per_run", 0.16)},
                {"mode": "search", "keywords": CONFIG["searches"], "storeIds": [store["id"]],
                 "zipCode": store.get("zip", ""), "maxStores": 1,
                 "maxProductsPerSearch": cfg.get("products_per_department", 480),
                 "onlyClearance": True, "minDiscountPercent": 0,
                 "onlyChanges": False, "maxConcurrency": 3})["data"]
    for _ in range(100):                               # up to ~20 minutes
        time.sleep(12)
        run = apify("GET", f"/actor-runs/{run['id']}")["data"]
        if run.get("status") not in ("READY", "RUNNING"):
            break
    if run.get("status") != "SUCCEEDED":
        raise RuntimeError(f"Apify run ended as {run.get('status')}")
    rows = apify("GET", f"/datasets/{run['defaultDatasetId']}/items", {"limit": 5000, "clean": "true"})
    print(f"  Apify: {len(rows)} rows, cost ${run.get('usageTotalUsd') or 0:.3f}, "
          f"events {json.dumps(run.get('chargedEventCounts'))}")
    if not rows:
        try:
            req = urllib.request.Request(APIFY + f"/actor-runs/{run['id']}/log", headers={
                "Authorization": "Bearer " + os.environ["APIFY_TOKEN"].strip()})
            tail = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace").splitlines()[-12:]
            print("  Apify log tail:\n    " + "\n    ".join(l[:220] for l in tail))
        except Exception:
            pass
    floor = float(CONFIG.get("min_price") or 0)
    seen, counts = {}, {d: 0 for d in CONFIG["searches"]}
    for r in rows:
        pid, price = str(r.get("itemId") or ""), num(r.get("price"))
        if not pid or price is None or r.get("type", "product") != "product":
            continue
        reg = num(r.get("regularPrice"))
        if max(price, reg or 0) < floor:                # skip items that were never worth $10
            continue
        key = f"{store['id']}:{pid}"
        if key in seen:
            continue
        pct = num(r.get("discountPercent"))
        dept = r.get("query") or ""
        seen[key] = {"pid": pid, "store_id": store["id"], "title": r.get("title") or "",
                     "brand": r.get("brand") or "", "model": r.get("model") or "",
                     "sku": str(r.get("storeSku") or ""), "upc": str(r.get("upc") or ""),
                     "price": price, "was": reg if reg and reg > price else None,
                     "pct": int(round(pct)) if pct else None, "badge": "",
                     "qty": num(r.get("storeQuantity")), "thumb": r.get("image") or "",
                     "link": clean_link(r.get("url") or "", pid), "dept": dept,
                     "cat": r.get("department") or "", "clearance": bool(r.get("isClearance")),
                     "source": "apify"}
        counts[dept] = counts.get(dept, 0) + 1
    log = [{"dept": d, "count": counts.get(d, 0), "filtered": True, "error": ""} for d in CONFIG["searches"]]
    for d in log:
        print(f"  {store['name']} / {d['dept']}: {d['count']} clearance items")
    return seen, log, run.get("usageTotalUsd") or 0


# ---------- Bright Data: is it discontinued? ----------

def bright(method, path, params=None, body=None):
    url = BRIGHT + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(
        url, data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={"Authorization": "Bearer " + os.environ["BRIGHTDATA_KEY"].strip(),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def discontinued_candidates(ledger, day):
    """Items worth a discontinued check: deep clearance that has gone missing,
    then the deepest clearance not checked in the last 3 weeks."""
    limit = CONFIG.get("discontinued_checks_per_run", 12)
    pool = []
    for key, it in ledger["items"].items():
        if it.get("discontinued") or not (it.get("pct") or 0) >= 40:
            continue
        last = it.get("disc_checked")
        if last and days_between(last, day) < 21:
            continue
        missing = it.get("missed", 0) >= 2
        pool.append((0 if missing else 1, -(it.get("pct") or 0), key))
    return [k for _, _, k in sorted(pool)[:limit]]


def check_discontinued(ledger, day):
    if not os.environ.get("BRIGHTDATA_KEY", "").strip():
        return "Bright Data key not set", 0
    keys = discontinued_candidates(ledger, day)
    if not keys:
        return "nothing to check", 0
    by_pid = {}
    for k in keys:
        by_pid.setdefault(ledger["items"][k]["pid"], []).append(k)
    inputs = [{"url": ledger["items"][ks[0]]["link"], "zipcode": ""} for ks in by_pid.values()]
    try:
        snap = json.loads(bright("POST", "/datasets/v3/trigger",
                                 {"dataset_id": BRIGHT_DATASET, "include_errors": "true",
                                  "format": "json"}, inputs))["snapshot_id"]
        for _ in range(40):                       # up to 10 minutes
            time.sleep(15)
            status = json.loads(bright("GET", f"/datasets/v3/progress/{snap}")).get("status")
            if status in ("ready", "failed"):
                break
        text = bright("GET", f"/datasets/v3/snapshot/{snap}", {"format": "json"}).strip()
        try:
            rows = json.loads(text)
        except ValueError:
            rows = [json.loads(l) for l in text.splitlines() if l.strip().startswith("{")]
        if isinstance(rows, dict):
            rows = [rows]
    except Exception as e:
        return f"Bright Data problem: {str(e)[:120]}", 0
    done = 0
    for row in rows:
        pid = str(row.get("product_id") or "")
        if not pid or row.get("error") or pid not in by_pid:
            continue
        for k in by_pid[pid]:
            it = ledger["items"][k]
            it["disc_checked"] = day
            if row.get("discontinued") is True:
                it["discontinued"] = True
                it.setdefault("discontinued_on", day)
            if row.get("upc") and not it.get("upc"):
                it["upc"] = str(row["upc"])
            if row.get("sku") and not it.get("sku"):
                it["sku"] = str(row["sku"])
            if not it.get("thumb") and row.get("main_image"):
                it["thumb"] = row["main_image"]
        done += 1
    return f"checked {done} items", done


# ---------- scoring ----------

def score(it, day):
    """0-100: how close this looks to a penny. Returns (score, reasons)."""
    pts, why = 0, []
    pct = it.get("pct") or 0
    if pct:
        pts += min(35, round(pct * 35 / 90))
        why.append(f"{pct}% off")
    start = it.get("first_clearance")
    if start:
        weeks = days_between(start, day) / 7
        pts += min(25, round(weeks * 25 / 12))
        if weeks >= 1:
            why.append(f"{int(weeks)} wk on clearance")
    end = ending(it.get("price"))
    if end in (2, 3):
        pts += 10
        why.append(f"price ends .0{end}")
    elif end in (4, 6):
        pts += 5
        why.append(f"price ends .0{end}")
    if it.get("discontinued"):
        pts += 15
        why.append("discontinued")
    qty = it.get("qty")
    if qty is not None and 1 <= qty <= 5:
        pts += 10
        why.append(f"only {int(qty)} left")
    elif qty == 0 and it.get("clearance"):
        pts += 10
        why.append("system shows 0 left")
    if it.get("price_changed_on") and it.get("prev_price") and it["prev_price"] > it["price"] \
            and days_between(it["price_changed_on"], day) <= 8:
        pts += 5
        why.append("price just dropped")
    return min(100, pts), why


# ---------- output for the app ----------

def write_output(ledger, day, status):
    names = {s["id"]: s["name"] for s in CONFIG["stores"]}
    items = []
    for key, it in ledger["items"].items():
        if it.get("store_id") not in names or it.get("price") is None:
            continue
        sc, why = score(it, day)
        end = ending(it["price"])
        items.append({
            "id": key, "pid": it["pid"], "store_id": it["store_id"],
            "title": it.get("title", ""), "brand": it.get("brand", ""), "model": it.get("model", ""),
            "sku": it.get("sku", ""), "upc": it.get("upc", ""),
            "price": it["price"], "was": it.get("was"), "pct": it.get("pct"),
            "prev_price": it.get("prev_price"), "price_changed_on": it.get("price_changed_on"),
            "ending": end, "qty": it.get("qty"), "thumb": it.get("thumb", ""),
            "link": it.get("link", ""), "dept": it.get("dept", ""), "cat": it.get("cat", ""),
            "clearance": bool(it.get("clearance")), "missing_since": it.get("missing_since") if it.get("missed") else None,
            "first_seen": it.get("first_seen"), "first_clearance": it.get("first_clearance"),
            "last_seen": it.get("last_seen"), "missed": it.get("missed", 0),
            "discontinued": bool(it.get("discontinued")), "discontinued_on": it.get("discontinued_on"),
            "history": it.get("history", [])[-12:], "score": sc, "why": why,
        })
    items.sort(key=lambda x: -x["score"])
    out = {
        "app": "Penny Run",
        "generated_at": datetime.now(TZ).isoformat(timespec="minutes"),
        "status": status,
        "stores": [{"id": s["id"], "name": s["name"], "short": s.get("short", s["name"]),
                    "maps": s.get("maps", ""), "last_scan": ledger.get("sweeps", {}).get(s["id"])}
                   for s in stores()],
        "departments": CONFIG["searches"],
        "log": ledger.get("log", [])[-12:],
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"Wrote {OUT.name}: {len(items)} items")


# ---------- demo data (for testing the app only; never committed by the daily job) ----------

def demo_ledger():
    random.seed(7)
    day = today().isoformat()
    led = {"items": {}, "tokens": {}, "sweeps": {}, "log": []}
    names = ["18V Cordless Drill Kit", "LED Flush Mount Ceiling Light", "Brass Ball Valve 3/4 in.",
             "Garden Hose 50 ft. Heavy Duty", "Smart Dimmer Switch", "Countertop Microwave 1.1 cu. ft.",
             "Tool Bag 16 in.", "Pendant Light Matte Black", "PEX Crimp Tool", "Raised Garden Bed Cedar"]
    for s in stores():
        led["sweeps"][s["id"]] = day
        for i in range(14):
            was = random.choice([19.98, 29.97, 49.97, 79.0, 129.0, 199.0])
            pct = random.choice([None, None, 25, 50, 50, 75, 75, 90])
            price = was if not pct else round(was * (100 - pct) / 100) + random.choice([0.03, 0.06, 0.02, 0.0])
            pid = str(300000000 + i)
            led["items"][f"{s['id']}:{pid}"] = {
                "pid": pid, "store_id": s["id"], "title": f"{names[i % 10]} (demo {i})",
                "brand": random.choice(["RYOBI", "DEWALT", "Husky", "Hampton Bay"]), "model": f"DM-{i:04d}",
                "price": price, "was": was if pct else None, "pct": pct, "badge": "",
                "qty": random.choice([None, 1, 2, 4, 9, 23]), "thumb": "",
                "link": "https://www.homedepot.com", "dept": random.choice(CONFIG["searches"]),
                "first_seen": "2026-08-20", "first_clearance": "2026-09-01" if pct else None,
                "last_seen": day, "missed": random.choice([0, 0, 0, 2]),
                "history": [["2026-08-20", was], [day, price]] if pct else [["2026-08-20", was]],
                "prev_price": was if pct else None, "price_changed_on": day if pct else None,
                "discontinued": pct == 90, "discontinued_on": day if pct == 90 else None}
    led["log"] = [{"date": day, "store": stores()[0]["name"], "searches": 9, "items": 96, "note": "demo data"}]
    return led


# ---------- main ----------

def main():
    day = today().isoformat()
    if "--demo" in sys.argv:
        global OUT
        OUT = Path(sys.argv[sys.argv.index("--demo") + 1]) if len(sys.argv) > sys.argv.index("--demo") + 1 \
            else ROOT / "demo-data.json"
        write_output(demo_ledger(), day, {"ok": True, "note": "Demo data"})
        return

    ledger = load_ledger()
    # October's full-price listings from the old tracker are noise now; keep clearance finds only
    ledger["items"] = {k: v for k, v in ledger["items"].items() if v.get("source") or v.get("pct")}
    if not any(v.get("source") for v in ledger["items"].values()) and not ledger.get("log_v2"):
        ledger["sweeps"], ledger["log"], ledger["log_v2"] = {}, [], True
    status = {"ok": True, "note": ""}
    have_apify = bool(os.environ.get("APIFY_TOKEN", "").strip())
    have_serp = bool(os.environ.get("SERPAPI_KEY", "").strip())

    if "--rebuild" in sys.argv or not (have_apify or have_serp):
        status = ledger.get("last_status") or {"ok": False, "note": "Waiting for the first scan."}
    else:
        order = sorted(stores(), key=lambda s: ledger.get("sweeps", {}).get(s["id"]) or "")
        store = order[0]
        if "--store" in sys.argv:                      # scan one particular store on request
            want = sys.argv[sys.argv.index("--store") + 1].lower()
            picked = [x for x in stores() if want in (x["id"], x["id"].lstrip("0"))
                      or want in x["name"].lower() or want in x.get("short", "").lower()]
            if picked:
                store = picked[0]
        print(f"Scanning {store['name']} ({day})")
        entry = {"date": day, "store": store["name"], "searches": 0, "items": 0, "note": "", "source": ""}
        seen, dept_log, problems = None, [], []
        if have_apify:
            try:
                seen, dept_log, cost = apify_sweep(store)
                entry["source"], entry["cost"] = "Apify", round(cost, 3)
                had = {}
                for v in ledger["items"].values():
                    if v.get("store_id") == store["id"] and not v.get("missed") and v.get("source") == "apify":
                        had[v.get("dept")] = had.get(v.get("dept"), 0) + 1
                if sum(had.values()) >= 5 and len(seen) < sum(had.values()) * 0.25:
                    seen = None                         # the scraper came back (nearly) empty: a bad run
                    raise RuntimeError("scan came back empty, so it was ignored")
                for d in dept_log:                      # a whole department vanishing is a scraper miss
                    if d["count"] == 0 and had.get(d["dept"], 0) >= 3:
                        d["error"] = "came back empty"
            except Exception as e:
                problems.append(f"Apify: {str(e)[:100]}")
                print("  ! " + problems[-1])
        if seen is None and have_serp:
            try:
                seen, entry["searches"], dept_log = sweep_store(ledger, store, day)
                entry["source"] = "SerpApi"
            except OutOfSearches:
                problems.append("SerpApi: out of free searches")
            except Exception as e:
                problems.append(f"SerpApi: {str(e)[:100]}")
        if seen is not None:
            entry["items"] = len(seen)
            update_ledger(ledger, store, seen, dept_log, day)
            ledger.setdefault("sweeps", {})[store["id"]] = day
            bad = [d["dept"] for d in dept_log if d["error"]]
            if bad:
                entry["note"] = "Couldn't read: " + ", ".join(bad)
        else:
            entry["note"] = "; ".join(problems) or "No data source available"
            status = {"ok": False, "note": f"Today's scan of {store['name']} didn't work. "
                                           "It will try again tomorrow."}
            print("  ! " + entry["note"])
        note, _ = check_discontinued(ledger, day)
        entry["discontinued_check"] = note
        print("  Discontinued check:", note)
        ledger.setdefault("log", []).append(entry)
        ledger["log"] = ledger["log"][-60:]
        ledger["last_status"] = status

    DATA.mkdir(exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, separators=(",", ":")))
    write_output(ledger, day, status)


if __name__ == "__main__":
    main()
