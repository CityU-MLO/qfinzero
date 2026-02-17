"""
Demo 1: Daily Buy-at-Close Strategy

Strategy:
  - Buy 10 shares of AAPL at close every trading day
  - Run for one month (January 2025)
  - Uses daily frequency

Prerequisites:
  - UPQ running on http://127.0.0.1:23333 with AAPL daily data
  - PMB running on http://127.0.0.1:24444

Usage:
  python demos/daily_buy_close.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
from demos.result_saver import ResultSaver


BASE = "http://127.0.0.1:24444"


def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def main():
    print_section("Daily Buy-at-Close Strategy: AAPL for January 2025")

    # 1. Create account with $50k
    print("\n1. Creating account...")
    acct_resp = requests.post(
        f"{BASE}/v1/accounts",
        json={
            "account_type": "MARGIN",
            "initial_cash": 50000.0,
            "start_date": "2025-01-06",
        },
    )
    acct = acct_resp.json()
    account_id = acct["account_id"]
    print(f"   Account created: {account_id}")
    print(f"   Initial cash: ${acct['account_state']['cash_available']:,.2f}")

    # 2. Create session: AAPL daily bars for January 2025
    print("\n2. Creating session (daily frequency)...")
    sess_resp = requests.post(
        f"{BASE}/v1/sessions",
        json={
            "account_id": account_id,
            "frequency": "1d",
            "start_ts": "2025-01-06",
            "end_ts": "2025-01-31",
            "universe": {"stocks": ["AAPL"]},
            "execution_config": {
                "slippage_bps": 2.0,
                "fee_model": {"stock_fee_per_share": 0.005},
            },
            "reproducibility": {"seed": 100, "run_id": "daily_buy_jan2025"},
        },
    )
    sess = sess_resp.json()
    session_id = sess["session_id"]
    print(f"   Session created: {session_id}")
    print(f"   Frequency: {sess['clock']['frequency']}")
    print(f"   Period: {sess['clock']['current_ts']} to {sess['clock']['end_ts']}")

    # 3. Trading loop: step through each day
    day_count = 0
    total_shares = 0
    orders_placed = []

    print("\n3. Running daily buy-at-close strategy...")
    print(f"   {'Day':>3} | {'Date':^10} | {'Price':>8} | {'Shares':>6} | {'Cash':>10} | {'Equity':>10}")
    print("   " + "-" * 65)

    while True:
        # Step to next day
        step_resp = requests.post(
            f"{BASE}/v1/sessions/{session_id}/step", json={"step": 1}
        )
        step_data = step_resp.json()

        if not step_data.get("ok"):
            break

        clock = step_data.get("clock", {})
        if clock.get("status") != "RUNNING":
            break

        events = step_data.get("events", [])
        day_count += 1

        # Extract market data
        market_tick = next((e for e in events if e["type"] == "MARKET_TICK"), None)
        aapl_bar = None
        if market_tick and market_tick["payload"]["stocks"]:
            aapl_bar = market_tick["payload"]["stocks"][0]

        # Extract account snapshot
        account_snap = next(
            (e for e in events if e["type"] == "ACCOUNT_SNAPSHOT"), None
        )
        if account_snap:
            snap = account_snap["payload"]
            cash = snap["cash_available"]
            equity = snap["equity"]

        # Place market buy order for 10 shares at close
        if aapl_bar:
            close_price = aapl_bar["close"]
            order_resp = requests.post(
                f"{BASE}/v1/orders",
                json={
                    "session_id": session_id,
                    "account_id": account_id,
                    "client_order_id": f"daily_buy_{day_count}",
                    "order": {
                        "instrument": {"type": "STOCK", "symbol": "AAPL"},
                        "side": "BUY",
                        "order_type": "MARKET",
                        "qty": 10,
                        "time_in_force": "DAY",
                    },
                },
            )
            order = order_resp.json()
            if order.get("ok"):
                orders_placed.append(order["order_id"])
                total_shares += 10
                date_str = clock["current_ts"][:10]
                print(
                    f"   {day_count:3d} | {date_str:^10} | ${close_price:7.2f} | {10:6d} | ${cash:9.2f} | ${equity:9.2f}"
                )

    # 4. Final summary
    print_section("Final Results")

    summary_resp = requests.get(f"{BASE}/v1/sessions/{session_id}/summary")
    summary = summary_resp.json()

    print(f"\n  Trading Period: {summary['start_ts'][:10]} to {summary['end_ts'][:10]}")
    print(f"  Days traded: {day_count}")
    print(f"  Total shares bought: {total_shares}")
    print(f"  Orders placed: {len(orders_placed)}")
    print(f"  Trades executed: {summary['num_trades']}")
    print(f"\n  Initial Equity: ${summary['final_equity'] / (1 + summary['total_return']):,.2f}")
    print(f"  Final Equity:   ${summary['final_equity']:,.2f}")
    print(f"  Total Return:   {summary['total_return']*100:+.2f}%")
    print(f"  Max Drawdown:   {summary['max_drawdown']*100:.2f}%")
    print(f"  Fees Paid:      ${summary['fees_paid']:.2f}")

    # 5. Final positions
    pos_resp = requests.get(f"{BASE}/v1/accounts/{account_id}/positions")
    positions = pos_resp.json().get("positions", [])

    print("\n  Final Positions:")
    for pos in positions:
        print(
            f"    {pos['instrument_id']:15s} {pos['qty']:6d} shares @ ${pos['avg_price']:.2f} avg, "
            f"mark ${pos['mark_price']:.2f}, P&L ${pos['unrealized_pnl']:+.2f}"
        )

    # 6. Export equity curve
    print("\n  Equity Curve:")
    export_resp = requests.get(f"{BASE}/v1/sessions/{session_id}/export?format=json")
    export_data = export_resp.json()
    equity_curve = export_data.get("equity_curve", [])

    for i, point in enumerate(equity_curve[::5]):  # show every 5th day
        print(f"    {point['ts'][:10]}: ${point['equity']:,.2f}")

    print(f"\n  Export saved {len(equity_curve)} equity points")

    # 7. Save results to disk
    print_section("Saving Results")

    saver = ResultSaver("daily_buy_close")

    # Build text report
    saver.add_summary_line(f"Daily Buy-at-Close Strategy: AAPL for January 2025")
    saver.add_summary_line(f"{'='*70}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Trading Period: {summary['start_ts'][:10]} to {summary['end_ts'][:10]}")
    saver.add_summary_line(f"Days traded: {day_count}")
    saver.add_summary_line(f"Total shares bought: {total_shares}")
    saver.add_summary_line(f"Orders placed: {len(orders_placed)}")
    saver.add_summary_line(f"Trades executed: {summary['num_trades']}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Initial Equity: ${summary['final_equity'] / (1 + summary['total_return']):,.2f}")
    saver.add_summary_line(f"Final Equity:   ${summary['final_equity']:,.2f}")
    saver.add_summary_line(f"Total Return:   {summary['total_return']*100:+.2f}%")
    saver.add_summary_line(f"Max Drawdown:   {summary['max_drawdown']*100:.2f}%")
    saver.add_summary_line(f"Fees Paid:      ${summary['fees_paid']:.2f}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Final Positions:")
    for pos in positions:
        saver.add_summary_line(
            f"  {pos['instrument_id']:15s} {pos['qty']:6d} shares @ ${pos['avg_price']:.2f} avg, "
            f"mark ${pos['mark_price']:.2f}, P&L ${pos['unrealized_pnl']:+.2f}"
        )

    saver.save_summary(summary)
    saver.save_holdings(positions)
    saver.save_operations(export_data.get("orders", []), export_data.get("trades", []))
    saver.save_equity_curve(equity_curve)
    saver.save_text_report()

    saver.print_saved_location()


if __name__ == "__main__":
    main()
