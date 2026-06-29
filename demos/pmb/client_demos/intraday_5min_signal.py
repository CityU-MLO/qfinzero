"""
Demo 2 (Client): Intraday 5-Minute Mean Reversion

Same strategy as api_raw/intraday_5min_signal.py but using PMBClient.
Every 5 minutes: if price down -> BUY 5, if price up and holding -> SELL 5.

Prerequisites:
  - UPQ running with AAPL minute data
  - PMB running on http://127.0.0.1:19380

Usage:
  cd qfinzero
  python demos/pmb/client_demos/intraday_5min_signal.py
"""

from qfinzero.clients.pmb import PMBClient


def main():
    with PMBClient() as pmb:
        # 1. Create account
        acct = pmb.create_account(initial_cash=25000.0, start_date="2025-01-06")
        account_id = acct["account_id"]
        print(f"Account: {account_id}, Cash: ${acct['account_state']['cash_available']:,.2f}")

        # 2. Create minute session
        sess = pmb.create_session(
            account_id=account_id,
            frequency="1m",
            start_ts="2025-01-06T09:30:00",
            end_ts="2025-01-06T16:00:00",
            universe={"stocks": ["AAPL"]},
            execution_config={
                "slippage_bps": 1.0,
                "fee_model": {"stock_fee_per_share": 0.005},
            },
            reproducibility={"seed": 200, "run_id": "intraday_5min"},
        )
        session_id = sess["session_id"]
        print(f"Session: {session_id}")

        # 3. Trading loop
        print(f"\n{'Time':^8} | {'Price':>8} | {'Signal':^6} | {'Action':^8} | {'Pos':>4} | {'Equity':>10}")
        print("-" * 65)

        minute = 0
        prices = []
        position = 0

        while True:
            result = pmb.step(session_id)
            if not result.is_running:
                break

            minute += 1
            price = result.get_stock_price("AAPL")
            if price:
                prices.append(price)

            snap = result.get_snapshot()
            if snap and snap["positions"]:
                position = snap["positions"][0]["qty"]
            elif snap:
                position = 0

            # Every 5 minutes: generate signal
            if minute % 5 == 0 and len(prices) >= 5:
                price_5ago = prices[-5]
                signal = "DOWN" if price < price_5ago else "UP"
                action = None

                if signal == "DOWN":
                    resp = pmb.buy(session_id, account_id, "AAPL", 5,
                                   client_order_id=f"buy_{minute}")
                    if resp.get("ok"):
                        action = "BUY 5"

                elif signal == "UP" and position >= 5:
                    resp = pmb.sell(session_id, account_id, "AAPL", 5,
                                    client_order_id=f"sell_{minute}")
                    if resp.get("ok"):
                        action = "SELL 5"

                equity = snap["equity"] if snap else 0
                time_str = result.current_ts[11:16]
                print(f"{time_str:^8} | ${price:7.2f} | {signal:^6} | {action or 'HOLD':^8} | {position:4d} | ${equity:9.2f}")

        # 4. Results
        summary = pmb.get_summary(session_id)
        positions = pmb.get_positions(account_id)

        print(f"\n--- Results ---")
        print(f"Minutes:       {minute}")
        print(f"Final Equity:  ${summary['final_equity']:,.2f}")
        print(f"Total Return:  {summary['total_return']*100:+.2f}%")
        print(f"Fees Paid:     ${summary['fees_paid']:.2f}")
        print(f"Orders/Trades: {summary['num_orders']}/{summary['num_trades']}")

        if positions:
            for pos in positions:
                print(f"  {pos['instrument_id']} {pos['qty']} shares "
                      f"@ ${pos['avg_price']:.2f}, P&L ${pos['unrealized_pnl']:+.2f}")
        else:
            print("  Flat (no positions)")


if __name__ == "__main__":
    main()
