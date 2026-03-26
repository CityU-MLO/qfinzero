"""
Demo: Market Data via MCP (UPQ tools)

Shows how an external system or LLM connects to QFinZero through the MCP
server and calls UPQ tools to fetch stock/option/rates data.

Covers:
  - upq_health
  - upq_stock_daily     — daily OHLCV bars
  - upq_stock_minute    — intraday minute bars
  - upq_option_chain    — option chain snapshot
  - upq_rates           — treasury yield curve
  - upq_make_opra       — build OPRA contract string

Prerequisites:
  - UPQ running on http://127.0.0.1:19703
  - MCP server deps: pip install "mcp[cli]>=1.0.0"

Usage:
  cd qfinzero
  python demos/mcp/market_data.py
"""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Path to the MCP server
SERVER_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "mcp", "server.py")


async def call(session: ClientSession, tool: str, **kwargs) -> any:
    """Call an MCP tool and return the parsed JSON result."""
    result = await session.call_tool(tool, kwargs)
    # print(result)
    return json.loads(result.content[0].text)


async def main():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER_SCRIPT],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ── Health check ──────────────────────────────────────────────
            health = await call(session, "upq_health")
            print(f"UPQ health: {health.get('status', health)}\n")

            # ── 1. Daily bars for multiple tickers ────────────────────────
            print("=== AAPL & MSFT Daily Bars (Jan 2025) ===\n")

            bars = await call(
                session, "upq_stock_daily",
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

            # ── 2. Daily bars with field selection ────────────────────────
            print("\n=== AAPL Close Prices Only (field filter) ===\n")

            bars = await call(
                session, "upq_stock_daily",
                tickers=["AAPL"],
                start="2025-01-06",
                end="2025-01-31",
                fields="ticker,date,close",
            )

            for bar in bars:
                print(f"  {bar['date']}  ${bar['close']:.2f}")

            # ── 3. Minute bars ────────────────────────────────────────────
            print("\n=== AAPL Minute Bars (2025-01-06, 09:30–10:00) ===\n")

            bars = await call(
                session, "upq_stock_minute",
                tickers=["AAPL"],
                start="2025-01-06T09:30:00",
                end="2025-01-06T10:00:00",
            )

            print(f"{'window_start (ns)':>22} | {'Close':>8} | {'Volume':>10}")
            print("-" * 48)
            for bar in bars[:10]:
                ns = bar["window_start"]
                # Convert nanoseconds to seconds for display
                from datetime import datetime, timezone
                ts = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
                print(f"  {ts.strftime('%H:%M:%S UTC'):>20} | ${bar['close']:7.2f} | {bar['volume']:10,}")
            print(f"\n... {len(bars)} minute bars total")

            # ── 4. Build OPRA contract string ─────────────────────────────
            print("\n=== Build OPRA Contract String ===\n")

            opra = await call(
                session, "upq_make_opra",
                underlying="NVDA",
                expiry="2025-01-17",
                right="C",
                strike=136.0,
            )
            print(f"  OPRA contract: {opra}")

            # ── 5. Option chain ───────────────────────────────────────────
            print("\n=== NVDA Option Chain (2025-01-06, calls $130–$150) ===\n")

            chain = await call(
                session, "upq_option_chain",
                underlying="NVDA",
                date="2025-01-06",
                strike_min=130.0,
                strike_max=150.0,
                option_type="C",
                fields="ticker,expiry,strike,close,volume",
            )

            print(f"{'Contract':^28} | {'Expiry':^10} | {'Strike':>8} | {'Close':>8} | {'Volume':>8}")
            print("-" * 75)
            for c in chain[:10]:
                print(
                    f"  {c.get('ticker',''):<26} | {c.get('expiry',''):^10} | "
                    f"${c.get('strike') or 0:7.1f} | ${c.get('close') or 0:7.2f} | {c.get('volume') or 0:8,}"
                )
            print(f"\n{len(chain)} contracts returned")

            # ── 6. Treasury yield rates ───────────────────────────────────
            # print("\n=== Treasury Yield Curve (Jan 2025) ===\n")

            # rates = await call(
            #     session, "upq_rates",
            #     start="2025-01-06",
            #     end="2025-01-10",
            #     tenors="1M,6M,1Y,2Y,5Y,10Y,30Y",
            # )

            # if rates:
            #     # Print header from first row keys
            #     cols = [k for k in rates[0].keys() if k != "date"]
            #     print(f"{'Date':^12} | " + " | ".join(f"{c:>8}" for c in cols))
            #     print("-" * (14 + 11 * len(cols)))
            #     for row in rates:
            #         vals = " | ".join(
            #             f"{row[c]:8.3f}" if row[c] is not None else f"{'N/A':>8}"
            #             for c in cols
            #         )
            #         print(f"  {row['date']:^10} | {vals}")


if __name__ == "__main__":
    asyncio.run(main())
