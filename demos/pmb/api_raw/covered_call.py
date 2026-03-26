"""
Demo 3: Rolling Covered Call Strategy with Options (3 Months)

Strategy:
  - Initial: Buy 100 shares of NVDA
  - Every 2 weeks: Sell 1 call option ~10% above current price, expiring ~1 month out
  - Monthly: Roll the option position (buy back old, sell new at higher strike)
  - Run for 3 months with detailed tracking

Prerequisites:
  - UPQ running on http://127.0.0.1:19703 with NVDA stock data
  - PMB running on http://127.0.0.1:19701

Note: This demo simulates a rolling covered call strategy.
      If actual option data is unavailable from UPQ, it will track stock only.

Usage:
  python demos/covered_call.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
from datetime import datetime, timedelta
from demos.result_saver import ResultSaver
from qfinzero.config import PMB_URL, UPQ_URL


BASE = PMB_URL
OPTION_CHAIN_API = UPQ_URL


def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def get_current_stock_price(session_id):
    """Get current stock price from market snapshot."""
    resp = requests.get(f"{BASE}/v1/sessions/{session_id}/market")
    if resp.status_code == 200:
        data = resp.json()
        if data.get("stocks"):
            return data["stocks"][0]["close"]
    return None


def get_option_chain(underlying, date, strike_min, strike_max, option_type="C", expiry_max=None):
    """Query option chain from the option service.

    Args:
        underlying: Stock symbol (e.g., "NVDA")
        date: Query date in YYYY-MM-DD format
        strike_min: Minimum strike price
        strike_max: Maximum strike price
        option_type: "C" for calls, "P" for puts
        expiry_max: Maximum expiry date (optional)

    Returns:
        List of option contracts with close, strike, expiry, ticker, etc.
    """
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

        resp = requests.get(f"{OPTION_CHAIN_API}/option/chain_query", params=params, timeout=5)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"   Warning: Option chain query failed with status {resp.status_code}")
            return []
    except Exception as e:
        print(f"   Warning: Could not reach option chain service: {e}")
        return []


def select_otm_call(option_chain, current_price, target_otm_pct=0.10, target_days=30):
    """Select an appropriate OTM call option.

    Args:
        option_chain: List of option contracts
        current_price: Current stock price
        target_otm_pct: Target out-of-the-money percentage (0.10 = 10%)
        target_days: Target days to expiration

    Returns:
        Selected option contract dict, or None
    """
    if not option_chain:
        return None

    target_strike = current_price * (1 + target_otm_pct)

    # Filter calls that are OTM
    otm_calls = [
        opt for opt in option_chain
        if opt["strike"] >= current_price and opt.get("close", 0) > 0
    ]

    if not otm_calls:
        return None

    # Find the call closest to our target strike
    best_option = min(otm_calls, key=lambda x: abs(x["strike"] - target_strike))
    return best_option


def main():
    print_section("Rolling Covered Call Strategy: NVDA 3-Month Demo")

    # 1. Create account
    print("\n1. Creating account with $100k...")
    acct_resp = requests.post(
        f"{BASE}/v1/accounts",
        json={
            "account_type": "MARGIN",
            "initial_cash": 100000.0,
            "start_date": "2025-01-06",
            "margin_config": {
                "stock_initial": 0.50,
                "stock_maintenance": 0.25,
                "option_short_a": 0.20,
                "option_short_b": 0.10,
            },
        },
    )
    acct = acct_resp.json()
    account_id = acct["account_id"]
    print(f"   Account: {account_id}")
    print(f"   Initial Cash: ${acct['account_state']['cash_available']:,.2f}")

    # 2. Create session: NVDA for 3 months (Jan-Mar 2025)
    print("\n2. Creating session (3 months, daily frequency)...")
    sess_resp = requests.post(
        f"{BASE}/v1/sessions",
        json={
            "account_id": account_id,
            "frequency": "1d",
            "start_ts": "2025-01-06",
            "end_ts": "2025-04-06",  # 3 months
            "universe": {"stocks": ["NVDA"]},
            "execution_config": {
                "slippage_bps": 2.0,
                "fee_model": {
                    "stock_fee_per_share": 0.005,
                    "option_fee_per_contract": 0.65,
                },
            },
            "reproducibility": {"seed": 300, "run_id": "covered_call_rolling"},
        },
    )
    sess = sess_resp.json()
    session_id = sess["session_id"]
    print(f"   Session: {session_id}")
    print(f"   Period: Jan 6 - Apr 6, 2025 (3 months)")

    # 3. Initial position: Buy 100 shares
    print("\n3. Setting up initial position...")

    # Step to first day
    step_resp = requests.post(f"{BASE}/v1/sessions/{session_id}/step", json={"step": 1})
    events = step_resp.json().get("events", [])

    # Get initial price
    market_tick = next((e for e in events if e["type"] == "MARKET_TICK"), None)
    initial_price = 0
    if market_tick and market_tick["payload"]["stocks"]:
        initial_price = market_tick["payload"]["stocks"][0]["close"]

    print(f"   Initial NVDA price: ${initial_price:.2f}")

    # Buy 100 shares
    print("\n   Buying 100 shares NVDA...")
    buy_resp = requests.post(
        f"{BASE}/v1/orders",
        json={
            "session_id": session_id,
            "account_id": account_id,
            "client_order_id": "initial_stock_buy",
            "order": {
                "instrument": {"type": "STOCK", "symbol": "NVDA"},
                "side": "BUY",
                "order_type": "MARKET",
                "qty": 100,
                "time_in_force": "DAY",
            },
        },
    )
    print(f"   Order placed: {buy_resp.json().get('order_id')}")

    # Step to execute
    requests.post(f"{BASE}/v1/sessions/{session_id}/step", json={"step": 1})

    # 4. Rolling strategy simulation
    print("\n4. Running 3-month rolling covered call strategy...")
    print(f"\n   Strategy Rules:")
    print(f"   - Every 2 weeks: Evaluate option positions")
    print(f"   - Sell calls 10% above current price")
    print(f"   - Roll monthly to new strikes")
    print(f"\n   {'Week':>4} | {'Date':^10} | {'NVDA':>8} | {'Action':^30} | {'Stock':>6} | {'Equity':>10}")
    print("   " + "-" * 90)

    day_count = 2  # Already stepped 2 days
    week_count = 0
    actions_log = []
    last_action_day = 0
    option_positions = []  # Track sold options
    option_chain_available = True  # Flag to track if option service is working

    while True:
        # Step one day
        step_resp = requests.post(f"{BASE}/v1/sessions/{session_id}/step", json={"step": 1})
        step_data = step_resp.json()

        if not step_data.get("ok"):
            break

        clock = step_data.get("clock", {})
        if clock.get("status") != "RUNNING":
            break

        events = step_data.get("events", [])
        day_count += 1

        # Get current state
        market_tick = next((e for e in events if e["type"] == "MARKET_TICK"), None)
        current_price = 0
        if market_tick and market_tick["payload"]["stocks"]:
            current_price = market_tick["payload"]["stocks"][0]["close"]

        account_snap = next((e for e in events if e["type"] == "ACCOUNT_SNAPSHOT"), None)
        equity = 0
        stock_pos = 0
        if account_snap:
            snap = account_snap["payload"]
            equity = snap["equity"]
            if snap["positions"]:
                stock_pos = snap["positions"][0].get("qty", 0)

        current_date = clock["current_ts"][:10]

        # Every 14 days (2 weeks), take action
        if day_count % 14 == 0:
            week_count = day_count // 7
            action = "Evaluating position"

            # Query real option chain
            if option_chain_available and (len(option_positions) == 0 or day_count % 28 == 0):
                # Calculate target strike (10% OTM)
                target_strike_min = current_price * 1.05
                target_strike_max = current_price * 1.20

                # Calculate expiry ~1 month out
                from datetime import datetime, timedelta
                query_date = datetime.strptime(current_date, "%Y-%m-%d")
                expiry_max = (query_date + timedelta(days=45)).strftime("%Y-%m-%d")

                # Query option chain
                chain = get_option_chain(
                    underlying="NVDA",
                    date=current_date,
                    strike_min=target_strike_min,
                    strike_max=target_strike_max,
                    option_type="C",
                    expiry_max=expiry_max
                )

                if chain:
                    # Select best option
                    selected_option = select_otm_call(chain, current_price, target_otm_pct=0.10)

                    if selected_option:
                        strike_price = selected_option["strike"]
                        premium = selected_option["close"]
                        contract_ticker = selected_option["ticker"]
                        expiry = selected_option["expiry"]

                        # Place real sell order through PMB
                        sell_resp = requests.post(
                            f"{BASE}/v1/orders",
                            json={
                                "session_id": session_id,
                                "account_id": account_id,
                                "client_order_id": f"sell_call_{week_count}",
                                "order": {
                                    "instrument": {"type": "OPTION", "contract": contract_ticker},
                                    "side": "SELL",
                                    "order_type": "MARKET",
                                    "qty": 1,
                                    "time_in_force": "GTC",
                                },
                            },
                        )

                        if sell_resp.json().get("ok"):
                            option_positions.append({
                                "strike": strike_price,
                                "entry_price": current_price,
                                "premium": premium,
                                "contract": contract_ticker,
                                "expiry": expiry,
                                "day": day_count,
                                "date": current_date,
                            })
                            action = f"SELL {contract_ticker[:15]}... @ ${strike_price:.2f}"
                            actions_log.append({
                                "week": week_count,
                                "date": current_date,
                                "price": current_price,
                                "action": action,
                                "strike": strike_price,
                                "premium": premium,
                                "contract": contract_ticker,
                                "expiry": expiry,
                            })
                        else:
                            action = f"Order rejected"
                    else:
                        action = "No suitable options found"
                        option_chain_available = False  # Disable further queries
                else:
                    # Fallback to simulated premium if option chain not available
                    option_chain_available = False
                    strike_price = current_price * 1.10
                    premium = current_price * 0.03
                    option_positions.append({
                        "strike": strike_price,
                        "entry_price": current_price,
                        "premium": premium,
                        "day": day_count,
                        "date": current_date,
                        "simulated": True,
                    })
                    action = f"SIMULATED: SELL CALL @ ${strike_price:.2f}"
                    actions_log.append({
                        "week": week_count,
                        "date": current_date,
                        "price": current_price,
                        "action": action,
                        "strike": strike_price,
                        "premium": premium,
                        "simulated": True,
                    })
            else:
                action = "Holding current call position"

            print(f"   {week_count:4d} | {current_date:^10} | ${current_price:7.2f} | {action:^30} | {stock_pos:6d} | ${equity:9.2f}")
            last_action_day = day_count

        # Print monthly summaries
        if day_count % 30 == 0:
            month = day_count // 30
            print(f"   {'':>4} | {'':^10} | {'':>8} | {'--- Month ' + str(month) + ' Complete ---':^30} | {'':>6} | ${equity:9.2f}")

    # 5. Final Summary
    print_section("Final Results - 3 Month Rolling Covered Call")

    summary_resp = requests.get(f"{BASE}/v1/sessions/{session_id}/summary")
    summary = summary_resp.json()

    print(f"\n  Strategy: Rolling Covered Call on NVDA")
    print(f"  Period: {summary['start_ts'][:10]} to {summary['end_ts'][:10]} (3 months)")
    print(f"  Total trading days: {day_count}")
    print(f"  Total weeks: {week_count}")
    print(f"\n  Performance:")
    print(f"  Initial Equity: ${100000:,.2f}")
    print(f"  Final Equity:   ${summary['final_equity']:,.2f}")
    print(f"  Total Return:   {summary['total_return']*100:+.2f}%")
    print(f"  Max Drawdown:   {summary['max_drawdown']*100:.2f}%")
    print(f"  Fees Paid:      ${summary['fees_paid']:.2f}")
    print(f"\n  Trading Activity:")
    print(f"  Orders: {summary['num_orders']}")
    print(f"  Trades: {summary['num_trades']}")

    # Action log
    print(f"\n  Covered Call Actions (Every 2 Weeks):")
    print(f"  {'Week':>4} | {'Date':^10} | {'NVDA':>8} | {'Strike':>8} | {'Premium':>8} | {'Expiry':^10} | Contract")
    print("  " + "-" * 95)
    for action in actions_log:
        contract_str = action.get('contract', 'SIMULATED')[:20] if not action.get('simulated') else 'SIMULATED'
        expiry_str = action.get('expiry', 'N/A')
        print(
            f"  {action['week']:4d} | {action['date']:^10} | "
            f"${action['price']:7.2f} | ${action['strike']:7.2f} | "
            f"${action['premium']:7.2f} | {expiry_str:^10} | {contract_str}"
        )

    # Option income summary
    total_premium = sum(opt['premium'] for opt in option_positions)
    real_options = [opt for opt in option_positions if not opt.get('simulated')]
    simulated_options = [opt for opt in option_positions if opt.get('simulated')]

    print(f"\n  Option Income Summary:")
    print(f"  Total calls sold: {len(option_positions)}")
    if real_options:
        print(f"  Real options: {len(real_options)} (premium: ${sum(opt['premium'] for opt in real_options):,.2f})")
    if simulated_options:
        print(f"  Simulated: {len(simulated_options)} (estimated premium: ${sum(opt['premium'] for opt in simulated_options):,.2f})")
    print(f"  Estimated premium collected: ${total_premium:,.2f}")
    print(f"  Average strike: ${sum(opt['strike'] for opt in option_positions) / len(option_positions) if option_positions else 0:.2f}")

    # Final positions
    pos_resp = requests.get(f"{BASE}/v1/accounts/{account_id}/positions")
    positions = pos_resp.json().get("positions", [])

    print("\n  Final Positions:")
    if positions:
        for pos in positions:
            iid = pos["instrument_id"]
            print(
                f"    {iid:35s} {pos['qty']:6d} @ ${pos['avg_price']:.2f}, "
                f"mark ${pos['mark_price']:.2f}, P&L ${pos['unrealized_pnl']:+.2f}"
            )
    else:
        print("    No positions")

    # Account state
    acct_resp = requests.get(f"{BASE}/v1/accounts/{account_id}")
    acct_state = acct_resp.json()

    print("\n  Final Account State:")
    print(f"    Cash Available:  ${acct_state['cash_available']:,.2f}")
    print(f"    Total Equity:    ${acct_state['equity']:,.2f}")
    print(f"    Buying Power:    ${acct_state['buying_power']:,.2f}")
    print(f"    Margin Status:   {acct_state['margin_status']}")

    # 6. Save results
    print_section("Saving Results")

    # Get export data
    export_resp = requests.get(f"{BASE}/v1/sessions/{session_id}/export?format=json")
    export_data = export_resp.json()

    saver = ResultSaver("covered_call_3month")

    # Build text report
    saver.add_summary_line(f"Rolling Covered Call Strategy: NVDA 3-Month Demo")
    saver.add_summary_line(f"{'='*70}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Strategy: Rolling Covered Call on NVDA")
    saver.add_summary_line(f"Period: {summary['start_ts'][:10]} to {summary['end_ts'][:10]} (3 months)")
    saver.add_summary_line(f"Total trading days: {day_count}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Performance:")
    saver.add_summary_line(f"  Initial Equity: ${100000:,.2f}")
    saver.add_summary_line(f"  Final Equity:   ${summary['final_equity']:,.2f}")
    saver.add_summary_line(f"  Total Return:   {summary['total_return']*100:+.2f}%")
    saver.add_summary_line(f"  Max Drawdown:   {summary['max_drawdown']*100:.2f}%")
    saver.add_summary_line(f"  Fees Paid:      ${summary['fees_paid']:.2f}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Trading Activity:")
    saver.add_summary_line(f"  Orders: {summary['num_orders']}")
    saver.add_summary_line(f"  Trades: {summary['num_trades']}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Covered Call Actions (Every 2 Weeks):")
    for action in actions_log:
        contract_info = f"contract={action.get('contract', 'SIMULATED')[:25]}" if not action.get('simulated') else "SIMULATED"
        expiry_info = f"expiry={action.get('expiry', 'N/A')}" if not action.get('simulated') else ""
        saver.add_summary_line(
            f"  Week {action['week']:2d} ({action['date']}): "
            f"Sold call @ ${action['strike']:.2f} strike, "
            f"premium ${action['premium']:.2f}, stock @ ${action['price']:.2f}, "
            f"{contract_info} {expiry_info}".strip()
        )
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Option Income Summary:")
    saver.add_summary_line(f"  Total calls sold: {len(option_positions)}")
    if real_options:
        saver.add_summary_line(f"  Real options: {len(real_options)} (premium: ${sum(opt['premium'] for opt in real_options):,.2f})")
    if simulated_options:
        saver.add_summary_line(f"  Simulated: {len(simulated_options)} (estimated: ${sum(opt['premium'] for opt in simulated_options):,.2f})")
    saver.add_summary_line(f"  Estimated premium collected: ${total_premium:,.2f}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Final Positions:")
    if positions:
        for pos in positions:
            iid = pos["instrument_id"]
            saver.add_summary_line(
                f"  {iid:35s} {pos['qty']:6d} @ ${pos['avg_price']:.2f}, "
                f"mark ${pos['mark_price']:.2f}, P&L ${pos['unrealized_pnl']:+.2f}"
            )
    else:
        saver.add_summary_line("  No positions")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Final Account State:")
    saver.add_summary_line(f"  Cash Available:  ${acct_state['cash_available']:,.2f}")
    saver.add_summary_line(f"  Total Equity:    ${acct_state['equity']:,.2f}")
    saver.add_summary_line(f"  Buying Power:    ${acct_state['buying_power']:,.2f}")
    saver.add_summary_line(f"  Margin Status:   {acct_state['margin_status']}")

    saver.save_summary(summary)
    saver.save_holdings(positions)
    saver.save_operations(export_data.get("orders", []), export_data.get("trades", []))
    saver.save_equity_curve(export_data.get("equity_curve", []))
    saver.save_text_report()

    saver.print_saved_location()


if __name__ == "__main__":
    main()
