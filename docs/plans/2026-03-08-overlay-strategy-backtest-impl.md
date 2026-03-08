# Overlay Strategy Backtest Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Two demo scripts (`overlay_profit_increase.py`, `overlay_hedging.py`) that backtest covered call and protective put overlay strategies on AAPL daily data for 2024.

**Architecture:** Each script pre-discovers all needed option contracts for the year via UPQ `chain_query`, creates a single PMB session with all contracts in the universe, then steps through each trading day executing the overlay logic. Results are saved via the existing `ResultSaver` plus an overlay-specific options log.

**Tech Stack:** Python, requests (sync HTTP to PMB + UPQ), existing PMB server + UPQ service.

---

## Key Design Decisions

### Pre-Discovery vs Monthly Sessions

PMB prefetches all bar data at session creation (`session_service.py:71-106`). We cannot add instruments mid-session. Two approaches were considered:

- **Monthly sessions:** Create 12 sessions, carry forward state. Complex, fragile.
- **Pre-discovery:** Before creating the session, query UPQ `chain_query` for each month's target contract. Collect all ~12 OPRA tickers upfront, pass them all in `universe.options`. One session covers the full year.

We use **pre-discovery**. This means:

1. Step through trading days conceptually (compute target dates for ~12 monthly options)
2. For each month, call `chain_query` to find the best contract
3. Build the full `universe.options` list
4. Create one session, step through the year

### Roll Mechanism: Natural Expiry (Plan A)

Options are NOT rolled before expiry. They expire naturally via PMB's `option_lifecycle.py`:

- **Covered Call OTM expiry:** Option worthless, premium captured. Script opens new call next trading day.
- **Covered Call ITM expiry (call-away):** PMB assignment sells 100 shares at strike. Script detects missing stock position, re-buys 100 shares, then opens new call.
- **Protective Put OTM expiry:** Option worthless, premium lost. Script buys new put next trading day.
- **Protective Put ITM expiry:** Option closed at intrinsic value. Script buys new put next trading day.

### Contract Selection

For each month, query `chain_query` with:
- **Covered Call:** `type=C`, strike range `[price*1.03, price*1.10]`, select closest to `price*1.05`
- **Protective Put:** `type=P`, strike range `[price*0.90, price*0.97]`, select closest to `price*0.95`
- **Expiry target:** 25-35 calendar days from the start of that month

---

## Task 1: Shared Helper Module `overlay_helpers.py`

**Files:**
- Create: `infra/pmb/demos/overlay_helpers.py`

Shared utilities used by both overlay scripts: option chain query, contract selection, benchmark calculation.

**Step 1: Write the helper module**

