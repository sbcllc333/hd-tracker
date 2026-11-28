"""Daily deep-clearance feed for the Home Depot stores in config.json.

Where the data comes from
-------------------------
Home Depot blocks plain scripts (and GitHub's servers) from its own site, so the
feed uses the same source that produced the old app's 50-99% off items: the
"Home Depot Scraper" actor on Apify (s_actors~home-depot-scraper). It returns
Home Depot's own store-level data: clearance price, was price, % off, store SKU,
UPC and units on the shelf for one store.

Cost: Apify's Free plan gives $5 of credit every month with no card. When it is
used up, runs stop until next month instead of billing. This module also checks
the month's usage first and stops at config feed.monthly_budget_usd (default
$4.50), and every run has a hard maxTotalChargeUsd cap.

No APIFY_TOKEN secret, or the credit is used up: nothing is fetched, and the app
keeps showing the last real scan with its date. Nothing is ever made up.

Files
-----
data/feed.json   ledger: every deep-clearance item per store, first/last seen,
                 price history, and per-store scan dates. Seeded once from the
                 old app's data/ledger.json (its real Apify scans of Nov 12-17).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FEED_PATH = DATA / "feed.json"
OLD_LEDGER = DATA / "ledger.json"
APIFY = "https://api.apify.com/v2"

DEFAULTS = {
    "source": "apify",
    "actor": "s_actors~home-depot-scraper",
    "min_pct": 50,
    "max_age_days": 14,
    "stores_per_day": 2,
    "monthly_budget_usd": 4.5,
    "max_cost_per_store_usd": 0.2,
    # Home Depot's "In-Store Clearance" refinement (all departments). Cheap: only
    # clearance items are paged through. If it comes back empty, the keywords
    # below are scanned instead (the old app's proven setup).
    "category_urls": ["https://www.homedepot.com/b/N-5yc1vZbwo6v"],
    "keywords": ["tools", "garden", "electrical", "lighting", "plumbing", "appliances", "storage"],
    "per_search": 480,
    "per_category": 744,
}


def settings(cfg: dict) -> dict:
    out = dict(DEFAULTS)
    out.update(cfg.get("feed") or {})
    return out


def _num(v):
    if v is None or isinstance(v, bool) or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace("$", "").replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _days(a: str, b: str) -> int:
    try:
        return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days
    except (TypeError, ValueError):
        return 10 ** 6


def pct_off(price, was, given=None):
    """Percent off, from the row's own figure or computed from was/price."""
    g = _num(given)
    if g is not None and g > 0:
        return int(round(g))
    price, was = _num(price), _num(was)
    if price is None or not was or was <= price:
        return 0
    return int(round((was - price) / was * 100))


def price_ending(price) -> str:
    """Last two cents digits as '.03', or '' when there is no price."""
    p = _num(price)
    if p is None:
        return ""
    return "." + f"{int(round(p * 100)) % 100:02d}"


def stepped_down(history) -> bool:
    """True if this store's price went down at least once while we watched it."""
    prices = [h[1] for h in (history or []) if isinstance(h, (list, tuple)) and len(h) == 2 and h[1] is not None]
    return any(b < a for a, b in zip(prices, prices[1:]))


def penny_stage(price, pct=None, history=None) -> str:
    """Home Depot never shows $0.01 online, so the data can only flag candidates.

    'penny' - $0.01 total in the store data (never seen so far; only the register shows it)
    'late'  - late clearance, trip-worthy: 75%+ off or under $1, AND either a markdown we saw
              (a prior step-down) or 90%+ off (85%+ items almost never get cut again, so they
              are at the last step). Price endings (.02/.03/.06) never tag on their own.
    ''      - anything else
    """
    p = _num(price)
    if p is None:
        return ""
    cents = int(round(p * 100))
    if cents <= 1:
        return "penny"
    pct = int(pct or 0)
    if (pct >= 75 or p < 1) and (stepped_down(history) or pct >= 90):
        return "late"
    return ""


