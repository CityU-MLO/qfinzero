"""
Demo: Query stock price data via UPQClient.

Shows how to:
  - Fetch daily OHLCV bars for one or more tickers
  - Fetch minute-level intraday bars
  - Select specific fields to reduce response size
  - Convert nanosecond timestamps

Prerequisites:
  - UPQ running on http://127.0.0.1:19703

Usage:
  cd qfinzero
  python demos/upq/stock_query.py
"""

from qfinzero.clients.upq import UPQClient


def main():
    with UPQClient() as upq:
        # Health check
        print("UPQ health:", upq.health())

        # ── 1. Daily bars for multiple tickers ──────────────────
        print("\n=== AAPL & MSFT Daily Bars (Jan 2025) ===\n")

        bars = upq.stock_daily(
            tickers=["AAPL", "MSFT"],
            start="2025-01-06",
            end="2025-01-17",
        )

        print(f"{'Ticker':>6} | {'Date':^10} | {'Open':>8} | {'High':>8} | {'Low':>8} | {'Close':>8} | {'Volume':>12}")
        print("-" * 75)
        for bar in bars:
            print(
                f"{bar['ticker']:>6} | {bar['date']:^10} | "
                f"${bar['open']:7.2f} | ${bar['high']:7.2f} | ${bar['low']:7.2f} | "
                f"${bar['close']:7.2f} | {bar['volume']:12,}"
            )

        print(f"\nTotal rows: {len(bars)}")

        # ── 2. Daily bars with selected fields ──────────────────
        print("\n=== AAPL Close Prices Only ===\n")

        bars = upq.stock_daily(
            tickers=["AAPL"],
            start="2025-01-06",
            end="2025-01-31",
            fields="ticker,date,close",
        )

        for bar in bars:
            print(f"  {bar['date']}  ${bar['close']:.2f}")

        # ── 3. Minute bars (intraday) ───────────────────────────
        print("\n=== AAPL Minute Bars (2025-01-06, first 30 min) ===\n")

        bars = upq.stock_minute(
            tickers=["AAPL"],
            start="2025-01-06T09:30:00",
            end="2025-01-06T10:00:00",
        )

        print(f"{'Time (UTC)':^24} | {'Close':>8} | {'Volume':>10}")
        print("-" * 50)
        for bar in bars[:10]:  # show first 10
            ts = UPQClient.ns_to_datetime(bar["window_start"])
            print(f"{ts.strftime('%Y-%m-%d %H:%M:%S'):^24} | ${bar['close']:7.2f} | {bar['volume']:10,}")

        print(f"\n... {len(bars)} minute bars total")


if __name__ == "__main__":
    main()