```python
"""
Shared helpers for overlay strategy demos.
"""

import requests
from datetime import datetime, timedelta

PMB_BASE = "http://127.0.0.1:19320"
UPQ_CHAIN = "http://127.0.0.1:19350"


def query_option_chain(underlying: str, date: str, option_type: str,
                       strike_min: float, strike_max: float,
                       expiry_min: str = None, expiry_max: str = None) -> list[dict]:
    """Query UPQ chain_query for matching option contracts."""
    params = {
        "underlying": underlying,
        "date": date,
        "type": option_type,
        "strike_min": strike_min,
        "strike_max": strike_max,
    }
    if expiry_min:
        params["expiry_min"] = expiry_min
    if expiry_max:
        params["expiry_max"] = expiry_max

    try:
        resp = requests.get(f"{UPQ_CHAIN}/option/chain_query", params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        print(f"  [WARN] chain_query returned {resp.status_code}")
        return []
    except Exception as e:
        print(f"  [WARN] chain_query failed: {e}")
        return []


def select_contract(chain: list[dict], target_strike: float) -> dict | None:
    """Select the contract with strike closest to target_strike.
    Only considers contracts with close > 0 (has trading activity)."""
    candidates = [c for c in chain if c.get("close", 0) > 0]
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs(c["strike"] - target_strike))


def get_monthly_option_dates(start_date: str, end_date: str) -> list[tuple[str, str, str]]:
    """Generate (query_date, expiry_min, expiry_max) tuples for each month.

    query_date: first trading day of the month (approx)
    expiry_min/max: target expiry window ~25-35 days from query_date
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    result = []

    current = start
    while current < end:
        query_date = current.strftime("%Y-%m-%d")
        expiry_min = (current + timedelta(days=25)).strftime("%Y-%m-%d")
        expiry_max = (current + timedelta(days=35)).strftime("%Y-%m-%d")
        result.append((query_date, expiry_min, expiry_max))
        # Move to approx first of next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1, day=2)
        else:
            current = current.replace(month=current.month + 1, day=2)

    return result


def discover_contracts(underlying: str, start_date: str, end_date: str,
                       option_type: str, otm_pct: float,
                       ref_price: float) -> list[dict]:
    """Pre-discover all option contracts needed for the backtest period.

    Args:
        underlying: Stock symbol
        start_date/end_date: Backtest period
        option_type: "C" or "P"
        otm_pct: OTM percentage for strike target (e.g. 0.05 for 5%)
        ref_price: Reference stock price for strike estimation

    Returns:
        List of selected contracts with {ticker, strike, expiry, close, query_date}
    """
    months = get_monthly_option_dates(start_date, end_date)
    contracts = []

    for query_date, expiry_min, expiry_max in months:
        if option_type == "C":
            strike_min = ref_price * (1 + otm_pct * 0.5)
            strike_max = ref_price * (1 + otm_pct * 2.0)
            target_strike = ref_price * (1 + otm_pct)
        else:  # P
            strike_min = ref_price * (1 - otm_pct * 2.0)
            strike_max = ref_price * (1 - otm_pct * 0.5)
            target_strike = ref_price * (1 - otm_pct)

        chain = query_option_chain(
            underlying=underlying,
            date=query_date,
            option_type=option_type,
            strike_min=strike_min,
            strike_max=strike_max,
            expiry_min=expiry_min,
            expiry_max=expiry_max,
        )

        selected = select_contract(chain, target_strike)
        if selected:
            contracts.append({
                "ticker": selected["ticker"],
                "strike": selected["strike"],
                "expiry": selected["expiry"],
                "close": selected["close"],
                "query_date": query_date,
            })
            print(f"  [DISCOVERY] {query_date}: {selected['ticker']} "
                  f"strike=${selected['strike']:.2f} expiry={selected['expiry']} "
                  f"premium=${selected['close']:.2f}")
        else:
            print(f"  [DISCOVERY] {query_date}: no suitable {option_type} contract found")

    return contracts


def create_account(initial_cash: float = 100_000.0,
                   start_date: str = "2024-01-02") -> dict:
    """Create a PMB margin account."""
    resp = requests.post(f"{PMB_BASE}/v1/accounts", json={
        "account_type": "MARGIN",
        "initial_cash": initial_cash,
        "start_date": start_date,
        "margin_config": {
            "stock_initial": 0.50,
            "stock_maintenance": 0.25,
            "option_short_a": 0.20,
            "option_short_b": 0.10,
        },
    })
    return resp.json()


def create_session(account_id: str, start_ts: str, end_ts: str,
                   stocks: list[str], options: list[str],
                   seed: int = 400, run_id: str = "overlay") -> dict:
    """Create a PMB session with prefetched data."""
    resp = requests.post(f"{PMB_BASE}/v1/sessions", json={
        "account_id": account_id,
        "frequency": "1d",
        "start_ts": start_ts,
        "end_ts": end_ts,
        "universe": {"stocks": stocks, "options": options},
        "execution_config": {
            "slippage_bps": 2.0,
            "fee_model": {
                "stock_fee_per_share": 0.005,
                "option_fee_per_contract": 0.65,
            },
        },
        "reproducibility": {"seed": seed, "run_id": run_id},
    })
    return resp.json()


def place_order(session_id: str, account_id: str, client_order_id: str,
                instrument: dict, side: str, qty: int,
                order_type: str = "MARKET", tif: str = "GTC") -> dict:
    """Place an order via PMB."""
    resp = requests.post(f"{PMB_BASE}/v1/orders", json={
        "session_id": session_id,
        "account_id": account_id,
        "client_order_id": client_order_id,
        "order": {
            "instrument": instrument,
            "side": side,
            "order_type": order_type,
            "qty": qty,
            "time_in_force": tif,
        },
    })
    return resp.json()


def step_session(session_id: str, n: int = 1) -> dict:
    """Step the session forward by n ticks."""
    resp = requests.post(f"{PMB_BASE}/v1/sessions/{session_id}/step",
                         json={"step": n})
    return resp.json()


def get_summary(session_id: str) -> dict:
    resp = requests.get(f"{PMB_BASE}/v1/sessions/{session_id}/summary")
    return resp.json()


def get_export(session_id: str) -> dict:
    resp = requests.get(f"{PMB_BASE}/v1/sessions/{session_id}/export?format=json")
    return resp.json()


def get_positions(account_id: str) -> list[dict]:
    resp = requests.get(f"{PMB_BASE}/v1/accounts/{account_id}/positions")
    return resp.json().get("positions", [])


def get_account(account_id: str) -> dict:
    resp = requests.get(f"{PMB_BASE}/v1/accounts/{account_id}")
    return resp.json()


def print_section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def compute_benchmark(equity_curve: list[dict], initial_cash: float) -> dict:
    """Compute buy-and-hold benchmark metrics from overlay equity curve.

    The benchmark is derived from the first stock purchase price and
    the stock's price trajectory embedded in the equity snapshots.
    Returns total_return and max_drawdown for comparison.
    """
    if not equity_curve:
        return {"total_return": 0.0, "max_drawdown": 0.0}

    # Simple approximation: benchmark = initial_cash * (1 + stock_return)
    # We can't perfectly reconstruct buy-and-hold from overlay equity,
    # so the demo scripts track it separately during the step loop.
    return {}
```

