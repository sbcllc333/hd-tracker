#!/usr/bin/env python3
"""Penny Run daily job.

  python tracker.py                 scan today's stores (needs APIFY_TOKEN), then build docs/data.json
  python tracker.py --store 6346    scan these stores now (comma list of store numbers)
  python tracker.py --no-fetch      no scan, no network: only rebuild docs/data.json

Deep-clearance items come from Home Depot store data via the Apify Home Depot
actor on Apify's Free plan ($5 credit a month, no card); see tools/feed.py.
Community and trip leads come from data/leads.json, as before.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import feed as F  # noqa: E402
import leads_lib as L  # noqa: E402


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cfg = L.load_config()
    stores = L.active_stores(cfg)
    fd = F.load_feed()
    seeded = F.seed_from_old_ledger(fd)
    if seeded:
        print(f"Seeded {seeded} items from the old app's last real scans (data/ledger.json)")
    status = None
    if "--no-fetch" not in argv:
        only = None
        if "--store" in argv:
            only = [x.strip().zfill(4) for x in argv[argv.index("--store") + 1].split(",") if x.strip()]
        status = F.update(fd, cfg, stores, L.today(), only=only)
        fd["last_status"] = status
    F.save_feed(fd)
    out = L.write_output(L.load_book(), feed=fd, feed_status=status)
    plan = out["feed"]["plan"]
    print(f"Cost plan: {plan['scans_per_month']} scans/month x ${plan['cap_per_scan']:.2f} cap = "
          f"${plan['worst_case_usd']:.2f} worst case vs ${plan['budget_usd']:.2f} budget (free credit $5); "
          f"each store about every {plan['every_n_days']} days")
    pc = out["penny_counts"]
    print(f"Penny signals: {pc['penny']} at $0.01, {pc['hidden']} dropped off clearance, {pc['late']} late clearance, "
          f"{pc['weak']} weak (0 in stock)")
    per = ", ".join(f"{s['short']} {out['feed']['stores'].get(s['id'], {}).get('count', 0)}"
                    for s in stores if s["id"] in out["feed"]["stores"])
    print(f"Wrote docs/data.json: {len(out['deals'])} deals ({per}); {len(out['items'])} leads")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
