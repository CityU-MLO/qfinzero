"""
Demo 4 (Client): Limit Order Status Tracing

Pick a stock (MSFT) and a trading day, place 10 limit buy orders at 1% below
current price at random times throughout the day.  After each order, wait up
to 10 minutes checking whether the order fills.
If not filled within 10 minutes, cancel it.

This exercises: LIMIT order placement, order status polling, cancel workflow,
and the execution engine's limit-fill logic (fills when bar.low <= limit_price).

Prerequisites:
  - UPQ running with MSFT minute data
  - PMB running on http://127.0.0.1:19701

Usage:
  cd qfinzero
  python demos/pmb/client_demos/limit_order_trace.py
"""

import random
from datetime import datetime, timedelta
from qfinzero.clients.pmb import PMBClient

SYMBOL = "MSFT"
DATE = "2025-01-13"
NUM_ATTEMPTS = 10
WAIT_MINUTES = 10
INITIAL_CASH = 100_000.0


def parse_ts(ts: str) -> datetime:
    """Parse a timestamp like '2025-01-13T10:05:00' to datetime."""
    return datetime.fromisoformat(ts[:19])


def find_order(orders: list, order_id: str) -> dict | None:
    for o in orders:
        if o["order_id"] == order_id:
            return o
    return None


def generate_schedule(date: str, n: int, seed: int = 42) -> list[datetime]:
    """Generate n random order times spread across the trading day.

    The day is divided into n equal slots, and one random time is picked
    per slot.  The last slot ends WAIT_MINUTES before close so the final
    order has room to wait.
    """
    rng = random.Random(seed)
    market_open = datetime.fromisoformat(f"{date}T09:30:00")
    last_place = datetime.fromisoformat(f"{date}T15:45:00")  # leave 15 min buffer
    total_seconds = (last_place - market_open).total_seconds()
    slot_size = total_seconds / n

    times = []
    for i in range(n):
        slot_start = market_open + timedelta(seconds=slot_size * i)
        slot_end = market_open + timedelta(seconds=slot_size * (i + 1))
        rand_offset = rng.random() * (slot_end - slot_start).total_seconds()
        t = slot_start + timedelta(seconds=rand_offset)
        times.append(t)
    return times


