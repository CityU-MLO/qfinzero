"""Batch fetcher for Massive news (dry-run scaffold).

Usage:
  python scripts/fetch_massive_news.py --symbol AAPL --start 2025-01-01 --end 2025-06-30 --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

# Ensure repository root is on sys.path so `src` is importable when running scripts
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
  sys.path.insert(0, REPO_ROOT)

import importlib.util

# Import `src/data_sources/massive_news.py` by path to avoid importing other
# `src.data_sources` package-level modules that require optional deps.
module_path = os.path.join(REPO_ROOT, "src", "data_sources", "massive_news.py")
spec = importlib.util.spec_from_file_location("massive_news", module_path)
massive_news = importlib.util.module_from_spec(spec)
spec.loader.exec_module(massive_news)
fetch_news_for_symbol = massive_news.fetch_news_for_symbol


def main(symbol: str, start: str | None, end: str | None, dry_run: bool = True):
  # Dry-run safe: MassiveClient will return empty without API key
  out = fetch_news_for_symbol(symbol, start=start, end=end)
  print(f"Found {len(out)} articles for {symbol} (dry-run={dry_run})")


if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument("--symbol", required=True)
  parser.add_argument("--start", required=False)
  parser.add_argument("--end", required=False)
  parser.add_argument("--dry-run", action="store_true")
  args = parser.parse_args()
  main(args.symbol, args.start, args.end, dry_run=args.dry_run)
