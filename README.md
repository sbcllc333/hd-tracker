# Jacksonville Home Depot — Penny Watch

Every morning this checks 4 Home Depot stores (Orange Park, Lane Ave/Normandy,
Lem Turner, Southside), saves what each store lists, and compares with yesterday.

The page in `docs/index.html` shows:
- Items that disappeared since yesterday (a few get double-checked as discontinued).
- Items priced ending in .03, which is often the last markdown before a penny.

- Departments tracked: `searches` in `config.json`.
- Online-only items are skipped (`"skip_online_only": true`).
- Turn a store off: set `"on": false` for it in `config.json`.
- Each store + search = 1 SerpApi search per day, plus up to `double_check_limit` checks.
  Right now: 6 searches x 4 stores = 24 a day, plus up to 3 checks.