**Step 2: Verify the module imports cleanly**

Run: `cd /Users/efan404/Codes/research/qfinzero/infra/pmb && python -c "import demos.overlay_helpers; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add infra/pmb/demos/overlay_helpers.py
git commit -m "feat(pmb): add shared overlay strategy helpers"
```

---

## Task 2: Covered Call Demo `overlay_profit_increase.py`

**Files:**
- Create: `infra/pmb/demos/overlay_profit_increase.py`
- Reference: `infra/pmb/demos/covered_call.py` (existing pattern)
- Reference: `infra/pmb/demos/overlay_helpers.py` (from Task 1)

**Step 1: Write the demo script**

The script follows this flow:
1. Query AAPL stock price from UPQ to get reference price for strike calculation
2. Pre-discover 12 monthly call contracts via `chain_query`
3. Create PMB account + session with all contracts in universe
4. Step through each trading day:
   - If no active short call: sell the contract assigned to this month
   - If `OPTION_EXPIRY_EVENT` received: log outcome, re-buy stock if called away
   - Track equity curve + benchmark (buy-and-hold without options)
5. Save results

```python
"""
Overlay Strategy Demo: Profit Increase (Covered Call)

Strategy:
  - Buy 100 shares AAPL on day 1
  - Each month: sell 1 OTM call (~5% above current price, ~30 days to expiry)
  - Let options expire naturally (Plan A: no early roll)
  - If call-away (ITM assignment): re-buy 100 shares, open new call
  - Run for full year 2024

Prerequisites:
  - UPQ running on http://127.0.0.1:23333 with AAPL 2024 daily data
  - UPQ option chain on http://127.0.0.1:19350 with AAPL 2024 option data
  - PMB running on http://127.0.0.1:19320

Usage:
  python demos/overlay_profit_increase.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from demos.overlay_helpers import (
    PMB_BASE, UPQ_CHAIN,
    discover_contracts, create_account, create_session,
    place_order, step_session, get_summary, get_export,
    get_positions, get_account, print_section,
    query_option_chain, select_contract,
)
from demos.result_saver import ResultSaver


# --- Config ---
UNDERLYING = "AAPL"
START_DATE = "2024-01-02"
END_DATE = "2024-12-31"
INITIAL_CASH = 100_000.0
STOCK_QTY = 100
OTM_PCT = 0.05  # 5% OTM for call strike


def get_reference_price(underlying: str, date: str) -> float:
    """Get approximate stock price from UPQ for strike estimation."""
    try:
        resp = requests.get(f"http://127.0.0.1:23333/stock/daily", params={
            "tickers": underlying, "start": date, "end": date,
            "fields": "ticker,date,close",
        }, timeout=10)
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return rows[0]["close"]
    except Exception:
        pass
    # Fallback: approximate AAPL price early 2024
    return 185.0


def main():
    print_section("Overlay Strategy: Covered Call (Profit Increase)")
    print(f"  Underlying: {UNDERLYING}")
    print(f"  Period: {START_DATE} to {END_DATE}")
    print(f"  Initial Capital: ${INITIAL_CASH:,.2f}")
    print(f"  Stock Position: {STOCK_QTY} shares")
    print(f"  Call Strike Target: {OTM_PCT*100:.0f}% OTM")

    # 1. Get reference price for contract discovery
    print_section("Phase 1: Contract Discovery")
    ref_price = get_reference_price(UNDERLYING, START_DATE)
    print(f"  Reference price: ${ref_price:.2f}")

    # 2. Pre-discover all monthly call contracts
    contracts = discover_contracts(
        underlying=UNDERLYING,
        start_date=START_DATE,
        end_date=END_DATE,
        option_type="C",
        otm_pct=OTM_PCT,
        ref_price=ref_price,
    )

    if not contracts:
        print("  ERROR: No option contracts found. Check UPQ data availability.")
        return

    print(f"\n  Discovered {len(contracts)} contracts for the year")

    # Build contract-to-month mapping (by expiry date)
    # Each contract covers the period from its query_date until its expiry
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
        seed=401,
        run_id="overlay_covered_call_2024",
    )
    session_id = sess["session_id"]
    print(f"  Session: {session_id}")

    # 4. Trading loop
    print_section("Phase 3: Running Covered Call Strategy")

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

    # Step to execute the buy
    step_session(session_id)

    # Track state
    active_call_contract = None
    contract_idx = 0  # Index into pre-discovered contracts
    options_log = []  # Track all option activity
    day_count = 2
    benchmark_equity = INITIAL_CASH  # Track buy-and-hold separately
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
        stock_pos = 0
        if account_snap:
            snap = account_snap["payload"]
            equity = snap["equity"]
            for pos in snap.get("positions", []):
                if pos.get("instrument_id", "").startswith("STOCK:"):
                    stock_pos = pos["qty"]

        # Update benchmark (buy-and-hold: initial_cash - cost + stock_value)
        if benchmark_initial_price > 0 and current_price > 0:
            stock_cost = benchmark_initial_price * STOCK_QTY
            benchmark_equity = (INITIAL_CASH - stock_cost) + current_price * STOCK_QTY

        # Handle option expiry events
        for evt in events:
            if evt.get("type") == "OPTION_EXPIRY_EVENT":
                payload = evt.get("payload", {})
                contract = payload.get("contract", "")
                is_itm = payload.get("is_itm", False)
                assignment = payload.get("assignment")

                if is_itm and assignment:
                    action_str = (f"EXPIRY ITM: {contract[-15:]} -> "
                                  f"{assignment['side']} {assignment['qty']}sh @${assignment['strike']:.2f}")
                    print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                          f"{action_str:^35} | ${equity:9.2f}")
                    options_log.append({
                        "date": current_date, "action": "EXPIRY_ITM",
                        "contract": contract, "strike": assignment["strike"],
                        "outcome": f"call-away {assignment['qty']} shares",
                    })
                else:
                    action_str = f"EXPIRY OTM: {contract[-15:]} worthless"
                    print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                          f"{action_str:^35} | ${equity:9.2f}")
                    options_log.append({
                        "date": current_date, "action": "EXPIRY_OTM",
                        "contract": contract, "outcome": "expired worthless",
                    })

                active_call_contract = None

        # Re-buy stock if called away
        if stock_pos < STOCK_QTY and current_price > 0:
            order_seq += 1
            place_order(session_id, account_id, f"rebuy_stock_{order_seq}",
                        {"type": "STOCK", "symbol": UNDERLYING}, "BUY",
                        STOCK_QTY - stock_pos)
            action_str = f"RE-BUY {STOCK_QTY - stock_pos} shares"
            print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                  f"{action_str:^35} | ${equity:9.2f}")

        # Open new call if no active position
        if active_call_contract is None and contract_idx < len(contracts):
            # Find the right contract for current date
            # Use the next contract whose expiry hasn't passed yet
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
                    action_str = f"SELL {c['ticker'][-15:]} @${c['strike']:.2f}"
                    print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                          f"{action_str:^35} | ${equity:9.2f}")
                    options_log.append({
                        "date": current_date, "action": "SELL_CALL",
                        "contract": c["ticker"], "strike": c["strike"],
                        "expiry": c["expiry"], "premium": c["close"],
                    })

    # 5. Final results
    print_section("Results: Covered Call vs Buy-and-Hold")

    summary = get_summary(session_id)
    positions = get_positions(account_id)
    acct_state = get_account(account_id)

    overlay_return = summary["total_return"]
    benchmark_return = (benchmark_equity - INITIAL_CASH) / INITIAL_CASH

    print(f"\n  {'Metric':<25} {'Covered Call':>15} {'Buy-and-Hold':>15}")
    print("  " + "-" * 55)
    print(f"  {'Total Return':<25} {overlay_return*100:>14.2f}% {benchmark_return*100:>14.2f}%")
    print(f"  {'Final Equity':<25} ${summary['final_equity']:>13,.2f} ${benchmark_equity:>13,.2f}")
    print(f"  {'Max Drawdown':<25} {summary['max_drawdown']*100:>14.2f}% {'N/A':>15}")
    print(f"  {'Overlay Alpha':<25} {(overlay_return - benchmark_return)*100:>14.2f}%")
    print(f"\n  Fees Paid: ${summary['fees_paid']:.2f}")
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
        print(f"    {pos['instrument_id']:35s} {pos['qty']:6d} @ ${pos['avg_price']:.2f}")

    # 6. Save results
    print_section("Saving Results")

    export_data = get_export(session_id)
    saver = ResultSaver("overlay_profit_increase")

    saver.add_summary_line(f"Overlay Strategy: Covered Call (Profit Increase)")
    saver.add_summary_line(f"{'='*70}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Underlying: {UNDERLYING}")
    saver.add_summary_line(f"Period: {START_DATE} to {END_DATE}")
    saver.add_summary_line(f"Initial Capital: ${INITIAL_CASH:,.2f}")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Performance:")
    saver.add_summary_line(f"  Covered Call Return: {overlay_return*100:+.2f}%")
    saver.add_summary_line(f"  Buy-and-Hold Return: {benchmark_return*100:+.2f}%")
    saver.add_summary_line(f"  Overlay Alpha: {(overlay_return - benchmark_return)*100:+.2f}%")
    saver.add_summary_line(f"  Max Drawdown: {summary['max_drawdown']*100:.2f}%")
    saver.add_summary_line(f"  Fees Paid: ${summary['fees_paid']:.2f}")
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


if __name__ == "__main__":
    main()
```

