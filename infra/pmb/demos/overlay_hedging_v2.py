"""
Overlay Strategy Demo v2: Hedging (Protective Put) — Paper Spec

Paper parameters:
  - Underlyings: QQQ, NVDA
  - Position: 10,000 shares + 20% cash buffer
  - Rebalance: Weekly (every Monday)
  - DTE: 7-60 days
  - Strategy: Protective put (buy OTM put ~5% below current price)
  - Period: 2024-01-02 to 2024-12-31

Prerequisites:
  - UPQ running on http://127.0.0.1:19703
  - PMB running on http://127.0.0.1:19701

Usage:
  python demos/overlay_hedging_v2.py [--ticker QQQ]
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from demos.overlay_helpers import (
    discover_contracts_weekly, create_account, create_session,
    place_order, step_session, get_summary, get_export,
    get_positions, get_account, print_section, query_stock_price,
    compute_initial_cash, query_option_greeks, compute_effective_delta,
)
from demos.result_saver import ResultSaver


# --- Paper Spec Config ---
PAPER_TICKERS = ["QQQ", "NVDA"]
START_DATE = "2024-01-02"
END_DATE = "2024-12-31"
STOCK_QTY = 10_000
CASH_BUFFER_PCT = 0.20
OTM_PCT = 0.05
DTE_MIN = 7
DTE_MAX = 60


def run_single_ticker(underlying: str):
    """Run protective put strategy for a single underlying."""

    print_section(f"Overlay v2: Protective Put — {underlying}")
    print(f"  Period: {START_DATE} to {END_DATE}")
    print(f"  Stock Position: {STOCK_QTY:,} shares")
    print(f"  Cash Buffer: {CASH_BUFFER_PCT*100:.0f}%")
    print(f"  DTE Window: {DTE_MIN}-{DTE_MAX} days")
    print(f"  Rebalance: Weekly")

    # 1. Get reference price and compute initial cash
    print_section("Phase 1: Contract Discovery")
    ref_price = query_stock_price(underlying, START_DATE)
    if ref_price is None:
        print(f"  ERROR: Cannot get {underlying} price from UPQ. Skipping.")
        return
    print(f"  Reference price: ${ref_price:.2f}")

    initial_cash = compute_initial_cash(ref_price, STOCK_QTY, CASH_BUFFER_PCT)
    print(f"  Initial capital: ${initial_cash:,.2f}")
    print(f"    Stock notional: ${ref_price * STOCK_QTY:,.2f}")
    print(f"    Cash buffer: ${initial_cash - ref_price * STOCK_QTY:,.2f}")

    # 2. Pre-discover all weekly put contracts
    contracts = discover_contracts_weekly(
        underlying=underlying,
        start_date=START_DATE,
        end_date=END_DATE,
        option_type="P",
        otm_pct=OTM_PCT,
        ref_price=ref_price,
        dte_min=DTE_MIN,
        dte_max=DTE_MAX,
    )

    if not contracts:
        print(f"  ERROR: No option contracts found for {underlying}.")
        return

    print(f"\n  Discovered {len(contracts)} contracts for the year")
    option_tickers = [c["ticker"] for c in contracts]

    # 3. Create account + session
    print_section("Phase 2: Session Setup")
    acct = create_account(initial_cash=initial_cash, start_date=START_DATE)
    account_id = acct["account_id"]
    print(f"  Account: {account_id}")

    sess = create_session(
        account_id=account_id,
        start_ts=START_DATE,
        end_ts=END_DATE,
        stocks=[underlying],
        options=option_tickers,
        seed=601,
        run_id=f"overlay_pp_v2_{underlying.lower()}_2024",
    )
    session_id = sess["session_id"]
    print(f"  Session: {session_id}")

    # 4. Trading loop
    print_section(f"Phase 3: Running Protective Put — {underlying}")

    # Step to first day and buy stock
    step_data = step_session(session_id)
    events = step_data.get("events", [])
    market_tick = next((e for e in events if e["type"] == "MARKET_TICK"), None)
    initial_price = 0
    if market_tick and market_tick["payload"]["stocks"]:
        initial_price = market_tick["payload"]["stocks"][0]["close"]

    print(f"  Initial {underlying} price: ${initial_price:.2f}")
    print(f"  Buying {STOCK_QTY:,} shares...")

    place_order(session_id, account_id, "initial_stock_buy",
                {"type": "STOCK", "symbol": underlying}, "BUY", STOCK_QTY)
    step_session(session_id)

    # Track state
    active_put_contract = None
    contract_idx = 0
    options_log = []
    day_count = 2
    benchmark_initial_price = initial_price
    order_seq = 0

    print(f"\n  {'Day':>4} | {'Date':^10} | {underlying:>8} | {'Action':^40} | {'Equity':>14}")
    print("  " + "-" * 95)

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

        # Handle option expiry events
        for evt in events:
            if evt.get("type") == "OPTION_EXPIRY_EVENT":
                payload = evt.get("payload", {})
                contract = payload.get("contract", "")
                is_itm = payload.get("is_itm", False)

                if is_itm:
                    action_str = f"PUT EXPIRY ITM: {contract[-21:]} (protected)"
                    options_log.append({
                        "date": current_date, "action": "EXPIRY_ITM",
                        "contract": contract, "outcome": "closed at intrinsic",
                    })
                else:
                    action_str = f"PUT EXPIRY OTM: {contract[-21:]} worthless"
                    options_log.append({
                        "date": current_date, "action": "EXPIRY_OTM",
                        "contract": contract, "outcome": "expired worthless",
                    })

                print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                      f"{action_str:^40} | ${equity:13,.2f}")
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

                # Delta constraint: skip if adding long put would violate delta limit
                greeks = query_option_greeks(c["ticker"], current_date)
                if greeks and greeks.get("delta"):
                    option_pos_list = []
                    for p in get_positions(account_id):
                        if p.get("instrument_id", "").startswith("OPTION:"):
                            p_greeks = query_option_greeks(
                                p["instrument_id"].split(":", 1)[1], current_date)
                            if p_greeks and p_greeks.get("delta"):
                                option_pos_list.append({
                                    "delta": p_greeks["delta"],
                                    "qty": p["qty"],
                                })
                    eff_delta = compute_effective_delta(STOCK_QTY, option_pos_list)
                    new_delta = eff_delta + greeks["delta"] * 1 * 100  # long put
                    if abs(new_delta) > STOCK_QTY:
                        print(f"  DELTA CONSTRAINT: skip {c['ticker']}, "
                              f"effective delta would be {new_delta:.0f} > {STOCK_QTY:,}")
                        contract_idx += 1
                        continue

                order_seq += 1
                resp = place_order(
                    session_id, account_id, f"buy_put_{order_seq}",
                    {"type": "OPTION", "contract": c["ticker"]},
                    "BUY", 1,
                )
                if resp.get("ok"):
                    active_put_contract = c["ticker"]
                    contract_idx += 1
                    action_str = f"BUY PUT {c['ticker'][-21:]} @${c['strike']:.2f}"
                    print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                          f"{action_str:^40} | ${equity:13,.2f}")
                    options_log.append({
                        "date": current_date, "action": "BUY_PUT",
                        "contract": c["ticker"], "strike": c["strike"],
                        "expiry": c["expiry"], "premium": c["close"],
                    })

    # 5. Final results
    print_section(f"Results: Protective Put vs Buy-and-Hold — {underlying}")

    summary = get_summary(session_id)
    positions = get_positions(account_id)

    overlay_return = summary["total_return"]

    # Buy-and-hold benchmark
    final_price = current_price if current_price > 0 else initial_price
    stock_cost = benchmark_initial_price * STOCK_QTY
    benchmark_equity = (initial_cash - stock_cost) + final_price * STOCK_QTY
    benchmark_return = (benchmark_equity - initial_cash) / initial_cash

    print(f"\n  {'Metric':<25} {'Protective Put':>15} {'Buy-Hold':>15}")
    print("  " + "-" * 55)
    print(f"  {'Total Return':<25} {overlay_return*100:>14.2f}% {benchmark_return*100:>14.2f}%")
    print(f"  {'Final Equity':<25} ${summary['final_equity']:>13,.2f} ${benchmark_equity:>13,.2f}")
    print(f"  {'Max Drawdown':<25} {summary['max_drawdown']*100:>14.2f}%")
    print(f"  {'Hedge Cost (alpha)':<25} {(overlay_return - benchmark_return)*100:>14.2f}%")
    print(f"\n  Fees Paid: ${summary['fees_paid']:,.2f}")
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
        print(f"    {pos['instrument_id']:35s} {pos['qty']:>8,} @ ${pos['avg_price']:.2f}")

    # 6. Save results
    print_section("Saving Results")

    export_data = get_export(session_id)
    saver = ResultSaver(f"overlay_hedging_v2_{underlying.lower()}")

    saver.add_summary_line(f"Overlay Strategy v2: Protective Put (Hedging)")
    saver.add_summary_line(f"{'='*70}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Underlying: {underlying}")
    saver.add_summary_line(f"Period: {START_DATE} to {END_DATE}")
    saver.add_summary_line(f"Position: {STOCK_QTY:,} shares")
    saver.add_summary_line(f"Initial Capital: ${initial_cash:,.2f}")
    saver.add_summary_line(f"Rebalance: Weekly, DTE {DTE_MIN}-{DTE_MAX}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Performance:")
    saver.add_summary_line(f"  Protective Put Return: {overlay_return*100:+.2f}%")
    saver.add_summary_line(f"  Buy-and-Hold Return: {benchmark_return*100:+.2f}%")
    saver.add_summary_line(f"  Hedge Cost: {(overlay_return - benchmark_return)*100:+.2f}%")
    saver.add_summary_line(f"  Max Drawdown: {summary['max_drawdown']*100:.2f}%")
    saver.add_summary_line(f"  Fees Paid: ${summary['fees_paid']:,.2f}")
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

    return {
        "underlying": underlying,
        "overlay_return": overlay_return,
        "benchmark_return": benchmark_return,
        "premium_paid": total_premium * 100,
        "puts_bought": len(buy_actions),
        "itm_expiries": itm_count,
        "otm_expiries": otm_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Overlay v2: Protective Put (Paper Spec)")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Single ticker to run (default: run all paper tickers)")
    args = parser.parse_args()

    tickers = [args.ticker] if args.ticker else PAPER_TICKERS
    results = []

    for ticker in tickers:
        result = run_single_ticker(ticker)
        if result:
            results.append(result)

    if len(results) > 1:
        print_section("Cross-Ticker Summary: Protective Put v2")
        print(f"\n  {'Ticker':<8} {'PP Return':>12} {'Buy-Hold':>12} {'Alpha':>10} {'Puts':>8} {'Premium':>12}")
        print("  " + "-" * 68)
        for r in results:
            print(f"  {r['underlying']:<8} {r['overlay_return']*100:>11.2f}% "
                  f"{r['benchmark_return']*100:>11.2f}% "
                  f"{(r['overlay_return']-r['benchmark_return'])*100:>9.2f}% "
                  f"{r['puts_bought']:>8} ${r['premium_paid']:>10,.2f}")


if __name__ == "__main__":
    main()
