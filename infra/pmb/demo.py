"""
Demo: AAPL single-day minute replay with stock trades.

Prerequisites:
  - UPQ running on http://127.0.0.1:23333 with AAPL minute data for 2025-01-06
  - PMB running on http://127.0.0.1:24444 (python main.py)

Usage:
  python demo.py
"""

import requests
import json

BASE = "http://127.0.0.1:24444"


def pp(label: str, resp):
    """Pretty print a response."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    if resp.status_code != 200:
        print(f"  ERROR {resp.status_code}: {resp.text}")
        return resp.json() if resp.text else {}
    data = resp.json()
    print(json.dumps(data, indent=2))
    return data


def main():
    # 1. Health check
    pp("Health Check", requests.get(f"{BASE}/v1/health"))

    # 2. Create account with $100k
    acct = pp(
        "Create Account",
        requests.post(
            f"{BASE}/v1/accounts",
            json={
                "account_type": "MARGIN",
                "initial_cash": 100000.0,
                "start_date": "2025-01-06",
            },
        ),
    )
    account_id = acct["account_id"]

    # 3. Create session: AAPL minute replay for 2025-01-06
    sess = pp(
        "Create Session (AAPL 1m replay)",
        requests.post(
            f"{BASE}/v1/sessions",
            json={
                "account_id": account_id,
                "frequency": "1m",
                "start_ts": "2025-01-06T09:30:00",
                "end_ts": "2025-01-06T16:00:00",
                "universe": {"stocks": ["AAPL"]},
                "execution_config": {
                    "slippage_bps": 1.0,
                    "fee_model": {
                        "stock_fee_per_share": 0.005,
                        "option_fee_per_contract": 0.65,
                    },
                },
                "reproducibility": {"seed": 42, "run_id": "demo_001"},
            },
        ),
    )
    session_id = sess["session_id"]

    # 4. Step 1 tick to get first market data
    step1 = pp("Step 1 (get first bar)", requests.post(f"{BASE}/v1/sessions/{session_id}/step", json={"step": 1}))

    # 5. Place a market buy order for 50 shares of AAPL
    order1 = pp(
        "Place Market Buy: 50 AAPL",
        requests.post(
            f"{BASE}/v1/orders",
            json={
                "session_id": session_id,
                "account_id": account_id,
                "client_order_id": "demo_buy_001",
                "order": {
                    "instrument": {"type": "STOCK", "symbol": "AAPL"},
                    "side": "BUY",
                    "order_type": "MARKET",
                    "qty": 50,
                    "time_in_force": "DAY",
                },
            },
        ),
    )

    # 6. Step again — the order should fill
    step2 = pp("Step 2 (order fills)", requests.post(f"{BASE}/v1/sessions/{session_id}/step", json={"step": 1}))

    # Print events summary
    if "events" in step2:
        for evt in step2["events"]:
            evt_type = evt.get("type", "?")
            if evt_type == "ORDER_EVENT":
                payload = evt["payload"]
                print(f"  >> ORDER filled: order_id={payload.get('order_id')}, status={payload.get('status')}, avg_price={payload.get('avg_fill_price')}")
            elif evt_type == "TRADE_EVENT":
                payload = evt["payload"]
                print(f"  >> TRADE: {payload.get('side')} {payload.get('qty')} @ {payload.get('price')}, fees={payload.get('fees')}")

    # 7. Check positions
    pp("Positions", requests.get(f"{BASE}/v1/accounts/{account_id}/positions"))

    # 8. Step 5 more ticks
    pp("Step 5 more ticks", requests.post(f"{BASE}/v1/sessions/{session_id}/step", json={"step": 5}))

    # 9. Place a limit sell order
    pp(
        "Place Limit Sell: 50 AAPL @ high price",
        requests.post(
            f"{BASE}/v1/orders",
            json={
                "session_id": session_id,
                "account_id": account_id,
                "client_order_id": "demo_sell_001",
                "order": {
                    "instrument": {"type": "STOCK", "symbol": "AAPL"},
                    "side": "SELL",
                    "order_type": "MARKET",
                    "qty": 50,
                    "time_in_force": "DAY",
                },
            },
        ),
    )

    # 10. Step to execute sell
    step_sell = pp("Step (sell fills)", requests.post(f"{BASE}/v1/sessions/{session_id}/step", json={"step": 1}))
    if "events" in step_sell:
        for evt in step_sell["events"]:
            if evt.get("type") == "TRADE_EVENT":
                payload = evt["payload"]
                print(f"  >> TRADE: {payload.get('side')} {payload.get('qty')} @ {payload.get('price')}")

    # 11. Check account state
    pp("Account State", requests.get(f"{BASE}/v1/accounts/{account_id}"))

    # 12. Fast forward remaining session
    print("\n... stepping through rest of session ...")
    done = False
    step_count = 0
    while not done:
        r = requests.post(f"{BASE}/v1/sessions/{session_id}/step", json={"step": 10})
        data = r.json()
        clock = data.get("clock", {})
        done = clock.get("status") != "RUNNING"
        step_count += 10
        if step_count % 100 == 0:
            print(f"  stepped {step_count} bars, ts={clock.get('current_ts')}")

    # 13. Session summary
    pp("Session Summary", requests.get(f"{BASE}/v1/sessions/{session_id}/summary"))

    # 14. Export trades
    export = requests.get(f"{BASE}/v1/sessions/{session_id}/export?format=json").json()
    print(f"\n  Export: {len(export.get('orders', []))} orders, {len(export.get('trades', []))} trades, {len(export.get('equity_curve', []))} equity points")


if __name__ == "__main__":
    main()