def penny_signals(d: dict) -> tuple[str, int, list[str]]:
    """(stage, sort score, reasons) for one store item.

    stage 'penny'  $0.01 in the store data
          'hidden' dropped off this store's clearance list after a deep-clearance price
                   (the best online sign of a penny / hidden price; or it sold out)
          'late'   late clearance, trip-worthy (see penny_stage)
          'weak'   0 in stock online with a clearance history (often sold out)
          ''       plain deep clearance
    """
    p = _num(d.get("price"))
    pct = int(d.get("pct") or 0)
    why: list[str] = []
    if p is None:
        return "", 0, why
    base = penny_stage(p, pct, d.get("history"))
    if base == "penny":
        return "penny", 100, ["$0.01 in Home Depot's store data"]
    score = 0
    if d.get("gone_on"):
        score += 60
        why.append(f"dropped off this store's clearance list {d['gone_on']} after {money_s(p)} ({pct}% off)")
    if base == "late":
        score += 40
        if stepped_down(d.get("history")):
            score += 15
            why.append("marked down again while we watched")
        if pct >= 90:
            score += 10
            why.append(f"{pct}% off, the last markdown step")
        elif pct >= 75:
            why.append(f"{pct}% off")
        if p < 1:
            score += 10
            why.append("under $1")
    if d.get("qty") == 0:
        score -= 10
        why.append("0 in stock online: likely sold out (penny items also get zeroed)")
    elif (d.get("qty") or 0) > 0:
        score += 5
    if price_ending(p) in (".02", ".03", ".06"):
        score += 1                                  # tiebreak only, never a tag
    if d.get("gone_on"):
        stage = "hidden"
    elif base == "late":
        stage = "late"
    elif d.get("qty") == 0:
        stage = "weak"
    else:
        stage = ""
    return stage, max(0, min(score, 99)), why


def money_s(p) -> str:
    return "$" + f"{p:,.2f}"


# Home Depot's ~100 raw category names rolled up to the departments Paul shops by.
# First match wins, so the specific words come before the broad ones.
DEPT_RULES = [
    ("Appliances", ("refrigerator", "freezer", "range hood", "microwave", "washing machine", "dryer", "dishwasher",
                    "beverage", "wine", "appliance", "oven", "cooktop")),
    ("Plumbing", ("water heater", "drain", "faucet", "toilet", "sink", "plumb", "brass fitting", "pipe", "pump",
                  "water filter", "shower")),
    ("Lighting", ("light", "lamp", "bulb", "sconce", "chandelier", "ceiling fan", "lantern")),
    ("Electrical", ("smoke", "carbon monoxide", "circuit", "breaker", "outlet", "switch", "generator", "wire",
                    "electrical", "solar", "extension cord", "doorbell", "ups ")),
    ("Garden", ("plant", "planter", "garden", "lawn", "grass", "weed", "insect", "sprinkler", "hose", "landscap",
                "mower", "grow media", "fertiliz", "pruning", "rake", "trap", "outdoor power", "sprayer", "rocks",
                "mulch", "soil", "seed", "bed bug", "pest", "chinch", "grub")),
    ("Paint", ("paint", "stain", "primer", "caulk", "brush", "roller", "spray paint")),
    ("Tools", ("saw", "drill", "driver", "wrench", "grinder", "sander", "nailer", "hammer", "compressor", "level",
               "tool", "jobsite", "workbench", "planer", "router", "staple", "clamp", "nibbler", "shear",
               "multi-tool", "vacuum", "battery", "batteries", "bit", "blade")),
    ("Hardware", ("hook", "storage", "cabinet", "organizer", "shelf", "shelving", "fire extinguisher", "lock",
                  "hinge", "fastener", "screw", "bolt", "anchor", "ladder", "safe", "fence")),
]
DEPT_GROUPS = [g for g, _ in DEPT_RULES] + ["Other"]


def dept_group(dept: str, title: str = "") -> str:
    d = (dept or "").lower()
    for text in (d, (title or "").lower()):
        if not text:
            continue
        for group, words in DEPT_RULES:
            if any(w in text for w in words):
                return group
    return "Other"