**Step 2: Verify the script parses without errors**

Run: `cd /Users/efan404/Codes/research/qfinzero/infra/pmb && python -c "import ast; ast.parse(open('demos/overlay_profit_increase.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add infra/pmb/demos/overlay_profit_increase.py
git commit -m "feat(pmb): add covered call overlay demo (profit increase)"
```

---

## Task 3: Protective Put Demo `overlay_hedging.py`

**Files:**
- Create: `infra/pmb/demos/overlay_hedging.py`
- Reference: `infra/pmb/demos/overlay_profit_increase.py` (from Task 2, same structure)

**Step 1: Write the demo script**

Same structure as covered call, with these differences:
- BUY puts instead of SELL calls
- Strike target: `price * 0.95` (5% below)
- No call-away/re-buy logic needed
- Track premium paid (cost of protection) instead of premium received

```python
"""
Overlay Strategy Demo: Hedging (Protective Put)

Strategy:
  - Buy 100 shares AAPL on day 1
  - Each month: buy 1 OTM put (~5% below current price, ~30 days to expiry)
  - Let puts expire naturally (Plan A: no early roll)
  - Put ITM: closed at intrinsic value; OTM: expired worthless
  - Run for full year 2024

Prerequisites:
  - UPQ running on http://127.0.0.1:23333 with AAPL 2024 daily data
  - UPQ option chain on http://127.0.0.1:19350 with AAPL 2024 option data
  - PMB running on http://127.0.0.1:19320

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
    get_positions, get_account, print_section,
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
    try:
        resp = requests.get(f"http://127.0.0.1:23333/stock/daily", params={
            "tickers": underlying, "start": date, "end": date,
            "fields": "ticker,date,close",
        }, timeout=10)
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return rows[0]["close"]
    except Exception:
        pass
    return 185.0


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
```

