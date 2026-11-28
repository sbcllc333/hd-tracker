# Penny Run

A phone app for penny-item leads at my Jacksonville-area Home Depot stores
(Orange Park, Lane Ave/Normandy, Lem Turner, Southside, Oakleaf, Atlantic Blvd,
Jacksonville Beach, and Lake City). It is not affiliated with The Home Depot
or Walmart.

**The app (after you publish this branch):** https://sbcllc333.github.io/hd-tracker/
Open it on your phone and choose "Install" or "Add to Home screen".

**Pennies never show online.** Home Depot only shows $0.01 at the register, so no
public data (and no version of this app) can list a confirmed penny. The app shows
**penny candidates, to confirm in store**, in this order:

1. **Confirmed 1¢**: only your own register / price-scanner mark ("Rang 1¢").
2. **Penny leads**: SKUs you paste from PennyCentral, Paydirt, a Facebook group or a
   receipt (the + button). Links only: those sites are never scraped.
3. **Likely penny · hidden price**: a deep-clearance item (70%+ off) that vanished from
   that store's clearance list in a full scan (kept 28 days with its last price).
4. **Late clearance · trip-worthy**: 75%+ off or under $1, after a markdown we saw, or
   at 90%+ off. Price endings (.02/.03/.06) are only a sort tiebreak, never a tag.
5. **Deep clearance**: everything else 50%+ off; "0 in stock online" items are marked
   likely sold out and sorted last.

Every price shows the date it was seen. Old scans are never hidden; the header shows
the data age (amber at 3+ days). The store may refuse a penny; be polite.

## The $0 cost math (rule 5)

Observed Apify cost per store scan (old app, Nov 13-17): $0.08-0.13 for department
searches, $0.20-0.26 at full depth. The free plan gives $5 a month.

- Plan: 8 stores, 2 scans a day = 60 scans a month, each hard-capped at $0.07
  (`max_cost_per_store_usd`) with 300 products max = **$4.20 worst case**, under the
  $4.50 stop and the $5 free credit. Each store refreshes about every 4 days.
- A capped scan can stop early. Then it only adds and updates items (no "dropped off"
  calls) until a full scan fits in the cap.
- The November credit was used up on Nov 17 by the old app, so no store has been
  scanned since. The app now records the real renewal date (`monthlyUsageCycle.endAt`)
  on the next run and shows it in Settings > Data status.

## Where the daily items come from (and what it costs)

Home Depot blocks scripts and cloud servers (including GitHub's) from its own
site, so the feed uses the same source that produced the old app's 50-99% off
items: the [Home Depot Scraper actor on Apify](https://apify.com/s_actors/home-depot-scraper)
(`s_actors~home-depot-scraper`). It returns Home Depot's own store-level data:
clearance price, was price, % off, store SKU, UPC, and pickup count.

- **Cost: $0.** It runs on Apify's **Free plan**: $5 of usage credit every month,
  no card. If the credit runs out, runs pause until next month; nothing is billed.
  `tools/feed.py` also checks the month's usage first, spreads the credit over the
  days left, stops at $4.50, and caps every run at $0.20.
- About 2 stores are scanned per day, oldest scan first, so each store is
  refreshed about every 4 days. Items not seen in a store's newest full scan move to
  "dropped off clearance"; older scans stay visible with their date.
- It needs **one** repo secret: `APIFY_TOKEN` (Apify Console > Settings >
  API & Integrations). Keep the account on the Free plan with no card.
  `SERPAPI_KEY` and `BRIGHTDATA_KEY` are not used and can be deleted.
- Without the secret (or when the month's credit is used up), nothing new is
  fetched and the app keeps showing each store's last real scan with its date.
- The first build was seeded from the old app's last real scans
  (Nov 16-17, 2026), so the app is not empty on day one.
- Fine print: Home Depot's terms of use restrict automated access to its site.
  The scraping is done by the Apify actor, not by this repo, but it is still
  Home Depot's data collected without its permission. Use it for personal
  shopping only, and don't republish it.

## How it works

- You and the community (by hand) add leads: SKU, UPC, name, store, reported
  price, and a short note. The book lives in `data/leads.json`.
- The phone app also saves new finds and trip marks in local storage, so you
  can use it with no server. Export a backup, or copy one lead as a JSON line
  and commit it to `data/leads.json`.
- Once a day, GitHub Actions runs `python tracker.py`. That scans today's
  stores (see above), keeps items 50%+ off in `data/feed.json`, reads
  `data/leads.json`, and writes `docs/data.json`. A code push only rebuilds
  (`--no-fetch`) and spends no credit. Run it by hand from the Actions tab;
  "stores" takes store numbers to scan right away (e.g. `6346,0275`).
- On a store run, mark **Found**, **Not there**, **Full price**, or **Rang up 1¢**.
  Each mark is stored with the date. Two "Not there" trips (on different days)
  demote the lead, unless a later trip finds it or rings up a penny.
- Scan the barcode on the box at self-checkout, not the shelf tag. The register
  price is the only proof of a penny.

## Adding finds

**On your phone:** tap **Add a find**. Enter a SKU or UPC, a price, a store,
and whether it came from your trip or a community list. Save keeps it on the
phone. **Copy as JSON line** gives you one line to paste into `data/leads.json`.

You can also paste a shortlist, one item per line:

```
564-184, 0.01, Wire shelf
100123456789, 0.01, Item with a UPC
```

**On a computer:**

```
python tools/add_lead.py --sku 564-184 --price 0.01 --name "Wire shelf" --store 0275 --source community
python tools/add_lead.py --paste-file pasted.txt --source community
python tools/add_lead.py --import-json backup.json
```

Then commit `data/leads.json` (and the rebuilt `docs/data.json`).

## Community lists (PennyCentral)

PennyCentral's penny list is a useful place to *read* community reports:
https://www.pennycentral.com/penny-list

It does **not** offer a public RSS, JSON, or spreadsheet feed that we are
allowed to reuse. Its [Terms of Service](https://www.pennycentral.com/terms-of-service)
(updated March 1, 2026) say: do not scrape, reverse engineer, or abuse site
systems, and unauthorized copying, scraping, or redistribution is prohibited.
`robots.txt` also disallows `/api/`.

So this app does not fetch PennyCentral. Open the list, copy the SKUs and
prices you want to check at your stores, and paste them into Add a find
(or `tools/add_lead.py --paste-file`). Always confirm at the register. Do not
commit a scraped dump of their list.

## Settings (`config.json`)

- `stores`: set `"on": false` to hide a store.
- `walmart_enabled`: defaults to `false`. Walmart stores stay in the file but
  are hidden until you turn this on. There is still no Walmart scrape; you
  would add those leads by hand the same way.

## Feed settings (`config.json` > `feed`)

- `min_pct` (50): lowest % off kept.  `max_age_days` (14): hide older items.
- `stores_per_day` (2), `monthly_budget_usd` (4.5), `max_cost_per_store_usd` (0.2).
- `category_urls`: Home Depot's In-Store Clearance page; `keywords` are scanned
  instead when that comes back empty (the old app's department searches).

## What changed from the old app

SerpApi and Bright Data are gone, and so are the Walmart scans. Apify stays,
on its Free plan only, because it is the only source that gave real 50-99% off
store clearance. `data/ledger.json` is read once to seed `data/feed.json` and is
otherwise unused.

## Develop locally

```
python tracker.py --no-fetch          # rebuild docs/data.json, no network
APIFY_TOKEN=... python tracker.py --store 6346   # real scan of one store
python -m unittest discover -s tools -p "test_*.py"
cd docs && python -m http.server 8765
```

Then open http://127.0.0.1:8765/