def clean_link(link: str, pid: str) -> str:
    if link and "/p/" in link:
        return "https://www.homedepot.com" + link[link.index("/p/"):].split("?")[0]
    return f"https://www.homedepot.com/p/{pid}" if pid else ""


def parse_row(r: dict, store_id: str) -> dict | None:
    """One Apify row -> one feed item, or None if it is not usable."""
    if r.get("type", "product") != "product":
        return None
    pid = str(r.get("itemId") or "").strip()
    price = _num(r.get("clearancePrice") if r.get("clearancePrice") not in (None, "") else r.get("price"))
    if not pid or price is None:
        return None
    was = _num(r.get("regularPrice"))
    if was is not None and was <= price:
        was = None
    aisle = r.get("aisle") or r.get("aisleBay") or ""
    bay = r.get("bay") or ""
    if isinstance(aisle, dict):
        aisle, bay = aisle.get("aisle") or "", aisle.get("bay") or bay
    qty = _num(r.get("storeQuantity"))
    return {
        "pid": pid,
        "store_id": str(r.get("storeId") or store_id).zfill(4) if str(r.get("storeId") or store_id).isdigit() else store_id,
        "title": str(r.get("title") or "").strip(),
        "brand": str(r.get("brand") or "").strip(),
        "model": str(r.get("model") or "").strip(),
        "sku": str(r.get("storeSku") or "").strip(),
        "upc": str(r.get("upc") or "").strip(),
        "price": price,
        "was": was,
        "pct": pct_off(price, was, r.get("discountPercent")),
        "qty": int(qty) if qty is not None else None,
        "thumb": str(r.get("image") or ""),
        "link": clean_link(str(r.get("url") or ""), pid),
        "dept": str(r.get("department") or r.get("query") or ""),
        "aisle": str(aisle or ""),
        "bay": str(bay or ""),
        "clearance": bool(r.get("isClearance", True)),
    }


# ---------- ledger ----------

def empty_feed() -> dict:
    return {"version": 1, "items": {}, "scans": {}, "log": [], "credit": None, "gone": {}}


def load_feed(path: Path | None = None) -> dict:
    path = path or FEED_PATH
    if path.exists() and path.read_text().strip():
        feed = json.loads(path.read_text())
        for k, v in empty_feed().items():
            feed.setdefault(k, v)
        return feed
    return empty_feed()


def save_feed(feed: dict, path: Path | None = None) -> None:
    path = path or FEED_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    feed["log"] = feed.get("log", [])[-60:]
    path.write_text(json.dumps(feed, separators=(",", ":"), ensure_ascii=False) + "\n")


def seed_from_old_ledger(feed: dict, old_path: Path | None = None) -> int:
    """Copy the old app's real Apify store scans (Home Depot only) into the feed once."""
    old_path = old_path or OLD_LEDGER
    if feed.get("seeded") or not old_path.exists():
        return 0
    old = json.loads(old_path.read_text())
    n = 0
    for key, v in (old.get("items") or {}).items():
        if v.get("source") != "apify" or v.get("missed") or not str(v.get("store_id", "")).isdigit():
            continue
        item = {
            "pid": str(v.get("pid") or ""), "store_id": v["store_id"], "title": v.get("title") or "",
            "brand": v.get("brand") or "", "model": v.get("model") or "", "sku": str(v.get("sku") or ""),
            "upc": str(v.get("upc") or ""), "price": _num(v.get("price")), "was": _num(v.get("was")),
            "pct": pct_off(v.get("price"), v.get("was"), v.get("pct")),
            "qty": int(v["qty"]) if isinstance(v.get("qty"), (int, float)) else None,
            "thumb": v.get("thumb") or "", "link": v.get("link") or "", "dept": v.get("cat") or v.get("dept") or "",
            "aisle": "", "bay": "", "clearance": True,
            "first_seen": v.get("first_clearance") or v.get("first_seen") or v.get("last_seen"),
            "last_seen": v.get("last_seen") or v.get("first_seen"),
            "history": [h for h in (v.get("history") or []) if isinstance(h, list) and len(h) == 2],
            "via": "old app scan",
        }
        if not item["pid"] or item["price"] is None:
            continue
        feed["items"][f"{item['store_id']}:{item['pid']}"] = item
        sid = item["store_id"]
        last = feed["scans"].get(sid, {}).get("date") or ""
        if (item["last_seen"] or "") > last:
            feed["scans"][sid] = {"date": item["last_seen"], "ok": True, "rows": 0, "source": "old app scan (Apify)"}
        n += 1
    for sid, sc in feed["scans"].items():
        sc["rows"] = sum(1 for it in feed["items"].values() if it["store_id"] == sid and it["last_seen"] == sc["date"])
    feed["seeded"] = True
    return n


