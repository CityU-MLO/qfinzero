"""
Overlay Strategy Demo: Hedging (Protective Put)

Strategy:
  - Buy 100 shares AAPL on day 1
  - Each month: buy 1 OTM put (~5% below current price, ~30 days to expiry)
  - Let puts expire naturally (Plan A: no early roll)
  - Put ITM: closed at intrinsic value; OTM: expired worthless
  - Run for full year 2024

Prerequisites:
  - UPQ running on http://127.0.0.1:19350 with AAPL 2024 daily data
  - UPQ option chain on http://127.0.0.1:19350 with AAPL 2024 option data
  - PMB running on http://127.0.0.1:19380

Usage:
  python demos/overlay_hedging.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from demos.overlay_helpers import (
    PMB_BASE,
    discover_contracts, create_account, create_session,
    place_order, step_session, get_summary, get_export,
    get_positions, get_account, print_section, query_stock_price,
)
from demos.result_saver import ResultSaver


# --- Config ---
UNDERLYING = "AAPL"
START_DATE = "2024-01-02"
END_DATE = "2024-12-31"
INITIAL_CASH = 100_000.0
STOCK_QTY = 100
OTM_PCT = 0.05  # 5% OTM for put strike


def get_reference_price(underlying: str, date: str) -> float:
    """Get approximate stock price from UPQ for strike estimation."""
    price = query_stock_price(underlying, date)
    return price if price is not None else 185.0


def main():
    print_section("Overlay Strategy: Protective Put (Hedging)")
    print(f"  Underlying: {UNDERLYING}")
    print(f"  Period: {START_DATE} to {END_DATE}")
    print(f"  Initial Capital: ${INITIAL_CASH:,.2f}")
    print(f"  Stock Position: {STOCK_QTY} shares")
    print(f"  Put Strike Target: {OTM_PCT*100:.0f}% OTM")

    # 1. Get reference price
    print_section("Phase 1: Contract Discovery")
    ref_price = get_reference_price(UNDERLYING, START_DATE)
    print(f"  Reference price: ${ref_price:.2f}")

    # 2. Pre-discover all monthly put contracts
    contracts = discover_contracts(
        underlying=UNDERLYING,
        start_date=START_DATE,
        end_date=END_DATE,
        option_type="P",
        otm_pct=OTM_PCT,
        ref_price=ref_price,
    )

    if not contracts:
        print("  ERROR: No option contracts found. Check UPQ data availability.")
        return

    print(f"\n  Discovered {len(contracts)} contracts for the year")
    option_tickers = [c["ticker"] for c in contracts]

    # 3. Create account + session
    print_section("Phase 2: Session Setup")
    acct = create_account(initial_cash=INITIAL_CASH, start_date=START_DATE)
    account_id = acct["account_id"]
    print(f"  Account: {account_id}")

    sess = create_session(
        account_id=account_id,
        start_ts=START_DATE,
        end_ts=END_DATE,
        stocks=[UNDERLYING],
        options=option_tickers,
        seed=402,
        run_id="overlay_protective_put_2024",
    )
    session_id = sess["session_id"]
    print(f"  Session: {session_id}")

    # 4. Trading loop
    print_section("Phase 3: Running Protective Put Strategy")

    # Step to first day and buy stock
    step_data = step_session(session_id)
    events = step_data.get("events", [])
    market_tick = next((e for e in events if e["type"] == "MARKET_TICK"), None)
    initial_price = 0
    if market_tick and market_tick["payload"]["stocks"]:
        initial_price = market_tick["payload"]["stocks"][0]["close"]

    print(f"  Initial {UNDERLYING} price: ${initial_price:.2f}")
    print(f"  Buying {STOCK_QTY} shares...")

    place_order(session_id, account_id, "initial_stock_buy",
                {"type": "STOCK", "symbol": UNDERLYING}, "BUY", STOCK_QTY)
    step_session(session_id)

    # Track state
    active_put_contract = None
    contract_idx = 0
    options_log = []
    day_count = 2
    benchmark_equity = INITIAL_CASH
    benchmark_initial_price = initial_price
    order_seq = 0

    print(f"\n  {'Day':>4} | {'Date':^10} | {UNDERLYING:>8} | {'Action':^35} | {'Equity':>10}")
    print("  " + "-" * 85)

    while True:
        step_data = step_session(session_id)
        if not step_data.get("ok"):
            break

        clock = step_data.get("clock", {})
        if clock.get("status") != "RUNNING":
            break

        events = step_data.get("events", [])
        day_count += 1
        current_date = clock.get("current_ts", "")[:10]

        # Extract market data
        market_tick = next((e for e in events if e["type"] == "MARKET_TICK"), None)
        current_price = 0
        if market_tick and market_tick["payload"]["stocks"]:
            current_price = market_tick["payload"]["stocks"][0]["close"]

        # Extract equity
        account_snap = next((e for e in events if e["type"] == "ACCOUNT_SNAPSHOT"), None)
        equity = 0
        if account_snap:
            equity = account_snap["payload"]["equity"]

        # Update benchmark
        if benchmark_initial_price > 0 and current_price > 0:
            stock_cost = benchmark_initial_price * STOCK_QTY
            benchmark_equity = (INITIAL_CASH - stock_cost) + current_price * STOCK_QTY

        # Handle option expiry events
        for evt in events:
            if evt.get("type") == "OPTION_EXPIRY_EVENT":
                payload = evt.get("payload", {})
                contract = payload.get("contract", "")
                is_itm = payload.get("is_itm", False)

                if is_itm:
                    action_str = f"PUT EXPIRY ITM: {contract[-15:]} (protected)"
                    options_log.append({
                        "date": current_date, "action": "EXPIRY_ITM",
                        "contract": contract, "outcome": "closed at intrinsic",
                    })
                else:
                    action_str = f"PUT EXPIRY OTM: {contract[-15:]} worthless"
                    options_log.append({
                        "date": current_date, "action": "EXPIRY_OTM",
                        "contract": contract, "outcome": "expired worthless",
                    })

                print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                      f"{action_str:^35} | ${equity:9.2f}")
                active_put_contract = None

        # Open new put if no active position
        if active_put_contract is None and contract_idx < len(contracts):
            while contract_idx < len(contracts):
                c = contracts[contract_idx]
                if c["expiry"] >= current_date:
                    break
                contract_idx += 1

            if contract_idx < len(contracts):
                c = contracts[contract_idx]
                order_seq += 1
                resp = place_order(
                    session_id, account_id, f"buy_put_{order_seq}",
                    {"type": "OPTION", "contract": c["ticker"]},
                    "BUY", 1,
                )
                if resp.get("ok"):
                    active_put_contract = c["ticker"]
                    contract_idx += 1
                    action_str = f"BUY PUT {c['ticker'][-15:]} @${c['strike']:.2f}"
                    print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                          f"{action_str:^35} | ${equity:9.2f}")
                    options_log.append({
                        "date": current_date, "action": "BUY_PUT",
                        "contract": c["ticker"], "strike": c["strike"],
                        "expiry": c["expiry"], "premium": c["close"],
                    })

    # 5. Final results
    print_section("Results: Protective Put vs Buy-and-Hold")

    summary = get_summary(session_id)
    positions = get_positions(account_id)
    acct_state = get_account(account_id)

    overlay_return = summary["total_return"]
    benchmark_return = (benchmark_equity - INITIAL_CASH) / INITIAL_CASH

    print(f"\n  {'Metric':<25} {'Protective Put':>15} {'Buy-and-Hold':>15}")
    print("  " + "-" * 55)
    print(f"  {'Total Return':<25} {overlay_return*100:>14.2f}% {benchmark_return*100:>14.2f}%")
    print(f"  {'Final Equity':<25} ${summary['final_equity']:>13,.2f} ${benchmark_equity:>13,.2f}")
    print(f"  {'Max Drawdown':<25} {summary['max_drawdown']*100:>14.2f}% {'N/A':>15}")
    print(f"  {'Hedge Cost (alpha)':<25} {(overlay_return - benchmark_return)*100:>14.2f}%")
    print(f"\n  Fees Paid: ${summary['fees_paid']:.2f}")
    print(f"  Orders: {summary['num_orders']}")
    print(f"  Trades: {summary['num_trades']}")

    # Premium summary
    buy_actions = [o for o in options_log if o["action"] == "BUY_PUT"]
    total_premium = sum(o.get("premium", 0) for o in buy_actions)
    itm_count = sum(1 for o in options_log if o["action"] == "EXPIRY_ITM")
    otm_count = sum(1 for o in options_log if o["action"] == "EXPIRY_OTM")

    print(f"\n  Option Activity:")
    print(f"    Puts bought: {len(buy_actions)}")
    print(f"    Est. total premium paid: ${total_premium * 100:,.2f} (x100 multiplier)")
    print(f"    Expired OTM (lost premium): {otm_count}")
    print(f"    Expired ITM (protection used): {itm_count}")

    # Final positions
    print(f"\n  Final Positions:")
    for pos in positions:
        print(f"    {pos['instrument_id']:35s} {pos['qty']:6d} @ ${pos['avg_price']:.2f}")

    # 6. Save results
    print_section("Saving Results")

    export_data = get_export(session_id)
    saver = ResultSaver("overlay_hedging")

    saver.add_summary_line(f"Overlay Strategy: Protective Put (Hedging)")
    saver.add_summary_line(f"{'='*70}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Underlying: {UNDERLYING}")
    saver.add_summary_line(f"Period: {START_DATE} to {END_DATE}")
    saver.add_summary_line(f"Initial Capital: ${INITIAL_CASH:,.2f}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Performance:")
    saver.add_summary_line(f"  Protective Put Return: {overlay_return*100:+.2f}%")
    saver.add_summary_line(f"  Buy-and-Hold Return: {benchmark_return*100:+.2f}%")
    saver.add_summary_line(f"  Hedge Cost: {(overlay_return - benchmark_return)*100:+.2f}%")
    saver.add_summary_line(f"  Max Drawdown: {summary['max_drawdown']*100:.2f}%")
    saver.add_summary_line(f"  Fees Paid: ${summary['fees_paid']:.2f}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Option Activity:")
    saver.add_summary_line(f"  Puts bought: {len(buy_actions)}")
    saver.add_summary_line(f"  Est. premium paid: ${total_premium * 100:,.2f}")
    saver.add_summary_line(f"  Expired OTM: {otm_count}")
    saver.add_summary_line(f"  Expired ITM: {itm_count}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Options Log:")
    for o in options_log:
        saver.add_summary_line(f"  {o['date']}: {o['action']} {o.get('contract', '')}")

    saver.save_summary(summary)
    saver.save_holdings(positions)
    saver.save_operations(export_data.get("orders", []), export_data.get("trades", []))
    saver.save_equity_curve(export_data.get("equity_curve", []))
    saver.save_text_report()
    saver.print_saved_location()


if __name__ == "__main__":
    main()
