#!/usr/bin/env python3
"""Penny Run builder. Kept as the daily-job entry point; see tools/build.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
from build import main

if __name__ == "__main__":
    raise SystemExit(main())
