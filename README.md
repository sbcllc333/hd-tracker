# Jacksonville Home Depot — Discontinued Watch

Every morning this checks the 8 Jacksonville-area Home Depot stores, saves what each
store lists, and compares with yesterday. Items that vanished get double-checked and
show up on the page in `docs/index.html`.

- Change what it tracks: edit `searches` in `config.json` (e.g. "power tools", "paint").
- Turn a store off: set `"on": false` for it in `config.json`.
- Each store + search = 1 SerpApi search per day, plus up to `double_check_limit` checks.
