"""
Demo: Query earnings calendar via NPPClient.

Shows how to:
  - Query earnings for specific tickers
  - Query earnings for a date range
  - Display EPS surprise data
  - Filter by importance

Prerequisites:
  - NPP running on http://127.0.0.1:19702

Usage:
  cd qfinzero
  python demos/npp/earnings_calendar.py
"""

from qfinzero.clients.npp import NPPClient


def main():
    with NPPClient() as npp:
        # ── 1. NVDA & AAPL earnings in Jan 2025 ──────────────────
        print("=== NVDA & AAPL Earnings (Jan 2025) ===\n")

        result = npp.earnings_calendar(
            start_date="2025-01-01",
            end_date="2025-01-31",
            tickers=["NVDA", "AAPL"],
            limit=20,
        )

        header = f"{'Ticker':>6} | {'Date':^10} | {'Status':>10} | {'EPS Act':>8} | {'EPS Est':>8} | {'Surprise%':>10}"
        print(header)
        print("-" * len(header))

        for ev in result["events"]:
            p = ev.get("payload", {})
            ticker = ev["tickers"][0] if ev["tickers"] else "?"
            date = ev["time_utc"][:10]
            actual = p.get("actual_eps")
            est = p.get("estimated_eps")
            surp = p.get("eps_surprise_percent")
            print(
                f"{ticker:>6} | {date:^10} | {ev['status']:>10} | "
                f"{actual or 'N/A':>8} | {est or 'N/A':>8} | "
                f"{surp or 'N/A':>10}"
            )

        print(f"\nTotal: {len(result['events'])} earnings events")

        # ── 2. All earnings on a busy day ─────────────────────────
        print("\n=== All Earnings on 2025-01-23 ===\n")

        result = npp.earnings_calendar(
            start_date="2025-01-23",
            end_date="2025-01-23",
            limit=20,
        )

        for ev in result["events"]:
            p = ev.get("payload", {})
            ticker = ev["tickers"][0] if ev["tickers"] else "?"
            company = p.get("company_name") or ""
            eps = p.get("actual_eps")
            print(f"  {ticker:>6}  {company[:30]:<30}  EPS: {eps or 'pending'}")

        print(f"\n  {len(result['events'])} companies reporting")

        # ── 3. High-importance earnings ───────────────────────────
        print("\n=== High Importance Earnings (2025-01-20 to 2025-01-31) ===\n")

        result = npp.earnings_calendar(
            start_date="2025-01-20",
            end_date="2025-01-31",
            min_importance=4,
            limit=10,
        )

        for ev in result["events"]:
            p = ev.get("payload", {})
            ticker = ev["tickers"][0] if ev["tickers"] else "?"
            period = f"{p.get('fiscal_period', '')} FY{p.get('fiscal_year', '')}"
            print(f"  {ev['time_utc'][:10]}  {ticker:>6}  {period}  importance={ev['importance']}")

        print(f"\n  {len(result['events'])} high-importance earnings")


if __name__ == "__main__":
    main()