def merge_scan(feed: dict, store_id: str, rows: list[dict], day: str, source: str, cost: float = 0.0,
               complete: bool = True) -> dict:
    """Apply one scan of one store. After a complete scan, items of that store not in it are
    dropped (sold out, back to full price, or pulled). A partial scan (stopped by the cost cap)
    only adds and updates."""
    seen = {}
    for it in rows:
        if it and it["store_id"] == store_id:
            seen[f"{store_id}:{it['pid']}"] = it
    dropped = 0
    gone = feed.setdefault("gone", {})
    for key in [k for k, v in feed["items"].items() if v["store_id"] == store_id]:
        if complete and key not in seen:
            old = feed["items"].pop(key)
            dropped += 1
            # A deep-clearance item that vanishes from the store's clearance list is the classic
            # penny sign (penny items get pulled from the system), or it simply sold out.
            if (old.get("pct") or 0) >= 70:
                gone[key] = dict(old, gone_on=day)
    for key in seen:
        gone.pop(key, None)
    for key in [k for k, v in gone.items() if _days(v.get("gone_on") or "", day) > 28]:
        del gone[key]
    added = 0
    for key, new in seen.items():
        old = feed["items"].get(key)
        hist = list((old or {}).get("history") or [])
        if not hist or hist[-1][1] != new["price"]:
            hist.append([day, new["price"]])
        if not old:
            added += 1
        feed["items"][key] = dict(new, first_seen=(old or {}).get("first_seen") or day, last_seen=day,
                                  history=hist[-12:], via=source)
    feed["scans"][store_id] = {"date": day, "ok": True, "rows": len(seen), "source": source, "cost": round(cost, 4),
                               "complete": complete}
    return {"kept": len(seen), "new": added, "dropped": dropped}


# ---------- Apify ----------

class BudgetUsed(Exception):
    pass


def apify(method: str, path: str, params=None, body=None, token: str | None = None):
    token = (token or os.environ.get("APIFY_TOKEN", "")).strip()
    url = APIFY + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def month_usage(call=apify, day: str | None = None):
    """(used, cap, days_left_in_cycle) for the Apify account."""
    lim = call("GET", "/users/me/limits")["data"]
    used = (lim.get("current") or {}).get("monthlyUsageUsd")
    cap = (lim.get("limits") or {}).get("maxMonthlyUsageUsd")
    end = ((lim.get("monthlyUsageCycle") or {}).get("endAt") or "")[:10]
    left = None
    if day:
        if not end:
            d = date.fromisoformat(day)
            nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
            end = nxt.isoformat()
        left = max(1, _days(day, end))
    month_usage.renews = end or None
    return (float(used) if used is not None else None), (float(cap) if cap is not None else None), left


def apify_run(s: dict, store: dict, body_extra: dict, cap_usd: float, call=apify, sleep=time.sleep):
    body = {"mode": "search", "storeIds": [store["id"]], "zipCode": store.get("zip", ""), "maxStores": 1,
            "onlyClearance": True, "minDiscountPercent": int(s["min_pct"]), "onlyChanges": False,
            "maxConcurrency": 3}
    body.update(body_extra)
    run = call("POST", f"/acts/{s['actor']}/runs", {"timeout": 2400, "maxTotalChargeUsd": round(cap_usd, 3)}, body)["data"]
    for _ in range(200):
        if run.get("status") not in ("READY", "RUNNING"):
            break
        sleep(12)
        run = call("GET", f"/actor-runs/{run['id']}")["data"]
    if run.get("status") != "SUCCEEDED":
        raise RuntimeError(f"Apify run ended as {run.get('status')}")
    rows = call("GET", f"/datasets/{run['defaultDatasetId']}/items", {"limit": 10000, "clean": "true"})
    return rows, float(run.get("usageTotalUsd") or 0)


