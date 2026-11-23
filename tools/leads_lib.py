"""Shared lead and trip-log helpers. No paid APIs, no network calls."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LEADS_PATH = DATA / "leads.json"
CONFIG_PATH = ROOT / "config.json"
OUT_PATH = ROOT / "docs" / "data.json"
TZ = ZoneInfo("America/New_York")

SOURCES = ("community", "my_trip")
MARKS = ("found", "gone", "full", "penny")
MARK_LABELS = {
    "found": "Found",
    "gone": "Not there",
    "full": "Full price",
    "penny": "Rang up 1¢",
}


def today() -> str:
    return datetime.now(TZ).date().isoformat()


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="minutes")


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def walmart_enabled(cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    return bool(cfg.get("walmart_enabled"))


def active_stores(cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_config()
    wm = walmart_enabled(cfg)
    out = []
    for s in cfg["stores"]:
        retailer = s.get("retailer", "homedepot")
        if retailer == "walmart" and not wm:
            continue
        if not s.get("on", True):
            continue
        out.append(s)
    return out


def empty_book() -> dict:
    return {"version": 1, "leads": [], "trips": []}


def load_book(path: Path | None = None) -> dict:
    path = path or LEADS_PATH
    if not path.exists() or not path.read_text().strip():
        return empty_book()
    data = json.loads(path.read_text())
    if isinstance(data, list):
        data = {"version": 1, "leads": data, "trips": []}
    data.setdefault("version", 1)
    data.setdefault("leads", [])
    data.setdefault("trips", [])
    return data


def save_book(book: dict, path: Path | None = None) -> None:
    path = path or LEADS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book, indent=2, ensure_ascii=False) + "\n")


def new_id() -> str:
    return "ld_" + uuid.uuid4().hex[:10]


def clean_sku(v) -> str:
    return re.sub(r"\s+", "", str(v or "")).strip()


def clean_upc(v) -> str:
    return re.sub(r"[^0-9]", "", str(v or "")).strip()


def num_price(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def store_ids(stores) -> list[str]:
    if not stores:
        return []
    if isinstance(stores, str):
        stores = [s.strip() for s in stores.split(",") if s.strip()]
    return [str(s) for s in stores if s]


def normalize_lead(raw: dict, default_source: str = "community") -> dict:
    sku = clean_sku(raw.get("sku"))
    upc = clean_upc(raw.get("upc"))
    name = str(raw.get("name") or raw.get("title") or "").strip()
    if not sku and not upc and not name:
        raise ValueError("A lead needs a SKU, a UPC, or a name.")
    source = (raw.get("source") or default_source).strip()
    if source not in SOURCES:
        raise ValueError(f"source must be community or my_trip, not {source!r}")
    reported = raw.get("reported_at") or raw.get("date") or today()
    # allow datetime; keep the date part
    reported = str(reported)[:10]
    try:
        date.fromisoformat(reported)
    except ValueError:
        raise ValueError(f"reported_at must be YYYY-MM-DD, not {reported!r}")
    price = num_price(raw.get("reported_price") if "reported_price" in raw else raw.get("price"))
    lead = {
        "id": str(raw.get("id") or new_id()),
        "sku": sku,
        "upc": upc,
        "name": name,
        "stores": store_ids(raw.get("stores") if "stores" in raw else raw.get("store")),
        "source": source,
        "reported_price": price,
        "reported_at": reported,
        "confirmed_at_register": bool(raw.get("confirmed_at_register")),
        "notes": str(raw.get("notes") or "").strip(),
    }
    if raw.get("retailer"):
        lead["retailer"] = raw["retailer"]
    if raw.get("preview"):
        lead["preview"] = True
    return lead


def normalize_trip(raw: dict) -> dict:
    lead_id = str(raw.get("lead_id") or raw.get("id") or "").strip()
    mark = str(raw.get("mark") or raw.get("val") or "").strip()
    if not lead_id:
        raise ValueError("A trip mark needs lead_id.")
    if mark not in MARKS:
        raise ValueError(f"mark must be one of {MARKS}, not {mark!r}")
    day = str(raw.get("date") or today())[:10]
    date.fromisoformat(day)
    store = str(raw.get("store_id") or raw.get("store") or "").strip()
    return {"lead_id": lead_id, "store_id": store, "mark": mark, "date": day}


def upsert_lead(book: dict, lead: dict) -> dict:
    lead = normalize_lead(lead)
    for i, existing in enumerate(book["leads"]):
        if existing.get("id") == lead["id"]:
            book["leads"][i] = lead
            return lead
        # same SKU+UPC+stores from a paste is an update, not a duplicate
        if (lead["sku"] or lead["upc"]) and existing.get("sku") == lead["sku"] and existing.get("upc") == lead["upc"] \
                and store_ids(existing.get("stores")) == lead["stores"] and existing.get("source") == lead["source"]:
            lead["id"] = existing["id"]
            if existing.get("confirmed_at_register"):
                lead["confirmed_at_register"] = True
            book["leads"][i] = lead
            return lead
    book["leads"].append(lead)
    return lead


def add_trip(book: dict, trip: dict) -> dict:
    trip = normalize_trip(trip)
    # one mark per lead+store+date: later tap replaces the same trip
    key = (trip["lead_id"], trip["store_id"], trip["date"])
    for i, existing in enumerate(book["trips"]):
        if (existing.get("lead_id"), existing.get("store_id") or "", existing.get("date")) == key:
            book["trips"][i] = trip
            return trip
    book["trips"].append(trip)
    return trip


def trips_for(book: dict, lead_id: str) -> list[dict]:
    return [t for t in book["trips"] if t.get("lead_id") == lead_id]


def latest_trip(trips: list[dict]) -> dict | None:
    if not trips:
        return None
    return max(trips, key=lambda t: (t.get("date") or "", MARKS.index(t["mark"]) if t.get("mark") in MARKS else 0))


def not_there_dates(trips: list[dict]) -> set[str]:
    return {t["date"] for t in trips if t.get("mark") == "gone" and t.get("date")}


def is_demoted(trips: list[dict], confirmed: bool = False) -> bool:
    """Two or more Not-there trips, unless a later trip found it or rang a penny."""
    if confirmed:
        return False
    if len(not_there_dates(trips)) < 2:
        return False
    last = latest_trip(trips)
    if last and last.get("mark") in ("found", "penny"):
        return False
    return True


def is_confirmed(lead: dict, trips: list[dict]) -> bool:
    if lead.get("confirmed_at_register"):
        return True
    return any(t.get("mark") == "penny" for t in trips)


def search_link(lead: dict) -> str:
    q = lead.get("sku") or lead.get("upc") or lead.get("name") or ""
    if not q:
        return ""
    retailer = lead.get("retailer") or "homedepot"
    if retailer == "walmart":
        return "https://www.walmart.com/search?q=" + q
    return "https://www.homedepot.com/s/" + q


def parse_paste(text: str, default_source: str = "community") -> list[dict]:
    """Parse a pasted list of SKUs and prices.

    Accepted lines (comma, tab, or 2+ spaces):
      SKU, 0.01, optional name, optional notes
      SKU  0.01  name
      UPC, $0.01, name
    Lines starting with # are comments. A header row is skipped.
    """
    leads = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"(?i)^(sku|upc|item)\b", line) and not re.search(r"\d{3,}", line):
            continue
        if "," in line:
            parts = [p.strip() for p in line.split(",")]
        elif "\t" in line:
            parts = [p.strip() for p in line.split("\t")]
        else:
            parts = re.split(r"\s{2,}|\s+(?=\$|\d+\.\d{2}\b)", line, maxsplit=3)
            parts = [p.strip() for p in parts if p.strip()]
        if len(parts) < 1:
            continue
        token, rest = parts[0], parts[1:]
        price = num_price(rest[0]) if rest else None
        if price is None and rest:
            # maybe column 1 is name and there is no price
            name = ", ".join(rest)
            notes = ""
        else:
            name = rest[1] if len(rest) > 1 else ""
            notes = ", ".join(rest[2:]) if len(rest) > 2 else ""
        digits = clean_upc(token)
        sku, upc = "", ""
        if digits and len(digits) in (12, 13) and digits == re.sub(r"[^0-9]", "", token):
            upc = digits
        else:
            sku = clean_sku(token)
        leads.append(normalize_lead({
            "sku": sku, "upc": upc, "name": name, "reported_price": price,
            "notes": notes, "source": default_source, "stores": [],
        }))
    return leads


def lead_sort_key(item: dict, preferred_stores: list[str]) -> tuple:
    demoted = 1 if item.get("demoted") else 0
    confirmed = 0 if item.get("confirmed") else 1
    recency = item.get("reported_at") or ""
    stores = item.get("stores") or []
    if any(s in preferred_stores for s in stores):
        mine = 0
    elif not stores:
        mine = 1
    else:
        mine = 2
    return (demoted, confirmed, recency, mine)


def apply_trips(lead: dict, trips: list[dict]) -> dict:
    confirmed = is_confirmed(lead, trips)
    if confirmed:
        lead = dict(lead)
        lead["confirmed_at_register"] = True
    out = dict(lead)
    out["confirmed"] = confirmed
    out["demoted"] = is_demoted(trips, confirmed)
    out["not_there_count"] = len(not_there_dates(trips))
    out["trips"] = sorted(trips, key=lambda t: t.get("date") or "", reverse=True)
    out["title"] = lead.get("name") or lead.get("sku") or lead.get("upc") or "Untitled find"
    out["price"] = lead.get("reported_price")
    out["link"] = search_link(lead)
    out["store_id"] = (lead.get("stores") or [""])[0]
    out["retailer"] = lead.get("retailer") or "homedepot"
    return out


def build_output(book: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    stores = active_stores(cfg)
    ids = {s["id"] for s in stores}
    preferred = [s["id"] for s in stores]
    items = []
    for raw in book["leads"]:
        lead = normalize_lead(raw)
        if lead.get("retailer") == "walmart" and not walmart_enabled(cfg):
            continue
        # drop stores that are switched off, but keep unassigned leads
        lead["stores"] = [s for s in lead["stores"] if s in ids] or lead["stores"]
        item = apply_trips(lead, trips_for(book, lead["id"]))
        items.append(item)
    items.sort(key=lambda i: lead_sort_key(i, preferred)[0:2] + (-_ord(i.get("reported_at")), lead_sort_key(i, preferred)[3]))
    # recency descending — handle in helper
    items.sort(key=lambda i: item_sort(i, preferred))
    status = {"ok": True, "note": ""}
    return {
        "app": "Penny Run",
        "mode": "leads",
        "generated_at": now_iso(),
        "status": status,
        "stores": [
            {
                "id": s["id"],
                "name": s["name"],
                "short": s.get("short", s["name"]),
                "maps": s.get("maps", ""),
                "retailer": s.get("retailer", "homedepot"),
            }
            for s in stores
        ],
        "walmart_enabled": walmart_enabled(cfg),
        "items": items,
        "trips": book.get("trips", []),
        "log": [{
            "date": today(),
            "store": "Lead book",
            "items": len(items),
            "note": f"Built {len(items)} leads from data/leads.json. No paid data sources.",
            "source": "local",
        }],
    }


def _ord(day: str | None) -> int:
    try:
        return date.fromisoformat((day or "")[:10]).toordinal()
    except ValueError:
        return 0


def item_sort(item: dict, preferred: list[str]) -> tuple:
    demoted, confirmed, recency, mine = lead_sort_key(item, preferred)
    return (demoted, confirmed, -_ord(recency), mine)


def write_output(book: dict | None = None, path: Path | None = None) -> dict:
    book = book if book is not None else load_book()
    out = build_output(book)
    dest = path or OUT_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    return out