**Step 2: Verify the script parses without errors**

Run: `cd /Users/efan404/Codes/research/qfinzero/infra/pmb && python -c "import ast; ast.parse(open('demos/overlay_hedging.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add infra/pmb/demos/overlay_hedging.py
git commit -m "feat(pmb): add protective put overlay demo (hedging)"
```

---

## Task 4: Update `run_all.py`

**Files:**
- Modify: `infra/pmb/demos/run_all.py:39-43`

**Step 1: Add new demos to the runner**

Add the two overlay demos to the `demos` list:

```python
    demos = [
        ("daily_buy_close.py", "Daily Buy-at-Close Strategy (AAPL Jan 2025)"),
        ("intraday_5min_signal.py", "Intraday 5-Min Mean Reversion (AAPL)"),
        ("covered_call.py", "Covered Call Strategy (NVDA with Options)"),
        ("overlay_profit_increase.py", "Overlay: Covered Call Profit Increase (AAPL 2024)"),
        ("overlay_hedging.py", "Overlay: Protective Put Hedging (AAPL 2024)"),
    ]
```

**Step 2: Verify**

Run: `cd /Users/efan404/Codes/research/qfinzero/infra/pmb && python -c "import ast; ast.parse(open('demos/run_all.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add infra/pmb/demos/run_all.py
git commit -m "feat(pmb): add overlay demos to run_all.py"
```

