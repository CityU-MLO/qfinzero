"""
Overlay Strategy Demo v2: Profit Increase (Covered Call) — Paper Spec

Paper parameters:
  - Underlyings: QQQ, NVDA, USO
  - Position: 10,000 shares + 20% cash buffer
  - Rebalance: Weekly (every Monday)
  - DTE: 7-45 days
  - Strategy: Covered call (sell OTM call ~5% above current price)
  - Period: 2024-01-02 to 2024-12-31

Prerequisites:
  - UPQ running on http://127.0.0.1:19703
  - PMB running on http://127.0.0.1:19701

Usage:
  python demos/overlay_profit_increase_v2.py [--ticker QQQ]
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from demos.overlay_helpers import (
    discover_contracts_weekly, create_account, create_session,
    place_order, step_session, get_summary, get_export,
    get_positions, get_account, print_section, query_stock_price,
    compute_initial_cash, get_etf_daily_prices,
)
from demos.result_saver import ResultSaver


# --- Paper Spec Config ---
PAPER_TICKERS = ["QQQ", "NVDA", "USO"]
ETF_BENCHMARKS = {"QQQ": "JEPQ", "NVDA": "NVDY", "USO": "USOY"}
START_DATE = "2024-01-02"
END_DATE = "2024-12-31"
STOCK_QTY = 10_000
CASH_BUFFER_PCT = 0.20
OTM_PCT = 0.05
DTE_MIN = 7
DTE_MAX = 45


def run_single_ticker(underlying: str):
    """Run covered call strategy for a single underlying."""

    etf_ticker = ETF_BENCHMARKS.get(underlying)

    print_section(f"Overlay v2: Covered Call — {underlying}")
    print(f"  Period: {START_DATE} to {END_DATE}")
    print(f"  Stock Position: {STOCK_QTY:,} shares")
    print(f"  Cash Buffer: {CASH_BUFFER_PCT*100:.0f}%")
    print(f"  DTE Window: {DTE_MIN}-{DTE_MAX} days")
    print(f"  Rebalance: Weekly")
    if etf_ticker:
        print(f"  ETF Benchmark: {etf_ticker}")

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

    # 2. Pre-discover all weekly call contracts
    contracts = discover_contracts_weekly(
        underlying=underlying,
        start_date=START_DATE,
        end_date=END_DATE,
        option_type="C",
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

    # 3. Fetch ETF benchmark data
    etf_prices = {}
    if etf_ticker:
        etf_data = get_etf_daily_prices(etf_ticker, START_DATE, END_DATE)
        etf_prices = {row["date"]: row["close"] for row in etf_data}
        print(f"  ETF benchmark {etf_ticker}: {len(etf_prices)} daily prices loaded")

    # 4. Create account + session
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
        seed=501,
        run_id=f"overlay_cc_v2_{underlying.lower()}_2024",
    )
    session_id = sess["session_id"]
    print(f"  Session: {session_id}")

    # 5. Trading loop
    print_section(f"Phase 3: Running Covered Call — {underlying}")

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
    active_call_contract = None
    contract_idx = 0
    options_log = []
    day_count = 2
    benchmark_initial_price = initial_price
    order_seq = 0
    etf_initial_price = None

    # ETF benchmark initial price
    if etf_prices:
        etf_initial_price = etf_prices.get(START_DATE)

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

        # Extract equity and stock position
        account_snap = next((e for e in events if e["type"] == "ACCOUNT_SNAPSHOT"), None)
        equity = 0
        stock_pos = 0
        if account_snap:
            snap = account_snap["payload"]
            equity = snap["equity"]
            for pos in snap.get("positions", []):
                if pos.get("instrument_id", "").startswith("STOCK:"):
                    stock_pos = pos["qty"]

        # Handle option expiry events
        for evt in events:
            if evt.get("type") == "OPTION_EXPIRY_EVENT":
                payload = evt.get("payload", {})
                contract = payload.get("contract", "")
                is_itm = payload.get("is_itm", False)
                assignment = payload.get("assignment")

                if is_itm and assignment:
                    action_str = (f"EXPIRY ITM: {contract[-21:]} -> "
                                  f"{assignment['side']} {assignment['qty']}sh")
                    options_log.append({
                        "date": current_date, "action": "EXPIRY_ITM",
                        "contract": contract, "strike": assignment["strike"],
                        "outcome": f"call-away {assignment['qty']} shares",
                    })
                else:
                    action_str = f"EXPIRY OTM: {contract[-21:]} worthless"
                    options_log.append({
                        "date": current_date, "action": "EXPIRY_OTM",
                        "contract": contract, "outcome": "expired worthless",
                    })

                print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                      f"{action_str:^40} | ${equity:13,.2f}")
                active_call_contract = None

        # Re-buy stock if called away
        if stock_pos < STOCK_QTY and current_price > 0:
            rebuy_qty = STOCK_QTY - stock_pos
            order_seq += 1
            place_order(session_id, account_id, f"rebuy_stock_{order_seq}",
                        {"type": "STOCK", "symbol": underlying}, "BUY", rebuy_qty)
            action_str = f"RE-BUY {rebuy_qty:,} shares"
            print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                  f"{action_str:^40} | ${equity:13,.2f}")

        # Open new call if no active position
        if active_call_contract is None and contract_idx < len(contracts):
            while contract_idx < len(contracts):
                c = contracts[contract_idx]
                if c["expiry"] >= current_date:
                    break
                contract_idx += 1

            if contract_idx < len(contracts):
                c = contracts[contract_idx]
                order_seq += 1
                resp = place_order(
                    session_id, account_id, f"sell_call_{order_seq}",
                    {"type": "OPTION", "contract": c["ticker"]},
                    "SELL", 1,
                )
                if resp.get("ok"):
                    active_call_contract = c["ticker"]
                    contract_idx += 1
                    action_str = f"SELL {c['ticker'][-21:]} @${c['strike']:.2f}"
                    print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                          f"{action_str:^40} | ${equity:13,.2f}")
                    options_log.append({
                        "date": current_date, "action": "SELL_CALL",
                        "contract": c["ticker"], "strike": c["strike"],
                        "expiry": c["expiry"], "premium": c["close"],
                    })

    # 6. Final results
    print_section(f"Results: Covered Call vs Benchmarks — {underlying}")

    summary = get_summary(session_id)
    positions = get_positions(account_id)

    overlay_return = summary["total_return"]

    # Buy-and-hold benchmark
    final_price = current_price if current_price > 0 else initial_price
    stock_cost = benchmark_initial_price * STOCK_QTY
    benchmark_equity = (initial_cash - stock_cost) + final_price * STOCK_QTY
    benchmark_return = (benchmark_equity - initial_cash) / initial_cash

    # ETF benchmark
    etf_return = None
    etf_final_equity = None
    if etf_initial_price and etf_prices:
        # Find last available ETF price
        etf_final_price = None
        for d in sorted(etf_prices.keys(), reverse=True):
            if d <= END_DATE:
                etf_final_price = etf_prices[d]
                break
        if etf_final_price:
            etf_return = (etf_final_price - etf_initial_price) / etf_initial_price
            etf_final_equity = initial_cash * (1 + etf_return)

    # Print results
    header = f"  {'Metric':<25} {'Covered Call':>15} {'Buy-Hold':>15}"
    if etf_return is not None:
        header += f" {etf_ticker:>15}"
    print(f"\n{header}")
    print("  " + "-" * (55 + (16 if etf_return is not None else 0)))

    row_return = f"  {'Total Return':<25} {overlay_return*100:>14.2f}% {benchmark_return*100:>14.2f}%"
    if etf_return is not None:
        row_return += f" {etf_return*100:>14.2f}%"
    print(row_return)

    row_equity = f"  {'Final Equity':<25} ${summary['final_equity']:>13,.2f} ${benchmark_equity:>13,.2f}"
    if etf_final_equity is not None:
        row_equity += f" ${etf_final_equity:>13,.2f}"
    print(row_equity)

    print(f"  {'Max Drawdown':<25} {summary['max_drawdown']*100:>14.2f}%")
    print(f"  {'Overlay Alpha':<25} {(overlay_return - benchmark_return)*100:>14.2f}%")
    print(f"\n  Fees Paid: ${summary['fees_paid']:,.2f}")
    print(f"  Orders: {summary['num_orders']}")
    print(f"  Trades: {summary['num_trades']}")

    # Premium summary
    sell_actions = [o for o in options_log if o["action"] == "SELL_CALL"]
    total_premium = sum(o.get("premium", 0) for o in sell_actions)
    itm_count = sum(1 for o in options_log if o["action"] == "EXPIRY_ITM")
    otm_count = sum(1 for o in options_log if o["action"] == "EXPIRY_OTM")

    print(f"\n  Option Activity:")
    print(f"    Calls sold: {len(sell_actions)}")
    print(f"    Est. total premium: ${total_premium * 100:,.2f} (x100 multiplier)")
    print(f"    Expired OTM (profit): {otm_count}")
    print(f"    Expired ITM (call-away): {itm_count}")

    # Final positions
    print(f"\n  Final Positions:")
    for pos in positions:
        print(f"    {pos['instrument_id']:35s} {pos['qty']:>8,} @ ${pos['avg_price']:.2f}")

    # 7. Save results
    print_section("Saving Results")

    export_data = get_export(session_id)
    saver = ResultSaver(f"overlay_profit_increase_v2_{underlying.lower()}")

    saver.add_summary_line(f"Overlay Strategy v2: Covered Call (Profit Increase)")
    saver.add_summary_line(f"{'='*70}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Underlying: {underlying}")
    saver.add_summary_line(f"Period: {START_DATE} to {END_DATE}")
    saver.add_summary_line(f"Position: {STOCK_QTY:,} shares")
    saver.add_summary_line(f"Initial Capital: ${initial_cash:,.2f}")
    saver.add_summary_line(f"Rebalance: Weekly, DTE {DTE_MIN}-{DTE_MAX}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Performance:")
    saver.add_summary_line(f"  Covered Call Return: {overlay_return*100:+.2f}%")
    saver.add_summary_line(f"  Buy-and-Hold Return: {benchmark_return*100:+.2f}%")
    if etf_return is not None:
        saver.add_summary_line(f"  {etf_ticker} Return: {etf_return*100:+.2f}%")
    saver.add_summary_line(f"  Overlay Alpha: {(overlay_return - benchmark_return)*100:+.2f}%")
    saver.add_summary_line(f"  Max Drawdown: {summary['max_drawdown']*100:.2f}%")
    saver.add_summary_line(f"  Fees Paid: ${summary['fees_paid']:,.2f}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Option Activity:")
    saver.add_summary_line(f"  Calls sold: {len(sell_actions)}")
    saver.add_summary_line(f"  Est. premium collected: ${total_premium * 100:,.2f}")
    saver.add_summary_line(f"  Expired OTM: {otm_count}")
    saver.add_summary_line(f"  Expired ITM (call-away): {itm_count}")
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
        "etf_return": etf_return,
        "etf_ticker": etf_ticker,
        "premium_collected": total_premium * 100,
        "calls_sold": len(sell_actions),
        "itm_expiries": itm_count,
        "otm_expiries": otm_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Overlay v2: Covered Call (Paper Spec)")
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
        print_section("Cross-Ticker Summary: Covered Call v2")
        print(f"\n  {'Ticker':<8} {'CC Return':>12} {'Buy-Hold':>12} {'ETF':>12} {'Alpha':>10} {'Calls':>8} {'Premium':>12}")
        print("  " + "-" * 80)
        for r in results:
            etf_str = f"{r['etf_return']*100:>11.2f}%" if r['etf_return'] is not None else f"{'N/A':>12}"
            print(f"  {r['underlying']:<8} {r['overlay_return']*100:>11.2f}% "
                  f"{r['benchmark_return']*100:>11.2f}% {etf_str} "
                  f"{(r['overlay_return']-r['benchmark_return'])*100:>9.2f}% "
                  f"{r['calls_sold']:>8} ${r['premium_collected']:>10,.2f}")


if __name__ == "__main__":
    main()
