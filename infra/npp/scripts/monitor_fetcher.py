#!/usr/bin/env python3
"""Simple monitor for fetch_nasdaq_earnings log.

Watches `data/outputs/fetch_nasdaq_earnings.log` for new ERROR/Exception/429/5xx
lines and appends alerts to `data/outputs/fetch_nasdaq_earnings.alerts.log`.

Usage: nohup python scripts/monitor_fetcher.py &
"""
from __future__ import annotations

import re
import time
import os
from pathlib import Path

LOG_PATH = Path("data/outputs/fetch_nasdaq_earnings.log")
ALERT_PATH = Path("data/outputs/fetch_nasdaq_earnings.alerts.log")
CURSOR_PATH = Path(".monitor_fetcher_cursor")

PATTERN = re.compile(r"\b(ERROR|Exception|HTTP\s*429|HTTP\s*5\d{2}|\b5\d{2}\b)\b", re.IGNORECASE)


def tail_monitor():
    # ensure files exist
    if not LOG_PATH.exists():
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text("")
    if not ALERT_PATH.exists():
        ALERT_PATH.write_text("")

    last_pos = 0
    if CURSOR_PATH.exists():
        try:
            last_pos = int(CURSOR_PATH.read_text().strip() or "0")
        except Exception:
            last_pos = 0

    with LOG_PATH.open("r", encoding="utf-8", errors="ignore") as fh:
        fh.seek(0, os.SEEK_END)
        end = fh.tell()
        if last_pos > end:
            last_pos = 0
        fh.seek(last_pos)

        while True:
            line = fh.readline()
            if not line:
                # no new data; sleep and retry
                time.sleep(5)
                fh.seek(fh.tell())
                continue

            if PATTERN.search(line):
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                ALERT_PATH.open("a", encoding="utf-8").write(f"{ts} {line}")
            # update cursor
            try:
                CURSOR_PATH.write_text(str(fh.tell()))
            except Exception:
                pass


if __name__ == "__main__":
    try:
        tail_monitor()
    except KeyboardInterrupt:
        print("monitor stopped")