---

## Task 5: Smoke Test with Live Services

**Prerequisites:** UPQ running on `:23333` + `:19350`, PMB running on `:19320`

**Step 1: Run covered call demo**

Run: `cd /Users/efan404/Codes/research/qfinzero/infra/pmb && python demos/overlay_profit_increase.py`

Expected:
- Phase 1 shows ~12 discovered contracts
- Phase 3 shows daily trading log with SELL_CALL and EXPIRY events
- Results section shows return comparison vs buy-and-hold
- Results saved to `results/overlay_profit_increase_*/`

**Step 2: Run protective put demo**

Run: `cd /Users/efan404/Codes/research/qfinzero/infra/pmb && python demos/overlay_hedging.py`

Expected:
- Similar output with BUY_PUT events instead of SELL_CALL
- Protective put return should be lower than buy-and-hold (premium cost)
- Results saved to `results/overlay_hedging_*/`

**Step 3: Verify results files**

Run: `ls -la infra/pmb/results/overlay_*/`

Expected: Two result directories with summary.json, equity_curve.csv, trades.csv, report.txt

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat(pmb): overlay strategy demos verified end-to-end"
```

---

## Task 6: LLM-Driven Overlay Agent (Phase 2 — After Task 5 Verified)

> This task replaces the hardcoded rule logic with LLM decision-making.
> Only start after Task 5 passes end-to-end.

**Files:**
- Create: `infra/pmb/demos/overlay_llm_agent.py`
- Reference: `eval/models.yaml:34-38` (DeepSeek config)
- Reference: `eval/planning/runner/run_multistep.py:245-274` (call_model pattern)

### Architecture

```
每个交易日:
  1. 构建 prompt (市场状态 + 持仓 + 期权链 + 策略指令)
  2. 调用 DeepSeek API → 返回 JSON action
  3. 解析 action → 调用 PMB 下单
  4. 记录: latency, prompt_tokens, completion_tokens, equity
