#!/usr/bin/env python3
"""Generate pre-computed LLM context files for the 2025 overlay agent backtest.

Reads from SQLite databases on qlib and writes JSON files to /home/qlib/news/llm_context_2025/.

Usage:
    scp infra/pmb/demos/generate_llm_context.py qlib:/tmp/generate_llm_context.py
    ssh qlib "python3 /tmp/generate_llm_context.py"
"""

import json
import os
import sqlite3
from collections import defaultdict

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ECON_DB = "/home/qlib/news/nasdaq_econ_events.sqlite3"
EARNINGS_DB = "/home/qlib/news/benzinga_earnings.sqlite3"
OUTPUT_DIR = "/home/qlib/news/llm_context_2025"

SEMI_TICKERS = [
    "NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM",
    "MU", "MRVL", "TXN", "LRCX", "KLAC", "AMAT",
]

ECON_EVENT_WHITELIST = [
    "Fed Interest Rate Decision", "FOMC Statement", "FOMC Press Conference",
    "FOMC Meeting Minutes", "Nonfarm Payrolls", "Unemployment Rate",
    "CPI", "Core CPI", "PPI", "Core PPI", "GDP",
    "ISM Manufacturing PMI", "ISM Non-Manufacturing PMI",
    "Retail Sales", "Core Retail Sales",
    "CB Consumer Confidence", "Michigan Consumer Sentiment",
    "Durable Goods Orders", "Core Durable Goods Orders",
    "Housing Starts", "Building Permits",
    "Initial Jobless Claims", "Continuing Jobless Claims",
    "Industrial Production", "Capacity Utilization Rate",
    "Trade Balance", "Philadelphia Fed Manufacturing Index",
    "NY Empire State Manufacturing Index",
    "Existing Home Sales", "New Home Sales",
    "PCE Prices", "Core PCE Prices",
    "JOLTS Job Openings", "ADP Nonfarm Employment Change",
]

# We need:
#   review files: 2024-12 through 2025-11  (actual data from that month)
#   upcoming files: 2025-01 through 2025-12  (events scheduled in month+1)
# So date range needed: 2024-12-01 through 2026-01-31

DATE_START = "2024-12-01"
DATE_END = "2026-02-01"  # exclusive upper bound


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_value(val: str | None) -> str:
    """Clean &nbsp;, whitespace-only, and None values to empty string."""
    if val is None:
        return ""
    val = val.replace("&nbsp;", "").replace("\xa0", "").strip()
    return val


def month_key(date_str: str) -> str:
    """Extract YYYY-MM from a date string like 2025-01-15."""
    return date_str[:7]


def next_month(ym: str) -> str:
    """Given YYYY-MM, return the next month's YYYY-MM."""
    y, m = int(ym[:4]), int(ym[5:7])
    m += 1
    if m > 12:
        m = 1
        y += 1
    return f"{y:04d}-{m:02d}"


# ---------------------------------------------------------------------------
# Macro events
# ---------------------------------------------------------------------------

def generate_macro_files():
    """Generate review and upcoming JSON files for macro events."""
    conn = sqlite3.connect(ECON_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    placeholders = ",".join(["?"] * len(ECON_EVENT_WHITELIST))
    cur.execute(
        f"""
        SELECT date, event_name, actual, consensus, previous
        FROM econ_events
        WHERE country = 'United States'
          AND event_name IN ({placeholders})
          AND date >= ?
          AND date < ?
        ORDER BY date, event_name
        """,
        (*ECON_EVENT_WHITELIST, DATE_START, DATE_END),
    )

    # Deduplicate by (date, event_name), keep first occurrence
    seen = set()
    events_by_month: dict[str, list[dict]] = defaultdict(list)

    for row in cur.fetchall():
        key = (row["date"], row["event_name"])
        if key in seen:
            continue
        seen.add(key)

        mk = month_key(row["date"])
        events_by_month[mk].append({
            "date": row["date"],
            "event": row["event_name"],
            "actual": clean_value(row["actual"]),
            "consensus": clean_value(row["consensus"]),
            "previous": clean_value(row["previous"]),
        })

    conn.close()

    macro_dir = os.path.join(OUTPUT_DIR, "macro")
    os.makedirs(macro_dir, exist_ok=True)

    # Review files: for each month M from 2024-12 to 2025-11,
    # write M_review.json with actual data from month M.
    # (2024-12_review serves as "last month review" when backtest starts in Jan 2025)
    review_months = ["2024-12"] + [f"2025-{m:02d}" for m in range(1, 12)]
    for ym in review_months:
        data = {
            "month": ym,
            "events": events_by_month.get(ym, []),
        }
        path = os.path.join(macro_dir, f"{ym}_review.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  wrote {path} ({len(data['events'])} events)")

    # Upcoming files: for month M from 2025-01 to 2025-12,
    # write M_upcoming.json containing events scheduled in month M+1 (date + event only).
    # e.g. 2025-01_upcoming.json contains Feb 2025 events.
    for m in range(1, 13):
        ym = f"2025-{m:02d}"
        target_month = next_month(ym)  # the month whose events we list
        raw_events = events_by_month.get(target_month, [])
        upcoming_events = [{"date": e["date"], "event": e["event"]} for e in raw_events]
        data = {
            "month": target_month,
            "events": upcoming_events,
        }
        path = os.path.join(macro_dir, f"{ym}_upcoming.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  wrote {path} ({len(upcoming_events)} events)")


# ---------------------------------------------------------------------------
# Semi earnings
# ---------------------------------------------------------------------------

def generate_semi_earnings():
    """Generate the semiconductor earnings JSON file."""
    conn = sqlite3.connect(EARNINGS_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    placeholders = ",".join(["?"] * len(SEMI_TICKERS))
    cur.execute(
        f"""
        SELECT ticker, date, time, fiscal_period, fiscal_year,
               estimated_eps, actual_eps, eps_surprise_percent,
               actual_revenue, estimated_revenue
        FROM earnings
        WHERE ticker IN ({placeholders})
          AND date >= '2025-01-01'
          AND date < '2026-01-01'
        ORDER BY date, ticker
        """,
        SEMI_TICKERS,
    )

    earnings = []
    for row in cur.fetchall():
        earnings.append({
            "ticker": row["ticker"],
            "date": row["date"],
            "time": row["time"],
            "fiscal_period": row["fiscal_period"],
            "fiscal_year": row["fiscal_year"],
            "estimated_eps": row["estimated_eps"],
            "actual_eps": row["actual_eps"],
            "eps_surprise_percent": row["eps_surprise_percent"],
            "actual_revenue": row["actual_revenue"],
            "estimated_revenue": row["estimated_revenue"],
        })

    conn.close()

    data = {
        "tickers": SEMI_TICKERS,
        "earnings": earnings,
    }
    path = os.path.join(OUTPUT_DIR, "semi_earnings_2025.json")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  wrote {path} ({len(earnings)} earnings records)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    print("Generating macro review & upcoming files...")
    generate_macro_files()
    print()

    print("Generating semi earnings file...")
    generate_semi_earnings()
    print()

    # Summary
    macro_dir = os.path.join(OUTPUT_DIR, "macro")
    macro_files = sorted(os.listdir(macro_dir))
    print(f"Done. {len(macro_files)} macro files + 1 earnings file = {len(macro_files) + 1} total files.")


if __name__ == "__main__":
    main()