def scan_store(s: dict, store: dict, call=apify, sleep=time.sleep):
    """Category pass first (cheap), keywords if that returns nothing.
    Returns (items, cost, how, complete) - complete is False if a run hit its cost cap."""
    cap = float(s["max_cost_per_store_usd"])
    rows, cost, how, complete = [], 0.0, "", True
    if s.get("category_urls"):
        rows, cost = apify_run(s, store, {"categoryUrls": s["category_urls"], "maxProductsPerSearch": int(s["per_category"])},
                               cap, call, sleep)
        how, complete = "In-Store Clearance pages", cost < cap * 0.95
    if not rows and s.get("keywords") and cap - cost > 0.02:
        more, c2 = apify_run(s, store, {"keywords": s["keywords"], "maxProductsPerSearch": int(s["per_search"])},
                             cap - cost, call, sleep)
        rows, how, complete = more, "department searches", c2 < (cap - cost) * 0.95
        cost += c2
    items = [x for x in (parse_row(r, store["id"]) for r in rows) if x and x["pct"] >= int(s["min_pct"])]
    return items, cost, how, complete


def pick_stores(feed: dict, stores: list[dict], n: int) -> list[dict]:
    hd = [x for x in stores if x.get("retailer", "homedepot") == "homedepot"]
    return sorted(hd, key=lambda x: (feed["scans"].get(x["id"], {}).get("date") or "", x["id"]))[:max(0, n)]


def update(feed: dict, cfg: dict, stores: list[dict], day: str, call=apify, sleep=time.sleep,
           token: str | None = None, only: list[str] | None = None) -> dict:
    """Run today's scans. Returns a status dict {ok, note}. Never raises on network trouble."""
    s = settings(cfg)
    token = os.environ.get("APIFY_TOKEN", "") if token is None else token
    if not token.strip():
        note = "No APIFY_TOKEN secret, so nothing new was fetched today. Showing the last real scan."
        feed["log"].append({"date": day, "store": "Feed", "items": 0, "note": note, "source": "none"})
        return {"ok": False, "note": note}
    try:
        used, cap, days_left = month_usage(call, day)
        feed["credit"] = {"used": used, "cap": cap, "on": day, "renews": getattr(month_usage, "renews", None)}
    except Exception as e:  # noqa: BLE001
        used, cap, days_left = None, None, None
        print("Apify credit check failed:", str(e)[:120])
    budget = float(s["monthly_budget_usd"])
    if cap is not None:
        budget = min(budget, cap - 0.3)
    per_store = float(s["max_cost_per_store_usd"])
    # spread what is left of the month's free credit evenly over the days left
    allowance = None
    if used is not None and days_left:
        allowance = max(per_store, (budget - used) / days_left)
    targets = [x for x in stores if x["id"] in only] if only else pick_stores(feed, stores, int(s["stores_per_day"]))
    notes, ok, spent = [], True, 0.0
    for store in targets:
        if used is not None and used + per_store > budget:
            renews = (feed.get("credit") or {}).get("renews")
            notes.append("This month's free Apify credit is used up"
                         + (f" (renews {renews})" if renews else "")
                         + ", so store prices are from each store's last scan. The community penny list still updates daily.")
            ok = False
            break
        if allowance is not None and not only and spent and spent + per_store > allowance:
            break                                   # today's share of the free credit is spent
        try:
            items, cost, how, complete = scan_store(s, store, call, sleep)
            if not items and not how:
                raise RuntimeError("no search set up")
            spent += cost
            res = merge_scan(feed, store["id"], items, day, "Home Depot store data via Apify", cost, complete)
            if used is not None:
                used += cost
            line = f"{res['kept']} items {s['min_pct']}%+ off ({res['new']} new, {res['dropped']} gone) from {how}, ${cost:.3f}"
            feed["log"].append({"date": day, "store": store.get("short") or store["name"], "items": res["kept"],
                                "note": line, "source": "Apify"})
            print(f"  {store['name']}: {line}")
        except Exception as e:  # noqa: BLE001
            ok = False
            msg = str(e)[:160]
            feed["log"].append({"date": day, "store": store.get("short") or store["name"], "items": 0,
                                "note": "Scan failed: " + msg, "source": "Apify"})
            notes.append(f"{store.get('short') or store['name']} scan failed today; showing its last scan.")
            print(f"  {store['name']}: scan failed: {msg}")
    if feed.get("credit") is not None and used is not None:
        feed["credit"]["used"] = round(used, 3)
    return {"ok": ok, "note": " ".join(notes)}


