"""
Demo 2: Intraday 5-Minute Mean Reversion Strategy

Strategy:
  - Check price every 5 minutes (aggregate from 1-minute bars)
  - If price is DOWN from 5 minutes ago: BUY 5 shares
  - If price is UP from 5 minutes ago: SELL 5 shares (if holding)
  - Single day: 2025-01-06

Prerequisites:
  - UPQ running on http://127.0.0.1:19703 with AAPL minute data
  - PMB running on http://127.0.0.1:19701

Usage:
  python demos/intraday_5min_signal.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
from demos.result_saver import ResultSaver
from qfinzero.config import PMB_URL


BASE = PMB_URL


def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def main():
    print_section("Intraday 5-Min Mean Reversion: AAPL 2025-01-06")

    # 1. Create account
    print("\n1. Creating account...")
    acct_resp = requests.post(
        f"{BASE}/v1/accounts",
        json={
            "account_type": "MARGIN",
            "initial_cash": 25000.0,
            "start_date": "2025-01-06",
        },
    )
    acct = acct_resp.json()
    account_id = acct["account_id"]
    print(f"   Account: {account_id}, Cash: ${acct['account_state']['cash_available']:,.2f}")

    # 2. Create session: AAPL minute bars for one day
    print("\n2. Creating session (1-minute frequency)...")
    sess_resp = requests.post(
        f"{BASE}/v1/sessions",
        json={
            "account_id": account_id,
            "frequency": "1m",
            "start_ts": "2025-01-06T09:30:00",
            "end_ts": "2025-01-06T16:00:00",
            "universe": {"stocks": ["AAPL"]},
            "execution_config": {
                "slippage_bps": 1.0,
                "fee_model": {"stock_fee_per_share": 0.005},
            },
            "reproducibility": {"seed": 200, "run_id": "intraday_5min"},
        },
    )
    sess = sess_resp.json()
    session_id = sess["session_id"]
    print(f"   Session: {session_id}")

    # 3. Trading loop with 5-minute signal
    print("\n3. Running 5-minute signal strategy...")
    print(f"   {'Time':^8} | {'Price':>8} | {'Signal':^8} | {'Action':^10} | {'Pos':>4} | {'Cash':>10} | {'Equity':>10}")
    print("   " + "-" * 80)

    minute_count = 0
    prices = []
    current_position = 0
    trades = []

    while True:
        # Step 1 minute
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
        minute_count += 1

        # Extract price
        market_tick = next((e for e in events if e["type"] == "MARKET_TICK"), None)
        current_price = None
        if market_tick and market_tick["payload"]["stocks"]:
            aapl_bar = market_tick["payload"]["stocks"][0]
            current_price = aapl_bar["close"]
            prices.append(current_price)

        # Extract account snapshot
        account_snap = next((e for e in events if e["type"] == "ACCOUNT_SNAPSHOT"), None)
        cash = 0
        equity = 0
        if account_snap:
            snap = account_snap["payload"]
            cash = snap["cash_available"]
            equity = snap["equity"]
            # Update position count from snapshot
            if snap["positions"]:
                current_position = snap["positions"][0]["qty"]
            else:
                current_position = 0

        # Every 5 minutes: generate signal
        if minute_count % 5 == 0 and len(prices) >= 5:
            price_5min_ago = prices[-5]
            signal = "DOWN" if current_price < price_5min_ago else "UP"
            action = None

            # DOWN signal: buy 5 shares
            if signal == "DOWN":
                order_resp = requests.post(
                    f"{BASE}/v1/orders",
                    json={
                        "session_id": session_id,
                        "account_id": account_id,
                        "client_order_id": f"buy_{minute_count}",
                        "order": {
                            "instrument": {"type": "STOCK", "symbol": "AAPL"},
                            "side": "BUY",
                            "order_type": "MARKET",
                            "qty": 5,
                            "time_in_force": "DAY",
                        },
                    },
                )
                if order_resp.json().get("ok"):
                    action = "BUY 5"
                    trades.append({"time": clock["current_ts"][11:16], "action": "BUY", "qty": 5, "price": current_price})

            # UP signal: sell 5 shares if holding
            elif signal == "UP" and current_position >= 5:
                order_resp = requests.post(
                    f"{BASE}/v1/orders",
                    json={
                        "session_id": session_id,
                        "account_id": account_id,
                        "client_order_id": f"sell_{minute_count}",
                        "order": {
                            "instrument": {"type": "STOCK", "symbol": "AAPL"},
                            "side": "SELL",
                            "order_type": "MARKET",
                            "qty": 5,
                            "time_in_force": "DAY",
                        },
                    },
                )
                if order_resp.json().get("ok"):
                    action = "SELL 5"
                    trades.append({"time": clock["current_ts"][11:16], "action": "SELL", "qty": 5, "price": current_price})

            time_str = clock["current_ts"][11:16]
            print(
                f"   {time_str:^8} | ${current_price:7.2f} | {signal:^8} | {action or 'HOLD':^10} | {current_position:4d} | ${cash:9.2f} | ${equity:9.2f}"
            )

    # 4. Summary
    print_section("Final Results")

    summary_resp = requests.get(f"{BASE}/v1/sessions/{session_id}/summary")
    summary = summary_resp.json()

    print(f"\n  Total minutes: {minute_count}")
    print(f"  Total orders: {summary['num_orders']}")
    print(f"  Total trades: {summary['num_trades']}")
    print(f"\n  Initial Equity: ${25000:,.2f}")
    print(f"  Final Equity:   ${summary['final_equity']:,.2f}")
    print(f"  Total Return:   {summary['total_return']*100:+.2f}%")
    print(f"  Fees Paid:      ${summary['fees_paid']:.2f}")

    print("\n  Trade Log:")
    for t in trades:
        print(f"    {t['time']} {t['action']:4s} {t['qty']:2d} @ ${t['price']:.2f}")

    # Final positions
    pos_resp = requests.get(f"{BASE}/v1/accounts/{account_id}/positions")
    positions = pos_resp.json().get("positions", [])

    print("\n  Final Positions:")
    if positions:
        for pos in positions:
            print(
                f"    {pos['instrument_id']:15s} {pos['qty']:6d} shares @ ${pos['avg_price']:.2f}, "
                f"mark ${pos['mark_price']:.2f}, P&L ${pos['unrealized_pnl']:+.2f}"
            )
    else:
        print("    No positions (flat)")

    # 5. Save results
    print_section("Saving Results")

    # Get export data
    export_resp = requests.get(f"{BASE}/v1/sessions/{session_id}/export?format=json")
    export_data = export_resp.json()

    saver = ResultSaver("intraday_5min_signal")

    # Build text report
    saver.add_summary_line(f"Intraday 5-Minute Mean Reversion: AAPL 2025-01-06")
    saver.add_summary_line(f"{'='*70}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Total minutes: {minute_count}")
    saver.add_summary_line(f"Total orders: {summary['num_orders']}")
    saver.add_summary_line(f"Total trades: {summary['num_trades']}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Initial Equity: ${25000:,.2f}")
    saver.add_summary_line(f"Final Equity:   ${summary['final_equity']:,.2f}")
    saver.add_summary_line(f"Total Return:   {summary['total_return']*100:+.2f}%")
    saver.add_summary_line(f"Fees Paid:      ${summary['fees_paid']:.2f}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Trade Log:")
    for t in trades:
        saver.add_summary_line(f"  {t['time']} {t['action']:4s} {t['qty']:2d} @ ${t['price']:.2f}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Final Positions:")
    if positions:
        for pos in positions:
            saver.add_summary_line(
                f"  {pos['instrument_id']:15s} {pos['qty']:6d} shares @ ${pos['avg_price']:.2f}, "
                f"mark ${pos['mark_price']:.2f}, P&L ${pos['unrealized_pnl']:+.2f}"
            )
    else:
        saver.add_summary_line("  No positions (flat)")

    saver.save_summary(summary)
    saver.save_holdings(positions)
    saver.save_operations(export_data.get("orders", []), export_data.get("trades", []))
    saver.save_equity_curve(export_data.get("equity_curve", []))
    saver.save_text_report()

    saver.print_saved_location()


if __name__ == "__main__":
    main()
