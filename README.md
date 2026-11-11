# Penny Run

A clearance and penny-item tracker for four Jacksonville-area Home Depot stores
(Orange Park, Lane Ave/Normandy, Lem Turner, Southside). Not affiliated with The Home Depot.

**The app:** https://sbcllc333.github.io/hd-tracker/ — open it on your phone and
choose "Install" or "Add to Home screen".

## How it works
- Every morning GitHub runs `tracker.py`, which scans **one store** (the one scanned
  longest ago), so each store is refreshed about every 4 days. That is roughly
  7 searches a day and fits SerpApi's free 250 searches a month.
- For each department it asks for items at 40% off or more at that store.
- `data/ledger.json` keeps a history per item per store: first seen on clearance,
  every price change, stock count.
- Bright Data's free plan is asked whether the deepest-clearance items are discontinued.
- Each item gets a 0-100 score (discount depth, weeks on clearance, low stock,
  price ending in .02/.03, discontinued).
- The app in `docs/` reads `docs/data.json`.

## Settings (`config.json`)
- `searches`: departments to scan. Each one costs 1 search per day.
- `min_price`: skip items cheaper than this.
- `min_percent_off`: the discount filter to use.
- `stores`: set `"on": false` to stop scanning a store.

## Secrets (GitHub → Settings → Secrets → Actions)
- `SERPAPI_KEY` (needed), `BRIGHTDATA_KEY` (optional).
