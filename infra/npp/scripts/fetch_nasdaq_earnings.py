"""Batch downloader for NASDAQ earnings calendar.

Usage:
  python scripts/fetch_nasdaq_earnings.py --start 2024-01-01 --end 2025-10-31

This script will iterate each date in the range and call
`data_sources.nasdaq_earnings.fetch_and_cache_earnings(date)` to populate the
local earnings sqlite cache (`data/outputs/earnings.db`). It skips dates that
already have entries and logs progress.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from typing import Optional
import time
import sys
import os
import logging

# Ensure repository root is importable so `src` is a top-level package
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.data_sources.nasdaq_earnings import fetch_and_cache_earnings, get_earnings_on

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fetch_nasdaq_earnings")


def daterange(start_date: datetime, end_date: datetime):
    cur = start_date
    while cur <= end_date:
        yield cur
        cur += timedelta(days=1)


def main(start: Optional[str], end: Optional[str], delay: float = 1.0, dry_run: bool = False,
         staged: bool = False, checkpoint_file: str = ".fetch_nasdaq_checkpoint", resume: bool = False):
    # If staged flag is used and start/end not provided, default to last ~6 months
    today = datetime.utcnow().date()
    if staged:
        default_end = today
        default_start = today - timedelta(days=183)
        if start is None:
            start = default_start.isoformat()
        if end is None:
            end = default_end.isoformat()

    if start is None or end is None:
        logger.error("Start and end dates are required unless --staged is used")
        sys.exit(1)

    try:
        s = datetime.fromisoformat(start).date()
        e = datetime.fromisoformat(end).date()
    except Exception:
        logger.error("Invalid date format, use YYYY-MM-DD")
        sys.exit(1)

    # Resume from checkpoint if requested
    if resume and os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r") as fh:
                last = fh.read().strip()
            if last:
                last_date = datetime.fromisoformat(last).date()
                s = last_date + timedelta(days=1)
                logger.info(f"Resuming from checkpoint; starting at {s.isoformat()}")
        except Exception:
            logger.warning("Failed to read checkpoint file, starting from given start date")

    if s > e:
        logger.info("Start date is after end date; nothing to do.")
        return

    total_days = (e - s).days + 1
    logger.info(f"Starting NASDAQ earnings batch fetch from {s.isoformat()} to {e.isoformat()} ({total_days} days)")

    fetched_days = 0
    skipped_days = 0

    for i, d in enumerate(daterange(s, e), start=1):
        ds = d.isoformat()
        existing = get_earnings_on(ds)
        if existing:
            logger.info(f"[{i}/{total_days}] {ds} - already have {len(existing)} entries, skipping")
            skipped_days += 1
            # update checkpoint so resume won't re-check
            try:
                with open(checkpoint_file, "w") as fh:
                    fh.write(ds)
            except Exception:
                logger.debug("Failed to write checkpoint file")
            continue

        logger.info(f"[{i}/{total_days}] {ds} - fetching...")
        if not dry_run:
            try:
                out = fetch_and_cache_earnings(ds)
                logger.info(f"    fetched {len(out)} rows for {ds}")
                fetched_days += 1
            except Exception as e:
                logger.exception(f"    failed to fetch {ds}: {e}")

            # write checkpoint after processing this day (whether fetched or error)
            try:
                with open(checkpoint_file, "w") as fh:
                    fh.write(ds)
            except Exception:
                logger.debug("Failed to write checkpoint file")

            # be polite
            time.sleep(delay)
        else:
            logger.info("    dry-run mode, not fetching")
            try:
                with open(checkpoint_file, "w") as fh:
                    fh.write(ds)
            except Exception:
                logger.debug("Failed to write checkpoint file")

    logger.info(f"Done. fetched-days={fetched_days}, skipped-days={skipped_days}")


if __name__ == "__main__":
        parser = argparse.ArgumentParser(description="Batch fetch NASDAQ earnings calendar")
        parser.add_argument("--start", required=False, help="Start date YYYY-MM-DD")
        parser.add_argument("--end", required=False, help="End date YYYY-MM-DD")
        parser.add_argument("--delay", type=float, default=1.0, help="Seconds to wait between requests (default 1s)")
        parser.add_argument("--dry-run", action="store_true", help="Don't perform network requests; only show what would be done")
        parser.add_argument("--staged", action="store_true", help="Run staged fetch for recent period (last ~6 months) if start/end not provided")
        parser.add_argument("--checkpoint-file", default=".fetch_nasdaq_checkpoint", help="Path to checkpoint file")
        parser.add_argument("--resume", action="store_true", help="Resume from checkpoint file if present")

        args = parser.parse_args()
        main(args.start, args.end, delay=args.delay, dry_run=args.dry_run,
            staged=args.staged, checkpoint_file=args.checkpoint_file, resume=args.resume)
