#!/usr/bin/env python3
"""Analyze open-close gaps in stock data via UPQ API.

Two analyses:
1. Daily: overnight gap = today's open vs yesterday's close
2. Minute: intra-day gap = bar's open vs previous bar's close

This helps assess look-ahead bias when using MARKET orders
(which fill at close) vs using next-bar open as fill price.

Usage:
    python3 scripts/analyze_gaps.py [--base http://127.0.0.1:19703]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.parse import urlencode


UPQ_BASE = "http://127.0.0.1:19703"
TICKERS = ["QQQ", "NVDA", "AAPL", "SPY"]
START = "2024-01-02"
END = "2024-12-31"


def fetch_json(url):
    with urlopen(Request(url), timeout=60) as resp:
        return json.loads(resp.read())


def analyze_daily_gaps(base):
    """Overnight gap: today's open vs yesterday's close."""
    print("=" * 70)
    print("  DAILY: Overnight Gap (today open vs yesterday close)")
    print("=" * 70)
    print(f"  Period: {START} to {END}\n")

    for ticker in TICKERS:
        params = urlencode({
            "tickers": ticker,
            "start": START,
            "end": END,
            "fields": "ticker,date,open,close",
        })
        rows = fetch_json(f"{base}/stock/daily?{params}")
        if len(rows) < 2:
            print(f"  {ticker}: insufficient data ({len(rows)} rows)")
            continue

        gaps = []
        for i in range(1, len(rows)):
            prev_close = rows[i - 1]["close"]
            curr_open = rows[i]["open"]
            if prev_close > 0:
                gap_pct = (curr_open - prev_close) / prev_close * 100
                gaps.append({
                    "date": rows[i]["date"],
                    "prev_close": prev_close,
                    "open": curr_open,
                    "gap_pct": gap_pct,
                })

        if not gaps:
            continue

        abs_gaps = [abs(g["gap_pct"]) for g in gaps]
        abs_gaps_sorted = sorted(abs_gaps)
        n = len(gaps)
        avg = sum(abs_gaps) / n
        median = abs_gaps_sorted[n // 2]
        p90 = abs_gaps_sorted[int(n * 0.90)]
        p95 = abs_gaps_sorted[int(n * 0.95)]
        p99 = abs_gaps_sorted[int(n * 0.99)]
        max_gap = max(abs_gaps)

        # Count by bucket
        under_10bps = sum(1 for g in abs_gaps if g < 0.10)
        under_25bps = sum(1 for g in abs_gaps if g < 0.25)
        under_50bps = sum(1 for g in abs_gaps if g < 0.50)
        over_1pct = sum(1 for g in abs_gaps if g >= 1.0)
        over_2pct = sum(1 for g in abs_gaps if g >= 2.0)

        # Biggest gaps
        top5 = sorted(gaps, key=lambda g: abs(g["gap_pct"]), reverse=True)[:5]

        print(f"  {ticker} ({n} trading days)")
        print(f"    Mean |gap|:  {avg:.3f}%   ({avg * 100:.1f} bps)")
        print(f"    Median:      {median:.3f}%")
        print(f"    P90:         {p90:.3f}%")
        print(f"    P95:         {p95:.3f}%")
        print(f"    P99:         {p99:.3f}%")
        print(f"    Max:         {max_gap:.3f}%")
        print(f"    <10bps:      {under_10bps}/{n} ({under_10bps/n*100:.0f}%)")
        print(f"    <25bps:      {under_25bps}/{n} ({under_25bps/n*100:.0f}%)")
        print(f"    <50bps:      {under_50bps}/{n} ({under_50bps/n*100:.0f}%)")
        print(f"    >=1%:        {over_1pct}/{n} ({over_1pct/n*100:.0f}%)")
        print(f"    >=2%:        {over_2pct}/{n} ({over_2pct/n*100:.0f}%)")
        print(f"    Top 5 gaps:")
        for g in top5:
            print(f"      {g['date']}  close=${g['prev_close']:.2f} -> open=${g['open']:.2f}  gap={g['gap_pct']:+.3f}%")
        print()


def analyze_minute_gaps(base):
    """Intra-day gap: bar open vs previous bar close (within same day)."""
    print("=" * 70)
    print("  MINUTE: Intra-day Bar Gap (bar open vs prev bar close)")
    print("=" * 70)
    print(f"  Period: {START} to {END}")
    print("  (Sampling: first week of each month to limit data volume)\n")

    # Sample dates: first trading week of each month
    sample_months = [
        ("2024-01-02", "2024-01-05"),
        ("2024-02-01", "2024-02-05"),
        ("2024-03-01", "2024-03-05"),
        ("2024-04-01", "2024-04-05"),
        ("2024-05-01", "2024-05-03"),
        ("2024-06-03", "2024-06-07"),
        ("2024-07-01", "2024-07-05"),
        ("2024-08-01", "2024-08-05"),
        ("2024-09-03", "2024-09-06"),
        ("2024-10-01", "2024-10-04"),
        ("2024-11-01", "2024-11-05"),
        ("2024-12-02", "2024-12-06"),
    ]

    for ticker in TICKERS:
        all_gaps = []
        total_bars = 0

        for start, end in sample_months:
            params = urlencode({
                "tickers": ticker,
                "start": f"{start}T09:30:00",
                "end": f"{end}T16:00:00",
                "fields": "ticker,window_start,open,close",
            })
            try:
                rows = fetch_json(f"{base}/stock?{params}")
            except Exception as e:
                continue

            if len(rows) < 2:
                continue

            # Group by date, compute gaps within each day
            day_rows = {}
            for r in rows:
                ws = r.get("window_start", 0)
                # window_start is nanosecond epoch timestamp
                if isinstance(ws, int):
                    dt = datetime.fromtimestamp(ws / 1_000_000_000, tz=timezone.utc)
                    day = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%H:%M")
                else:
                    day = str(ws)[:10]
                    time_str = str(ws)[11:16]
                r["_day"] = day
                r["_time"] = time_str
                if day not in day_rows:
                    day_rows[day] = []
                day_rows[day].append(r)

            for day, bars in day_rows.items():
                total_bars += len(bars)
                for i in range(1, len(bars)):
                    prev_close = bars[i - 1]["close"]
                    curr_open = bars[i]["open"]
                    if prev_close > 0:
                        gap_pct = (curr_open - prev_close) / prev_close * 100
                        all_gaps.append({
                            "date": day,
                            "time": bars[i]["_time"],
                            "prev_close": prev_close,
                            "open": curr_open,
                            "gap_pct": gap_pct,
                        })

        if not all_gaps:
            print(f"  {ticker}: no minute data available")
            continue

        abs_gaps = [abs(g["gap_pct"]) for g in all_gaps]
        abs_gaps_sorted = sorted(abs_gaps)
        n = len(all_gaps)
        avg = sum(abs_gaps) / n
        median = abs_gaps_sorted[n // 2]
        p90 = abs_gaps_sorted[int(n * 0.90)]
        p95 = abs_gaps_sorted[int(n * 0.95)]
        p99 = abs_gaps_sorted[min(int(n * 0.99), n - 1)]
        max_gap = max(abs_gaps)

        under_1bps = sum(1 for g in abs_gaps if g < 0.01)
        under_5bps = sum(1 for g in abs_gaps if g < 0.05)
        under_10bps = sum(1 for g in abs_gaps if g < 0.10)
        over_25bps = sum(1 for g in abs_gaps if g >= 0.25)
        over_50bps = sum(1 for g in abs_gaps if g >= 0.50)

        # Biggest intra-day gaps
        top5 = sorted(all_gaps, key=lambda g: abs(g["gap_pct"]), reverse=True)[:5]

        print(f"  {ticker} ({n} bar transitions, {total_bars} total bars sampled)")
        print(f"    Mean |gap|:  {avg:.4f}%   ({avg * 100:.2f} bps)")
        print(f"    Median:      {median:.4f}%")
        print(f"    P90:         {p90:.4f}%")
        print(f"    P95:         {p95:.4f}%")
        print(f"    P99:         {p99:.4f}%")
        print(f"    Max:         {max_gap:.4f}%")
        print(f"    <1bps:       {under_1bps}/{n} ({under_1bps/n*100:.0f}%)")
        print(f"    <5bps:       {under_5bps}/{n} ({under_5bps/n*100:.0f}%)")
        print(f"    <10bps:      {under_10bps}/{n} ({under_10bps/n*100:.0f}%)")
        print(f"    >=25bps:     {over_25bps}/{n} ({over_25bps/n*100:.1f}%)")
        print(f"    >=50bps:     {over_50bps}/{n} ({over_50bps/n*100:.1f}%)")
        print(f"    Top 5 gaps:")
        for g in top5:
            print(f"      {g['date']} {g['time']}  close=${g['prev_close']:.2f} -> open=${g['open']:.2f}  gap={g['gap_pct']:+.4f}%")
        print()


def main():
    parser = argparse.ArgumentParser(description="Analyze open-close gaps via UPQ API")
    parser.add_argument("--base", default=UPQ_BASE, help="UPQ base URL")
    args = parser.parse_args()

    print(f"\nUPQ Gap Analysis — {args.base}\n")
    analyze_daily_gaps(args.base)
    analyze_minute_gaps(args.base)


if __name__ == "__main__":
    main()
