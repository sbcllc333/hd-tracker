#!/usr/bin/env python3
"""Build docs/data.json from data/leads.json. No network, no paid APIs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from leads_lib import LEADS_PATH, OUT_PATH, load_book, write_output


def main():
    book = load_book()
    out = write_output(book)
    print(f"Wrote {OUT_PATH.relative_to(OUT_PATH.parents[1])}: {len(out['items'])} leads from {LEADS_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
