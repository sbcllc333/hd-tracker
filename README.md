# Penny Run

A phone app for penny-item leads at my Jacksonville-area Home Depot stores
(Orange Park, Lane Ave/Normandy, Lem Turner, Southside, Oakleaf, Atlantic Blvd,
Jacksonville Beach, and Lake City). It is not affiliated with The Home Depot
or Walmart.

**The app (after you publish this branch):** https://sbcllc333.github.io/hd-tracker/
Open it on your phone and choose "Install" or "Add to Home screen".

This rebuild costs **$0 a month**. It does not call Apify, SerpApi, Bright Data,
or any LLM. There is no Home Depot scrape. Every lead is shown as **unconfirmed
until it rings up at the register**.

## How it works

- You and the community (by hand) add leads: SKU, UPC, name, store, reported
  price, and a short note. The book lives in `data/leads.json`.
- The phone app also saves new finds and trip marks in local storage, so you
  can use it with no server. Export a backup, or copy one lead as a JSON line
  and commit it to `data/leads.json`.
- Once a day, GitHub Actions runs `python tools/build.py`. That reads
  `data/leads.json` and writes `docs/data.json`. It uses no paid keys.
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

## What this branch removed

The old daily job paid Apify, SerpApi, and Bright Data to scrape clearance
aisles. That could not find real pennies (a $0.01 system price is a
pull-and-destroy flag, and most "possible pennies" showed 0 in stock). Those
code paths and the `APIFY_TOKEN`, `SERPAPI_KEY`, and `BRIGHTDATA_KEY` secrets
are gone from the workflow. After you publish, you can delete those secrets
and cancel the paid plans.

Leftover scrape files (`data/ledger.json`, `data/snapshots/`) are unused. You
can delete them whenever you like; the app no longer reads them.

## Develop locally

```
python tools/build.py
python tools/test_rebuild.py
cd docs && python -m http.server 8765
```

Then open http://127.0.0.1:8765/
