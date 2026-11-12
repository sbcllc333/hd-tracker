# Penny Run

A clearance and penny-item tracker for four Jacksonville-area Home Depot stores
(Orange Park, Lane Ave/Normandy, Lem Turner, Southside). Not affiliated with The Home Depot.

**The app:** https://sbcllc333.github.io/hd-tracker/ — open it on your phone and
choose "Install" or "Add to Home screen".

## How it works
- Every morning GitHub runs `tracker.py`, which scans **one store** (the one scanned
  longest ago), so each store is refreshed about every 4 days.
- **Apify** (free $5 monthly credit) pulls that store's clearance items in each department:
  clearance price, regular price, store SKU, UPC and the store's stock count.
  One store scan costs roughly 7 to 15 cents and is capped in `config.json`.
- **SerpApi** (250 free searches a month) is the backup if Apify can't run.
- **Bright Data** (free plan) is asked whether the deepest-clearance items are discontinued.
- `data/ledger.json` keeps a history per item per store: first seen on clearance,
  every price change, stock count, and when it dropped off the clearance list.
- Each item gets a 0-100 score (discount depth, weeks on clearance, low or zero stock,
  price ending in .02/.03, discontinued).
- The app in `docs/` reads `docs/data.json`.

## Settings (`config.json`)
- `searches`: departments to scan.
- `apify`: how deep to look per department and the spending cap per scan.
- `min_price`: skip items cheaper than this.
- `min_percent_off`: the discount filter to use.
- `stores`: set `"on": false` to stop scanning a store.

## Secrets (GitHub → Settings → Secrets → Actions)
- `APIFY_TOKEN` (main source), `SERPAPI_KEY` (backup), `BRIGHTDATA_KEY` (optional).
