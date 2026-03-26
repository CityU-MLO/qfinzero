"""
Demo: Query treasury yield data via UPQClient.

Shows how to:
  - Fetch yield curve data for all tenors
  - Filter by specific tenors (e.g. 1M, 10Y)

Prerequisites:
  - UPQ running on http://127.0.0.1:19703 with rates data

Usage:
  cd qfinzero
  python demos/upq/rates_query.py
"""

from qfinzero.clients.upq import UPQClient


def main():
    with UPQClient() as upq:

        # ── 1. All tenors ───────────────────────────────────────
        print("=== Treasury Yields - All Tenors (Jan 2025) ===\n")

        yields = upq.rates(start="2025-01-02", end="2025-01-15")

        if yields:
            # Print header from first row's keys
            tenor_keys = [k for k in yields[0].keys() if k.startswith("yield_")]
            header = f"{'Date':^10} |" + "|".join(f"{k.replace('yield_', ''):>8}" for k in tenor_keys)
            print(header)
            print("-" * len(header))

            for row in yields:
                vals = "|".join(f"{row.get(k, 0):8.2f}" for k in tenor_keys)
                print(f"{row['date']:^10} |{vals}")

            print(f"\n{len(yields)} trading days")
        else:
            print("No rates data found.")

        # ── 2. Specific tenors ──────────────────────────────────
        print("\n=== 1M vs 10Y Spread (Jan 2025) ===\n")

        yields = upq.rates(
            start="2025-01-02",
            end="2025-01-31",
            tenors="1M,10Y",
        )

        if yields:
            print(f"{'Date':^10} | {'1M':>6} | {'10Y':>6} | {'Spread':>7}")
            print("-" * 40)
            for row in yields:
                y1m = row.get("yield_1_month", 0)
                y10y = row.get("yield_10_year", 0)
                spread = y10y - y1m
                print(f"{row['date']:^10} | {y1m:5.2f}% | {y10y:5.2f}% | {spread:+6.2f}%")
        else:
            print("No rates data found.")


if __name__ == "__main__":
    main()