# ---------- output ----------

def deals_for_output(feed: dict, cfg: dict, stores: list[dict], day: str) -> tuple[list[dict], dict]:
    """Every item from each store's latest real scan. Old scans are never hidden (an empty app looks
    broken); items older than max_age_days are flagged 'stale' so the app can show their date."""
    s = settings(cfg)
    ids = {x["id"] for x in stores if x.get("retailer", "homedepot") == "homedepot"}
    out = []
    keys = ("pid", "store_id", "title", "brand", "model", "sku", "upc", "price", "was",
            "pct", "qty", "thumb", "link", "dept", "aisle", "bay", "first_seen", "last_seen", "history")

    def emit(it, gone_on=None):
        d = {k: it.get(k) for k in keys}
        d["history"] = (d.get("history") or [])[-6:]
        d["id"] = f"hd-{it['store_id']}-{it['pid']}"
        d["ending"] = price_ending(it.get("price"))
        d["group"] = dept_group(it.get("dept") or "", it.get("title") or "")
        d["age"] = _days(it.get("last_seen") or "", day)
        d["stale"] = d["age"] > int(s["max_age_days"])
        if gone_on:
            d["gone_on"] = gone_on
        out.append(d)

    for it in feed["items"].values():
        if it["store_id"] in ids and (it.get("pct") or 0) >= int(s["min_pct"]):
            emit(it)
    for it in (feed.get("gone") or {}).values():
        if it["store_id"] in ids:
            emit(it, it.get("gone_on"))
    out.sort(key=lambda d: (-(d["pct"] or 0), d["price"] if d["price"] is not None else 1e9, d["store_id"]))
    per = {}
    for x in stores:
        if x["id"] in ids:
            sc = feed["scans"].get(x["id"]) or {}
            per[x["id"]] = {"last_scan": sc.get("date"), "count": sum(1 for d in out if d["store_id"] == x["id"])}
    meta = {"min_pct": int(s["min_pct"]), "max_age_days": int(s["max_age_days"]), "stores": per,
            "source": "Home Depot store clearance data (via the Apify Home Depot actor, free plan)",
            "credit": feed.get("credit")}
    return out, meta


def apply_penny(deals: list[dict]) -> None:
    for d in deals:
        d["stage"], d["penny_score"], d["why"] = penny_signals(d)


def cost_plan(cfg: dict, stores: list[dict]) -> dict:
    """The $0 math (Paul's rule 5): scans a month x hard cap per scan must stay under the free credit."""
    s = settings(cfg)
    n = len([x for x in stores if x.get("retailer", "homedepot") == "homedepot"])
    per_day = int(s["stores_per_day"])
    scans = per_day * 30
    cap = float(s["max_cost_per_store_usd"])
    worst = round(scans * cap, 2)
    return {"stores": n, "scans_per_month": scans, "cap_per_scan": cap, "worst_case_usd": worst,
            "budget_usd": float(s["monthly_budget_usd"]), "free_credit_usd": 5.0,
            "every_n_days": round(n / per_day, 1) if per_day else None,
            "fits": worst <= float(s["monthly_budget_usd"])}