```

### LLM Config (from eval/models.yaml)

```python
LLM_CONFIG = {
    "model_name": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "${DEEPSEEK_API_KEY}",  # from eval/models.yaml:36
    "call_latency_s": 1.0,
}
```

Better: load directly from `eval/models.yaml` to keep config DRY.

### Token & Latency Tracking

The existing `call_model()` in `eval/planning/runner/run_multistep.py:245-274` only
extracts `content` from the response, but OpenAI-compatible APIs return a `usage` field:

```json
{
  "choices": [...],
  "usage": {
    "prompt_tokens": 1234,
    "completion_tokens": 567,
    "total_tokens": 1801
  }
}
```

The LLM agent should extract and accumulate these:

```python
def call_llm(prompt: str) -> tuple[str, float, dict]:
    """Returns (content, latency_s, usage_dict)."""
    t0 = time.monotonic()
    resp = httpx.post(url, json=payload, headers=headers, timeout=90)
    latency = time.monotonic() - t0
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, latency, usage
```

### Three Key Metrics to Track

**1. Latency (耗时)**
- Per-call latency (seconds)
- Total backtest wall time
- Avg latency per trading day
- Saved to: `results/overlay_llm_*/timing.json`

```json
{
  "total_wall_time_s": 312.5,
  "total_llm_calls": 252,
  "avg_latency_per_call_s": 1.24,
  "avg_latency_per_day_s": 1.24,
  "call_latency_p50_s": 1.1,
  "call_latency_p95_s": 2.3
}
```

**2. Token Consumption (Token 消耗)**
- Total prompt tokens
- Total completion tokens
- Estimated cost (DeepSeek pricing: ~$0.14/M input, ~$0.28/M output for deepseek-chat)
- Saved to: `results/overlay_llm_*/tokens.json`

```json
{
  "total_prompt_tokens": 315000,
  "total_completion_tokens": 25200,
  "total_tokens": 340200,
  "estimated_cost_usd": 0.051,
  "avg_prompt_tokens_per_call": 1250,
  "avg_completion_tokens_per_call": 100
}
```

**3. Equity Curve (账户曲线)**
- Daily equity snapshots (same as rule-based demos)
- Comparison columns: LLM agent vs rule-based vs buy-and-hold
- Saved to: `results/overlay_llm_*/equity_curve.csv`

```csv
date,llm_equity,rule_equity,benchmark_equity
2024-01-02,100000.00,100000.00,100000.00
2024-01-03,100150.00,100120.00,100100.00
...
```

### Prompt Design (Sketch)

```
You are an options overlay trading agent. Your goal is to enhance returns
on an existing AAPL stock position using covered call writing.

Current state:
- Date: {date}
- AAPL price: ${price}
- Cash: ${cash}
- Stock position: {qty} shares
- Active options: {options_list}
- Available contracts: {chain_summary}

Rules:
- You MUST maintain 100 shares of AAPL at all times
- You may sell up to 1 call contract at a time (covered)
- Respond with JSON: {"action": "sell_call"|"hold"|"close_call", "contract": "...", "reason": "..."}
```

### Step-by-Step (high-level, detailed plan TBD after Task 5)

1. Create `overlay_llm_agent.py` with LLM call loop
2. Load DeepSeek config from `eval/models.yaml`
3. Build prompt template with market state injection
4. Parse LLM JSON response → PMB order
5. Accumulate timing/token/equity metrics
6. Save results with comparison to rule-based baseline
7. Smoke test with live services

---

## Summary

| Task | Description | Files | Phase |
|------|-------------|-------|-------|
| 1 | Shared helper module | `demos/overlay_helpers.py` | 1 (rule-based) |
| 2 | Covered Call demo | `demos/overlay_profit_increase.py` | 1 |
| 3 | Protective Put demo | `demos/overlay_hedging.py` | 1 |
| 4 | Update run_all.py | `demos/run_all.py` (modify) | 1 |
| 5 | Smoke test with live services | Verify end-to-end | 1 |
| 6 | LLM-driven overlay agent | `demos/overlay_llm_agent.py` | 2 (after Task 5) |
