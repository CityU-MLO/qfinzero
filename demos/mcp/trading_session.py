"""
Demo: Full Trading Session via MCP (PMB tools)

Shows how an external system or LLM connects to QFinZero through the MCP
server and runs a complete paper-trading backtest — from account creation
through to performance summary.

Strategy: Buy 10 shares of AAPL at close every trading day in Jan 2025.
Equivalent to demos/pmb/client_demos/daily_buy_close.py but driven entirely
through MCP tool calls, exactly as an LLM agent would use them.

Covers:
  - pmb_health
  - pmb_create_account   — create paper account
  - pmb_create_session   — configure backtest
  - pmb_step_session     — advance clock, read market ticks
  - pmb_buy_stock        — place market order
  - pmb_get_positions    — inspect open positions
  - pmb_get_orders       — inspect order history
  - pmb_get_summary      — backtest performance metrics
  - pmb_export_session   — export trade log

Prerequisites:
  - UPQ and PMB running (scripts/run_all.sh)
  - MCP server deps: pip install "mcp[cli]>=1.0.0"

Usage:
  cd qfinzero
  python demos/mcp/trading_session.py
"""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "mcp", "server.py")


async def call(session: ClientSession, tool: str, **kwargs) -> any:
    """Call an MCP tool and return the parsed JSON result."""
    result = await session.call_tool(tool, kwargs)
    return json.loads(result.content[0].text)


def _get_stock_price(step_result: dict, symbol: str) -> float | None:
    """Extract close price for a symbol from a pmb_step_session result."""
    for event in step_result.get("events", []):
        if event.get("type") == "MARKET_TICK":
            for bar in event.get("payload", {}).get("stocks", []):
                if bar.get("symbol") == symbol:
                    return bar.get("close")
    return None


def _get_snapshot(step_result: dict) -> dict | None:
    """Extract ACCOUNT_SNAPSHOT payload from a pmb_step_session result."""
    for event in step_result.get("events", []):
        if event.get("type") == "ACCOUNT_SNAPSHOT":
            return event.get("payload")
    return None


async def main():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER_SCRIPT],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ── Health check ──────────────────────────────────────────────
            health = await call(session, "pmb_health")
            print(f"PMB health: {health.get('status', health)}\n")

            # ── 1. Create account ─────────────────────────────────────────
            acct = await call(
                session, "pmb_create_account",
                initial_cash=50000.0,
                account_type="MARGIN",
                start_date="2025-01-06",
            )
            account_id = acct["account_id"]
            cash = acct["account_state"]["cash_available"]
            print(f"Account : {account_id}")
            print(f"Cash    : ${cash:,.2f}\n")

            # ── 2. Create session ─────────────────────────────────────────
            sess = await call(
                session, "pmb_create_session",
                account_id=account_id,
                frequency="1d",
                start_ts="2025-01-06",
                end_ts="2025-01-31",
                stock_universe=["AAPL"],
            )
            session_id = sess["session_id"]
            print(f"Session : {session_id}")
            print(f"Clock   : {sess['clock']['current_ts']} → {sess['clock']['end_ts']}\n")

            # ── 3. Trading loop ───────────────────────────────────────────
            print(f"{'Day':>3} | {'Date':^10} | {'Price':>8} | {'Cash':>10} | {'Equity':>10} | {'Status'}")
            print("-" * 68)

            day = 0
            while True:
                step = await call(session, "pmb_step_session", session_id=session_id, n=1)

                if not step.get("is_running"):
                    print(f"\n  Session ended — status: {step.get('status')}")
                    break

                day += 1
                date_str = step["current_ts"][:10]
                price = _get_stock_price(step, "AAPL")
                snap = _get_snapshot(step)

                order_status = "—"
                if price:
                    order = await call(
                        session, "pmb_buy_stock",
                        session_id=session_id,
                        account_id=account_id,
                        symbol="AAPL",
                        qty=10,
                        order_type="MARKET",
                        client_order_id=f"daily_buy_{day}",
                    )
                    order_status = order.get("status", "?")

                cash_now = snap["cash_available"] if snap else 0.0
                equity = snap["equity"] if snap else 0.0
                price_str = f"${price:.2f}" if price else "N/A"

                print(
                    f"{day:3d} | {date_str:^10} | {price_str:>8} | "
                    f"${cash_now:9.2f} | ${equity:9.2f} | {order_status}"
                )

            # ── 4. Inspect positions ──────────────────────────────────────
            print("\n=== Open Positions ===\n")

            positions = await call(session, "pmb_get_positions", account_id=account_id)

            if positions:
                print(f"  {'Instrument':^28} | {'Qty':>6} | {'Avg Cost':>9} | {'Unreal P&L':>12}")
                print("  " + "-" * 65)
                for pos in positions:
                    print(
                        f"  {pos['instrument_id']:<28} | {pos['qty']:6} | "
                        f"${pos['avg_price']:8.2f} | ${pos['unrealized_pnl']:+11.2f}"
                    )
            else:
                print("  (no open positions)")

            # ── 5. Order history ──────────────────────────────────────────
            print("\n=== Order History (first 5) ===\n")

            orders = await call(
                session, "pmb_get_orders",
                account_id=account_id,
                session_id=session_id,
            )

            print(f"  Total orders placed: {len(orders)}")
            print(f"  {'Order ID':^10} | {'Symbol':^8} | {'Side':^4} | {'Qty':>4} | {'Fill Price':>10} | Status")
            print("  " + "-" * 70)
            for o in orders[:5]:
                instrument = o.get("instrument_id", "?")
                symbol = instrument.split(":")[1] if ":" in instrument else instrument
                fill = o.get("avg_fill_price")
                fill_str = f"${fill:.2f}" if fill else "—"
                print(
                    f"  {o['order_id'][:8]:<10} | {symbol:^8} | {o['side']:^4} | "
                    f"{o['qty']:4} | {fill_str:>10} | {o['status']}"
                )
            if len(orders) > 5:
                print(f"  ... and {len(orders) - 5} more")

            # ── 6. Performance summary ────────────────────────────────────
            print("\n=== Backtest Summary ===\n")

            summary = await call(session, "pmb_get_summary", session_id=session_id)

            metrics = [
                ("Final Equity",  f"${summary.get('final_equity', 0):,.2f}"),
                ("Total Return",  f"{summary.get('total_return', 0) * 100:+.2f}%"),
                ("Max Drawdown",  f"{summary.get('max_drawdown', 0) * 100:.2f}%"),
                ("Sharpe Ratio",  f"{summary.get('sharpe_ratio', 0):.3f}" if summary.get('sharpe_ratio') is not None else "N/A"),
                ("Fees Paid",     f"${summary.get('fees_paid', 0):.2f}"),
                ("Orders",        str(summary.get("num_orders", 0))),
                ("Trades",        str(summary.get("num_trades", 0))),
            ]
            for label, value in metrics:
                print(f"  {label:<16} {value}")

            # ── 7. Export trade log ───────────────────────────────────────
            print("\n=== Export (JSON preview) ===\n")

            export = await call(session, "pmb_export_session", session_id=session_id, fmt="json")

            if isinstance(export, dict):
                # Show top-level keys and a brief preview
                print(f"  Export keys: {list(export.keys())}")
                trades = export.get("trades", [])
                print(f"  Trade records: {len(trades)}")
                if trades:
                    t = trades[0]
                    print(f"  First trade: {json.dumps(t, indent=4)[:300]}")
            else:
                print(f"  Export received ({len(str(export))} chars)")


if __name__ == "__main__":
    asyncio.run(main())
