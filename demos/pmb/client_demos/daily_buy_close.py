"""
Demo 1 (Client): Daily Buy-at-Close Strategy

Same strategy as api_raw/daily_buy_close.py but using PMBClient.
Buy 10 shares of AAPL at close every trading day for January 2025.

Prerequisites:
  - UPQ running with AAPL daily data
  - PMB running on http://127.0.0.1:19320

Usage:
  cd qfinzero
  python demos/pmb/client_demos/daily_buy_close.py
"""

from qfinzero.clients.pmb import PMBClient


def main():
    with PMBClient() as pmb:
        # 1. Create account
        acct = pmb.create_account(initial_cash=50000.0, start_date="2025-01-06")
        account_id = acct["account_id"]
        print(f"Account: {account_id}, Cash: ${acct['account_state']['cash_available']:,.2f}")

        # 2. Create session
        sess = pmb.create_session(
            account_id=account_id,
            frequency="1d",
            start_ts="2025-01-06",
            end_ts="2025-01-31",
            universe={"stocks": ["AAPL"]},
            execution_config={
                "slippage_bps": 2.0,
                "fee_model": {"stock_fee_per_share": 0.005},
            },
            reproducibility={"seed": 100, "run_id": "daily_buy_jan2025"},
        )
        session_id = sess["session_id"]
        print(f"Session: {session_id}")

        # 3. Trading loop
        print(f"\n{'Day':>3} | {'Date':^10} | {'Price':>8} | {'Cash':>10} | {'Equity':>10}")
        print("-" * 55)

        day = 0
        while True:
            result = pmb.step(session_id)
            if not result.is_running:
                break

            day += 1
            price = result.get_stock_price("AAPL")
            snap = result.get_snapshot()

            if price:
                pmb.buy(session_id, account_id, "AAPL", 10,
                        client_order_id=f"daily_buy_{day}")

                cash = snap["cash_available"] if snap else 0
                equity = snap["equity"] if snap else 0
                date_str = result.current_ts[:10]
                print(f"{day:3d} | {date_str:^10} | ${price:7.2f} | ${cash:9.2f} | ${equity:9.2f}")

        # 4. Results
        summary = pmb.get_summary(session_id)
        positions = pmb.get_positions(account_id)

        print(f"\n--- Results ---")
        print(f"Final Equity:  ${summary['final_equity']:,.2f}")
        print(f"Total Return:  {summary['total_return']*100:+.2f}%")
        print(f"Max Drawdown:  {summary['max_drawdown']*100:.2f}%")
        print(f"Fees Paid:     ${summary['fees_paid']:.2f}")
        print(f"Orders/Trades: {summary['num_orders']}/{summary['num_trades']}")

        for pos in positions:
            print(f"  {pos['instrument_id']} {pos['qty']} shares "
                  f"@ ${pos['avg_price']:.2f}, P&L ${pos['unrealized_pnl']:+.2f}")


if __name__ == "__main__":
    main()
