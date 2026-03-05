"""
Demo 3 (Client): Rolling Covered Call Strategy

Same strategy as api_raw/covered_call.py but using PMBClient.
Buy 100 NVDA shares, sell OTM calls every 2 weeks over 3 months.

Prerequisites:
  - UPQ running with NVDA stock + option data
  - PMB running on http://127.0.0.1:19320

Usage:
  cd qfinzero
  python demos/pmb/client_demos/covered_call.py
"""

import requests
from datetime import datetime, timedelta
from qfinzero.clients.pmb import PMBClient

UPQ_URL = "http://127.0.0.1:19350"


def query_option_chain(underlying, date, strike_min, strike_max, option_type="C", expiry_max=None):
    """Query option chain from UPQ."""
    try:
        params = {
            "underlying": underlying,
            "date": date,
            "strike_min": strike_min,
            "strike_max": strike_max,
            "type": option_type,
        }
        if expiry_max:
            params["expiry_max"] = expiry_max
        resp = requests.get(f"{UPQ_URL}/option/chain_query", params=params, timeout=5)
        return resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print(f"  Warning: Option chain query failed: {e}")
        return []


def select_otm_call(chain, current_price, target_otm_pct=0.10):
    """Select an OTM call closest to target_otm_pct above current price."""
    target_strike = current_price * (1 + target_otm_pct)
    otm = [o for o in chain if o["strike"] >= current_price and o.get("close", 0) > 0]
    if not otm:
        return None
    return min(otm, key=lambda x: abs(x["strike"] - target_strike))


def main():
    with PMBClient() as pmb:
        # 1. Create account with margin config
        acct = pmb.create_account(
            initial_cash=100000.0,
            start_date="2025-01-06",
            margin_config={
                "stock_initial": 0.50,
                "stock_maintenance": 0.25,
                "option_short_a": 0.20,
                "option_short_b": 0.10,
            },
        )
        account_id = acct["account_id"]
        print(f"Account: {account_id}, Cash: ${acct['account_state']['cash_available']:,.2f}")

        # 2. Create 3-month session
        sess = pmb.create_session(
            account_id=account_id,
            frequency="1d",
            start_ts="2025-01-06",
            end_ts="2025-04-06",
            universe={"stocks": ["NVDA"]},
            execution_config={
                "slippage_bps": 2.0,
                "fee_model": {
                    "stock_fee_per_share": 0.005,
                    "option_fee_per_contract": 0.65,
                },
            },
            reproducibility={"seed": 300, "run_id": "covered_call_rolling"},
        )
        session_id = sess["session_id"]
        print(f"Session: {session_id}, Period: Jan 6 - Apr 6, 2025")

        # 3. Step once and buy 100 shares
        result = pmb.step(session_id)
        initial_price = result.get_stock_price("NVDA") or 0
        print(f"Initial NVDA: ${initial_price:.2f}")

        pmb.buy(session_id, account_id, "NVDA", 100,
                client_order_id="initial_stock_buy")
        pmb.step(session_id)  # execute order
        print("Bought 100 NVDA shares")

        # 4. Rolling covered call loop
        print(f"\n{'Week':>4} | {'Date':^10} | {'NVDA':>8} | {'Action':^30} | {'Equity':>10}")
        print("-" * 75)

        day = 2
        option_positions = []
        option_chain_ok = True

        while True:
            result = pmb.step(session_id)
            if not result.is_running:
                break

            # Handle option expiry events
            for evt in result.events:
                if evt.get("type") == "OPTION_EXPIRY_EVENT":
                    payload = evt.get("payload", {})
                    contract = payload.get("contract", "")
                    is_itm = payload.get("is_itm", False)
                    assignment = payload.get("assignment")
                    if is_itm and assignment:
                        print(f"  [EXPIRY] {contract} expired ITM -> {assignment['side']} "
                              f"{assignment['qty']} shares at ${assignment['strike']:.2f}")
                    else:
                        print(f"  [EXPIRY] {contract} expired worthless")
                    option_positions = [p for p in option_positions
                                        if p.get("contract") != contract]

            day += 1
            price = result.get_stock_price("NVDA") or 0
            snap = result.get_snapshot()
            equity = snap["equity"] if snap else 0
            current_date = result.current_ts[:10]

            # Every 14 days: evaluate option position
            if day % 14 == 0:
                week = day // 7
                action = "Holding"

                if option_chain_ok and (not option_positions or day % 28 == 0):
                    query_date = datetime.strptime(current_date, "%Y-%m-%d")
                    expiry_max = (query_date + timedelta(days=45)).strftime("%Y-%m-%d")

                    chain = query_option_chain(
                        "NVDA", current_date,
                        strike_min=price * 1.05,
                        strike_max=price * 1.20,
                        expiry_max=expiry_max,
                    )

                    if chain:
                        opt = select_otm_call(chain, price)
                        if opt:
                            resp = pmb.sell_option(
                                session_id, account_id,
                                contract=opt["ticker"], qty=1,
                                client_order_id=f"sell_call_{week}",
                            )
                            if resp.get("ok"):
                                option_positions.append({
                                    "strike": opt["strike"],
                                    "premium": opt["close"],
                                    "contract": opt["ticker"],
                                    "date": current_date,
                                })
                                action = f"SELL {opt['ticker'][:20]}"
                            else:
                                action = "Order rejected"
                        else:
                            action = "No suitable option"
                            option_chain_ok = False
                    else:
                        option_chain_ok = False
                        # Simulated fallback
                        option_positions.append({
                            "strike": price * 1.10,
                            "premium": price * 0.03,
                            "date": current_date,
                            "simulated": True,
                        })
                        action = f"SIM: SELL CALL @ ${price * 1.10:.0f}"

                print(f"{week:4d} | {current_date:^10} | ${price:7.2f} | {action:^30} | ${equity:9.2f}")

        # 5. Final results
        summary = pmb.get_summary(session_id)
        positions = pmb.get_positions(account_id)

        print(f"\n--- Results ---")
        print(f"Final Equity:  ${summary['final_equity']:,.2f}")
        print(f"Total Return:  {summary['total_return']*100:+.2f}%")
        print(f"Max Drawdown:  {summary['max_drawdown']*100:.2f}%")
        print(f"Fees Paid:     ${summary['fees_paid']:.2f}")
        print(f"Orders/Trades: {summary['num_orders']}/{summary['num_trades']}")
        print(f"Calls Sold:    {len(option_positions)}")

        total_premium = sum(o["premium"] for o in option_positions)
        print(f"Total Premium: ${total_premium:,.2f}")

        print(f"\nPositions:")
        for pos in positions:
            print(f"  {pos['instrument_id']:30s} {pos['qty']:6d} @ ${pos['avg_price']:.2f}, "
                  f"P&L ${pos['unrealized_pnl']:+.2f}")

        acct_state = pmb.get_account(account_id)
        print(f"\nAccount: Cash ${acct_state['cash_available']:,.2f}, "
              f"Equity ${acct_state['equity']:,.2f}, "
              f"Margin {acct_state['margin_status']}")


if __name__ == "__main__":
    main()
