"""
Overlay Strategy Demo v2: Hedging (Put Spread) — Paper Spec

Paper parameters:
  - Underlyings: QQQ, NVDA
  - Position: 10,000 shares + 20% cash buffer
  - Rebalance: Weekly (every Monday)
  - DTE: 7-60 days
  - Strategy: Put spread (buy near-ATM put + sell further-OTM put)
  - Period: 2025-01-02 to 2025-12-31

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
from collections import defaultdict
from demos.overlay_helpers import (
    discover_contracts_weekly, create_account, create_session,
    place_order, place_spread, step_session, get_summary, get_export,
    get_positions, get_account, print_section, query_stock_price,
    compute_initial_cash, query_option_greeks, compute_effective_delta,
    query_option_chain,
)
from demos.result_saver import ResultSaver


# --- Paper Spec Config ---
PAPER_TICKERS = ["QQQ", "NVDA"]
START_DATE = "2025-01-02"
END_DATE = "2025-12-31"
STOCK_QTY = 10_000
CASH_BUFFER_PCT = 0.20
DTE_MIN = 7
DTE_MAX = 60
OPTION_QTY = STOCK_QTY // 100  # 100 contracts = 10,000 shares
NEAR_OTM_PCT = 0.03   # Long leg: 3% OTM
FAR_OTM_PCT = 0.08    # Short leg: 8% OTM


def pair_spread_contracts(contracts: list[dict], ref_price: float) -> list[dict]:
    """Pair contracts into spreads by expiry.

    For each expiry, find:
      - near leg: strike closest to ref_price × (1 - NEAR_OTM_PCT)
      - far leg: strike closest to ref_price × (1 - FAR_OTM_PCT)

    Returns list of {"expiry": ..., "near": {...}, "far": {...}} dicts.
    Only includes pairs where both legs exist and near.strike > far.strike.
    """
    by_expiry = defaultdict(list)
    for c in contracts:
        by_expiry[c["expiry"]].append(c)

    near_target = ref_price * (1 - NEAR_OTM_PCT)
    far_target = ref_price * (1 - FAR_OTM_PCT)

    pairs = []
    for expiry in sorted(by_expiry.keys()):
        cs = by_expiry[expiry]
        if len(cs) < 2:
            continue
        near = min(cs, key=lambda c: abs(c["strike"] - near_target))
        far = min(cs, key=lambda c: abs(c["strike"] - far_target))
        if near["ticker"] != far["ticker"] and near["strike"] > far["strike"]:
            pairs.append({"expiry": expiry, "near": near, "far": far})
    return pairs


def run_single_ticker(underlying: str):
    """Run put spread hedging strategy for a single underlying."""

    print_section(f"Overlay v2: Put Spread Hedge — {underlying}")
    print(f"  Period: {START_DATE} to {END_DATE}")
    print(f"  Stock Position: {STOCK_QTY:,} shares")
    print(f"  Cash Buffer: {CASH_BUFFER_PCT*100:.0f}%")
    print(f"  DTE Window: {DTE_MIN}-{DTE_MAX} days")
    print(f"  Spread: Buy {NEAR_OTM_PCT*100:.0f}% OTM put + Sell {FAR_OTM_PCT*100:.0f}% OTM put")
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

    # 2. Pre-discover put contracts with wide strike range (covers 3%-8% OTM)
    # We discover at 5% OTM center, which should give us a range of strikes
    contracts = discover_contracts_weekly(
        underlying=underlying,
        start_date=START_DATE,
        end_date=END_DATE,
        option_type="P",
        otm_pct=0.05,
        ref_price=ref_price,
        dte_min=DTE_MIN,
        dte_max=DTE_MAX,
    )

    # Also discover at 3% and 8% to ensure we have wider coverage
    for pct in [NEAR_OTM_PCT, FAR_OTM_PCT]:
        extra = discover_contracts_weekly(
            underlying=underlying,
            start_date=START_DATE,
            end_date=END_DATE,
            option_type="P",
            otm_pct=pct,
            ref_price=ref_price,
            dte_min=DTE_MIN,
            dte_max=DTE_MAX,
        )
        if extra:
            existing_tickers = {c["ticker"] for c in contracts}
            for c in extra:
                if c["ticker"] not in existing_tickers:
                    contracts.append(c)

    if not contracts:
        print(f"  ERROR: No option contracts found for {underlying}.")
        return

    print(f"\n  Discovered {len(contracts)} put contracts for the year")

    # Pair contracts into spreads by expiry
    spread_pairs = pair_spread_contracts(contracts, ref_price)
    print(f"  Paired into {len(spread_pairs)} spread pairs")

    if not spread_pairs:
        print(f"  ERROR: Could not pair any spreads for {underlying}.")
        return

    for sp in spread_pairs[:3]:
        print(f"    {sp['expiry']}: BUY ${sp['near']['strike']:.2f} / SELL ${sp['far']['strike']:.2f}")
    if len(spread_pairs) > 3:
        print(f"    ... and {len(spread_pairs) - 3} more")

    # Collect all unique contracts for the universe
    all_tickers = set()
    for sp in spread_pairs:
        all_tickers.add(sp["near"]["ticker"])
        all_tickers.add(sp["far"]["ticker"])
    option_tickers = list(all_tickers)

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
        run_id=f"overlay_pp_v2_{underlying.lower()}_2025",
    )
    session_id = sess["session_id"]
    print(f"  Session: {session_id}")

    # 4. Trading loop
    print_section(f"Phase 3: Running Put Spread Hedge — {underlying}")

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
    active_spread = None  # {"near_contract": ..., "far_contract": ...}
    spread_idx = 0
    options_log = []
    day_count = 2
    benchmark_initial_price = initial_price
    order_seq = 0

    print(f"\n  {'Day':>4} | {'Date':^10} | {underlying:>8} | {'Action':^50} | {'Equity':>14}")
    print("  " + "-" * 105)

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
                    action_str = f"SPREAD EXPIRY ITM: {contract[-21:]}"
                    options_log.append({
                        "date": current_date, "action": "EXPIRY_ITM",
                        "contract": contract, "outcome": "closed at intrinsic",
                    })
                else:
                    action_str = f"SPREAD EXPIRY OTM: {contract[-21:]}"
                    options_log.append({
                        "date": current_date, "action": "EXPIRY_OTM",
                        "contract": contract, "outcome": "expired worthless",
                    })

                print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                      f"{action_str:^50} | ${equity:13,.2f}")

                # Clear active spread if one of its legs expired
                if active_spread and (
                    contract == active_spread["near_contract"]
                    or contract == active_spread["far_contract"]
                ):
                    active_spread = None

        # Open new put spread if no active position
        if active_spread is None and spread_idx < len(spread_pairs):
            while spread_idx < len(spread_pairs):
                sp = spread_pairs[spread_idx]
                if sp["expiry"] >= current_date:
                    break
                spread_idx += 1

            if spread_idx < len(spread_pairs):
                sp = spread_pairs[spread_idx]

                # Delta constraint check
                greeks_near = query_option_greeks(sp["near"]["ticker"], current_date)
                greeks_far = query_option_greeks(sp["far"]["ticker"], current_date)
                skip = False

                if greeks_near and greeks_near.get("delta") and greeks_far and greeks_far.get("delta"):
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
                    # Long near put (qty=+OPTION_QTY) + short far put (qty=-OPTION_QTY)
                    proposed = option_pos_list + [
                        {"delta": greeks_near["delta"], "qty": OPTION_QTY},
                        {"delta": greeks_far["delta"], "qty": -OPTION_QTY},
                    ]
                    new_delta = compute_effective_delta(STOCK_QTY, proposed)
                    if abs(new_delta) > STOCK_QTY:
                        print(f"  DELTA CONSTRAINT: skip spread, "
                              f"effective delta would be {new_delta:.0f} > {STOCK_QTY:,}")
                        spread_idx += 1
                        skip = True

                if not skip:
                    order_seq += 1
                    responses = place_spread(
                        session_id, account_id, f"put_spread_{order_seq}",
                        legs=[
                            {"instrument": {"type": "OPTION", "contract": sp["near"]["ticker"]},
                             "side": "BUY", "qty": OPTION_QTY},
                            {"instrument": {"type": "OPTION", "contract": sp["far"]["ticker"]},
                             "side": "SELL", "qty": OPTION_QTY},
                        ],
                    )

                    if all(r.get("ok") for r in responses):
                        active_spread = {
                            "near_contract": sp["near"]["ticker"],
                            "far_contract": sp["far"]["ticker"],
                        }
                        spread_idx += 1
                        near_s = sp["near"]["strike"]
                        far_s = sp["far"]["strike"]
                        action_str = f"BUY SPREAD ${near_s:.0f}/${far_s:.0f} exp={sp['expiry']}"
                        print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                              f"{action_str:^50} | ${equity:13,.2f}")
                        options_log.append({
                            "date": current_date, "action": "BUY_SPREAD",
                            "near_contract": sp["near"]["ticker"],
                            "far_contract": sp["far"]["ticker"],
                            "near_strike": near_s, "far_strike": far_s,
                            "expiry": sp["expiry"],
                            "near_premium": sp["near"].get("close", 0),
                            "far_premium": sp["far"].get("close", 0),
                        })

    # 5. Final results
    print_section(f"Results: Put Spread Hedge vs Buy-and-Hold — {underlying}")

    summary = get_summary(session_id)
    positions = get_positions(account_id)

    overlay_return = summary["total_return"]

    # Buy-and-hold benchmark
    final_price = current_price if current_price > 0 else initial_price
    stock_cost = benchmark_initial_price * STOCK_QTY
    benchmark_equity = (initial_cash - stock_cost) + final_price * STOCK_QTY
    benchmark_return = (benchmark_equity - initial_cash) / initial_cash

    print(f"\n  {'Metric':<25} {'Put Spread':>15} {'Buy-Hold':>15}")
    print("  " + "-" * 55)
    print(f"  {'Total Return':<25} {overlay_return*100:>14.2f}% {benchmark_return*100:>14.2f}%")
    print(f"  {'Final Equity':<25} ${summary['final_equity']:>13,.2f} ${benchmark_equity:>13,.2f}")
    print(f"  {'Max Drawdown':<25} {summary['max_drawdown']*100:>14.2f}%")
    print(f"  {'Hedge Cost (alpha)':<25} {(overlay_return - benchmark_return)*100:>14.2f}%")
    print(f"\n  Fees Paid: ${summary['fees_paid']:,.2f}")
    print(f"  Orders: {summary['num_orders']}")
    print(f"  Trades: {summary['num_trades']}")

    # Premium summary
    spread_actions = [o for o in options_log if o["action"] == "BUY_SPREAD"]
    net_premium = sum(
        (o.get("near_premium", 0) - o.get("far_premium", 0))
        for o in spread_actions
    )
    itm_count = sum(1 for o in options_log if o["action"] == "EXPIRY_ITM")
    otm_count = sum(1 for o in options_log if o["action"] == "EXPIRY_OTM")

    print(f"\n  Option Activity:")
    print(f"    Spreads bought: {len(spread_actions)}")
    print(f"    Est. net premium paid: ${net_premium * OPTION_QTY * 100:,.2f} (x{OPTION_QTY}x100)")
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

    saver.add_summary_line(f"Overlay Strategy v2: Put Spread Hedge")
    saver.add_summary_line(f"{'='*70}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Underlying: {underlying}")
    saver.add_summary_line(f"Period: {START_DATE} to {END_DATE}")
    saver.add_summary_line(f"Position: {STOCK_QTY:,} shares")
    saver.add_summary_line(f"Initial Capital: ${initial_cash:,.2f}")
    saver.add_summary_line(f"Spread: Buy {NEAR_OTM_PCT*100:.0f}% / Sell {FAR_OTM_PCT*100:.0f}% OTM")
    saver.add_summary_line(f"Rebalance: Weekly, DTE {DTE_MIN}-{DTE_MAX}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Performance:")
    saver.add_summary_line(f"  Put Spread Return: {overlay_return*100:+.2f}%")
    saver.add_summary_line(f"  Buy-and-Hold Return: {benchmark_return*100:+.2f}%")
    saver.add_summary_line(f"  Hedge Cost: {(overlay_return - benchmark_return)*100:+.2f}%")
    saver.add_summary_line(f"  Max Drawdown: {summary['max_drawdown']*100:.2f}%")
    saver.add_summary_line(f"  Fees Paid: ${summary['fees_paid']:,.2f}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Option Activity:")
    saver.add_summary_line(f"  Spreads: {len(spread_actions)}")
    saver.add_summary_line(f"  Est. net premium: ${net_premium * OPTION_QTY * 100:,.2f}")
    saver.add_summary_line(f"  Expired OTM: {otm_count}")
    saver.add_summary_line(f"  Expired ITM: {itm_count}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Spread Log:")
    for o in options_log:
        if o["action"] == "BUY_SPREAD":
            saver.add_summary_line(
                f"  {o['date']}: BUY ${o['near_strike']:.0f}/${o['far_strike']:.0f} "
                f"exp={o['expiry']}")
        else:
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
        "net_premium_paid": net_premium * OPTION_QTY * 100,
        "spreads_bought": len(spread_actions),
        "itm_expiries": itm_count,
        "otm_expiries": otm_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Overlay v2: Put Spread Hedge (Paper Spec)")
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
        print_section("Cross-Ticker Summary: Put Spread Hedge v2")
        print(f"\n  {'Ticker':<8} {'Spread Return':>14} {'Buy-Hold':>12} {'Alpha':>10} {'Spreads':>8} {'Net Prem':>12}")
        print("  " + "-" * 70)
        for r in results:
            print(f"  {r['underlying']:<8} {r['overlay_return']*100:>13.2f}% "
                  f"{r['benchmark_return']*100:>11.2f}% "
                  f"{(r['overlay_return']-r['benchmark_return'])*100:>9.2f}% "
                  f"{r['spreads_bought']:>8} ${r['net_premium_paid']:>10,.2f}")


if __name__ == "__main__":
    main()