def main():
    schedule = generate_schedule(DATE, NUM_ATTEMPTS)

    with PMBClient() as pmb:
        # 1. Create account
        acct = pmb.create_account(initial_cash=INITIAL_CASH, start_date=DATE)
        account_id = acct["account_id"]
        print(f"Account: {account_id}")
        print(f"Cash:    ${INITIAL_CASH:,.0f}")
        print(f"Stock:   {SYMBOL}")
        print(f"Date:    {DATE}")
        print(f"Strategy: Place limit buy at 1% below market, wait {WAIT_MINUTES} min, cancel if not filled")
        print(f"Schedule: {[t.strftime('%H:%M') for t in schedule]}\n")

        # 2. Create 1-minute session
        sess = pmb.create_session(
            account_id=account_id,
            frequency="1m",
            start_ts=f"{DATE}T09:30:00",
            end_ts=f"{DATE}T16:00:00",
            universe={"stocks": [SYMBOL]},
            execution_config={
                "slippage_bps": 1.0,
                "fee_model": {"stock_fee_per_share": 0.005},
            },
            reproducibility={"seed": 42, "run_id": "limit_order_trace"},
        )
        session_id = sess["session_id"]

        # 3. Simulation state
        attempt_idx = 0        # next attempt to place
        pending_order_id = None
        pending_limit = None
        place_time = None      # when the pending order was placed
        results = []           # (attempt#, place_time, limit_price, outcome, wait_mins, fill_price)

        header = f"{'#':>2} | {'Time':^5} | {'Market':>8} | {'Limit':>8} | {'Action':^10} | {'Status':^16} | {'Wait':>4}"
        print(header)
        print("-" * len(header))

        while True:
            result = pmb.step(session_id)
            if not result.is_running:
                break

            price = result.get_stock_price(SYMBOL)
            now = parse_ts(result.current_ts)
            time_str = result.current_ts[11:16]

            # -- If we have a pending order, check its status --
            if pending_order_id:
                elapsed = (now - place_time).total_seconds() / 60
                orders = pmb.get_orders(account_id, session_id=session_id)
                order = find_order(orders, pending_order_id)
                status = order["status"] if order else "UNKNOWN"

                if status == "FILLED":
                    fill_price = order.get("avg_fill_price", 0)
                    print(f"{attempt_idx:2d} | {time_str} | ${price:7.2f} | ${pending_limit:7.2f} | {'':^10} | FILLED @${fill_price:6.2f} | {elapsed:3.0f}m")
                    results.append((attempt_idx, time_str, pending_limit, "FILLED", elapsed, fill_price))
                    pending_order_id = None

                elif elapsed >= WAIT_MINUTES:
                    pmb.cancel_order(pending_order_id, session_id, account_id)
                    print(f"{attempt_idx:2d} | {time_str} | ${price:7.2f} | ${pending_limit:7.2f} | {'CANCEL':^10} | TIMEOUT {WAIT_MINUTES}m     | {elapsed:3.0f}m")
                    results.append((attempt_idx, time_str, pending_limit, "CANCELLED", elapsed, None))
                    pending_order_id = None

                if pending_order_id:
                    continue  # still waiting

            # -- Check if it's time to place the next order --
            if attempt_idx < NUM_ATTEMPTS and now >= schedule[attempt_idx]:
                attempt_idx += 1
                if price is None:
                    results.append((attempt_idx, time_str, 0, "NO_PRICE", 0, None))
                    continue

                limit_price = round(price * 0.99, 2)  # 1% below market
                resp = pmb.buy(
                    session_id, account_id, SYMBOL, 10,
                    order_type="LIMIT",
                    limit_price=limit_price,
                    time_in_force="GTC",
                    client_order_id=f"limit_{attempt_idx}",
                )

                if resp.get("ok"):
                    pending_order_id = resp["order_id"]
                    pending_limit = limit_price
                    place_time = now
                    print(f"{attempt_idx:2d} | {time_str} | ${price:7.2f} | ${limit_price:7.2f} | {'PLACE':^10} | {resp['status']:^16} | {'':>4}")
                else:
                    print(f"{attempt_idx:2d} | {time_str} | ${price:7.2f} | ${limit_price:7.2f} | {'REJECTED':^10} | {resp.get('error','?'):^16} |")
                    results.append((attempt_idx, time_str, limit_price, "REJECTED", 0, None))

        # Cancel any leftover pending order
        if pending_order_id:
            pmb.cancel_order(pending_order_id, session_id, account_id)
            results.append((attempt_idx, "close", pending_limit, "CANCELLED", WAIT_MINUTES, None))
            print(f"{attempt_idx:2d} | close | {'':>8} | ${pending_limit:7.2f} | {'CANCEL':^10} | SESSION END      |")

        # 4. Summary
        filled = [r for r in results if r[3] == "FILLED"]
        cancelled = [r for r in results if r[3] == "CANCELLED"]

        print(f"\n{'='*64}")
        print(f"  LIMIT ORDER TRACE SUMMARY — {SYMBOL} on {DATE}")
        print(f"{'='*64}")
        print(f"  Total attempts:  {len(results)}")
        print(f"  Filled:          {len(filled)}")
        print(f"  Cancelled:       {len(cancelled)}")
        if filled:
            avg_wait = sum(r[4] for r in filled) / len(filled)
            avg_fill = sum(r[5] for r in filled) / len(filled)
            print(f"  Avg fill wait:   {avg_wait:.1f} minutes")
            print(f"  Avg fill price:  ${avg_fill:.2f}")

        # Account summary
        summary = pmb.get_summary(session_id)
        positions = pmb.get_positions(account_id)

        print(f"\n  Final equity:    ${summary['final_equity']:,.2f}")
        print(f"  Total return:    {summary['total_return']*100:+.2f}%")
        print(f"  Fees paid:       ${summary['fees_paid']:.2f}")
        print(f"  Orders placed:   {summary['num_orders']}")
        print(f"  Trades executed: {summary['num_trades']}")

        if positions:
            print(f"\n  Positions:")
            for pos in positions:
                print(f"    {pos['instrument_id']} {pos['qty']} shares "
                      f"@ ${pos['avg_price']:.2f}, P&L ${pos['unrealized_pnl']:+.2f}")

        print()


if __name__ == "__main__":
    main()
