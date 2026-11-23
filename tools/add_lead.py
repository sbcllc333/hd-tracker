#!/usr/bin/env python3
"""Add a lead to data/leads.json, or import a pasted SKU list / JSON backup.

Examples:
  python tools/add_lead.py --sku 564-184 --price 0.01 --name "Wire shelf" --store 0275 --source community
  python tools/add_lead.py --paste-file pasted.txt --source community
  python tools/add_lead.py --import-json backup.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from leads_lib import (
    LEADS_PATH, load_book, save_book, upsert_lead, parse_paste, write_output, today,
)


def main(argv=None):
    p = argparse.ArgumentParser(description="Add a penny lead to the local book.")
    p.add_argument("--sku", default="")
    p.add_argument("--upc", default="")
    p.add_argument("--name", default="")
    p.add_argument("--store", default="", help="Store id or comma-separated ids")
    p.add_argument("--price", default=None, help="Reported price, e.g. 0.01")
    p.add_argument("--source", choices=("community", "my_trip"), default="my_trip")
    p.add_argument("--notes", default="")
    p.add_argument("--date", default="", help="reported_at, YYYY-MM-DD, default today")
    p.add_argument("--confirmed", action="store_true", help="Already rang up at the register")
    p.add_argument("--id", default="", help="Reuse an id to update a lead")
    p.add_argument("--paste-file", type=Path, help="Text file: SKU, price, name")
    p.add_argument("--import-json", type=Path, help="A leads.json or app export")
    p.add_argument("--no-build", action="store_true", help="Don't rewrite docs/data.json")
    args = p.parse_args(argv)

    book = load_book()
    added = []

    if args.import_json:
        data = json.loads(args.import_json.read_text())
        if isinstance(data, list):
            leads, trips = data, []
        else:
            leads, trips = data.get("leads") or [], data.get("trips") or []
        for raw in leads:
            added.append(upsert_lead(book, raw))
        if trips:
            from leads_lib import add_trip
            for t in trips:
                add_trip(book, t)
        print(f"Imported {len(leads)} leads and {len(trips)} trip marks")
    elif args.paste_file:
        leads = parse_paste(args.paste_file.read_text(), default_source=args.source)
        for lead in leads:
            if args.store:
                lead["stores"] = [s.strip() for s in args.store.split(",") if s.strip()]
            added.append(upsert_lead(book, lead))
        print(f"Pasted {len(added)} leads from {args.paste_file}")
    else:
        if not (args.sku or args.upc or args.name):
            p.error("Need --sku, --upc, or --name (or --paste-file / --import-json)")
        lead = {
            "id": args.id or None,
            "sku": args.sku,
            "upc": args.upc,
            "name": args.name,
            "stores": args.store,
            "reported_price": args.price,
            "source": args.source,
            "notes": args.notes,
            "reported_at": args.date or today(),
            "confirmed_at_register": args.confirmed,
        }
        added.append(upsert_lead(book, lead))
        print(f"Saved {added[-1]['id']}: {added[-1]['name'] or added[-1]['sku'] or added[-1]['upc']}")

    save_book(book)
    print(f"Wrote {LEADS_PATH}")
    if not args.no_build:
        out = write_output(book)
        print(f"Built docs/data.json ({len(out['items'])} leads)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
