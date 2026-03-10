"""
Shared helpers for overlay strategy demos.
"""

import json
import subprocess

import requests
from datetime import datetime, timedelta

PMB_BASE = "http://127.0.0.1:19701"
UPQ_CHAIN = "http://127.0.0.1:19703"
QLIB_CONTEXT_DIR = "/home/qlib/news/llm_context_2025"


def load_remote_json(remote_path: str) -> dict | None:
    """Load a JSON file — local first, then SSH fallback.

    If the file exists locally (e.g. running on qlib), reads it directly.
    Otherwise falls back to ``ssh qlib "cat <path>"``.
    Returns the parsed dict on success, or None on failure.
    """
    import os

    # Try local file first (works when running on qlib itself)
    if os.path.isfile(remote_path):
        try:
            with open(remote_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [WARN] load_remote_json: local read failed for {remote_path}: {e}")
            return None

    # Fallback to SSH (works when running from local machine)
    try:
        result = subprocess.run(
            ["ssh", "qlib", f"cat {remote_path}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print(f"  [WARN] load_remote_json: ssh failed for {remote_path}: {result.stderr.strip()}")
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        print(f"  [WARN] load_remote_json: timeout reading {remote_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"  [WARN] load_remote_json: invalid JSON in {remote_path}: {e}")
        return None
    except Exception as e:
        print(f"  [WARN] load_remote_json: {e}")
        return None


def load_macro_context(current_month: str) -> dict:
    """Load macro context files for a given month.

    Args:
        current_month: Month string like "2025-01".

    Returns:
        {"last_month_review": {...}, "next_month_upcoming": {...}}
        Values are None if the corresponding file could not be loaded.
    """
    # Compute previous month
    year, month = int(current_month[:4]), int(current_month[5:7])
    if month == 1:
        prev_month = f"{year - 1}-12"
    else:
        prev_month = f"{year}-{month - 1:02d}"

    review_path = f"{QLIB_CONTEXT_DIR}/macro/{prev_month}_review.json"
    upcoming_path = f"{QLIB_CONTEXT_DIR}/macro/{current_month}_upcoming.json"

    return {
        "last_month_review": load_remote_json(review_path),
        "next_month_upcoming": load_remote_json(upcoming_path),
    }


def load_semi_earnings() -> dict | None:
    """Load semiconductor earnings context from qlib.

    Returns the parsed dict, or None if loading fails.
    """
    return load_remote_json(f"{QLIB_CONTEXT_DIR}/semi_earnings_2025.json")


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
        "include_greeks": "true",
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
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1, day=2)
        else:
            current = current.replace(month=current.month + 1, day=2)

    return result


def get_weekly_option_dates(start_date: str, end_date: str,
                            dte_min: int = 7, dte_max: int = 45
                            ) -> list[tuple[str, str, str]]:
    """Generate (query_date, expiry_min, expiry_max) tuples for each week.

    query_date: Monday of each week (or start_date for the first week)
    expiry_min/max: target expiry window based on dte_min/dte_max
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    result = []

    current = start
    while current < end:
        query_date = current.strftime("%Y-%m-%d")
        expiry_min = (current + timedelta(days=dte_min)).strftime("%Y-%m-%d")
        expiry_max = (current + timedelta(days=dte_max)).strftime("%Y-%m-%d")
        result.append((query_date, expiry_min, expiry_max))
        # Advance to next Monday
        days_to_monday = 7 - current.weekday()  # 0=Mon, so Mon->7
        if current.weekday() == 0:
            days_to_monday = 7
        current = current + timedelta(days=days_to_monday)

    return result


def discover_contracts_weekly(underlying: str, start_date: str, end_date: str,
                              option_type: str, otm_pct: float,
                              ref_price: float,
                              dte_min: int = 7, dte_max: int = 45
                              ) -> list[dict]:
    """Pre-discover option contracts for weekly rebalance schedule.

    Same logic as discover_contracts but uses weekly intervals and
    configurable DTE window instead of fixed monthly 25-35 day window.
    Deduplicates by ticker — each unique contract appears only once.
    """
    weeks = get_weekly_option_dates(start_date, end_date, dte_min, dte_max)
    contracts = []
    seen_tickers = set()

    for query_date, expiry_min, expiry_max in weeks:
        week_price = query_stock_price(underlying, query_date) or ref_price

        if option_type == "C":
            strike_min = week_price * (1 + otm_pct * 0.5)
            strike_max = week_price * (1 + otm_pct * 2.0)
            target_strike = week_price * (1 + otm_pct)
        else:  # P
            strike_min = week_price * (1 - otm_pct * 2.0)
            strike_max = week_price * (1 - otm_pct * 0.5)
            target_strike = week_price * (1 - otm_pct)

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
            ticker = selected["ticker"]
            if ticker in seen_tickers:
                print(f"  [DISCOVERY] {query_date} (spot=${week_price:.2f}): "
                      f"{ticker} (already discovered, skipping)")
                continue
            seen_tickers.add(ticker)
            contracts.append({
                "ticker": ticker,
                "strike": selected["strike"],
                "expiry": selected["expiry"],
                "close": selected["close"],
                "query_date": query_date,
            })
            print(f"  [DISCOVERY] {query_date} (spot=${week_price:.2f}): {ticker} "
                  f"strike=${selected['strike']:.2f} expiry={selected['expiry']} "
                  f"premium=${selected['close']:.2f}")
        else:
            print(f"  [DISCOVERY] {query_date} (spot=${week_price:.2f}): "
                  f"no suitable {option_type} contract found")

    return contracts


def get_etf_daily_prices(ticker: str, start_date: str, end_date: str) -> list[dict]:
    """Get daily close prices for an ETF from UPQ.

    Returns list of {date, close} sorted by date.
    """
    try:
        resp = requests.get(f"{UPQ_CHAIN}/stock/daily", params={
            "tickers": ticker,
            "start": start_date,
            "end": end_date,
            "fields": "ticker,date,close",
        }, timeout=30)
        if resp.status_code == 200:
            rows = resp.json()
            return [{"date": r["date"][:10], "close": r["close"]} for r in rows]
    except Exception:
        pass
    return []


def get_etf_total_return(ticker: str, start_date: str, end_date: str) -> float | None:
    """Compute ETF total return (price + reinvested dividends).

    Uses price return + cumulative dividends / start price.
    """
    prices = get_etf_daily_prices(ticker, start_date, end_date)
    if len(prices) < 2:
        return None
    start_price = prices[0]["close"]
    end_price = prices[-1]["close"]

    # Query dividends
    try:
        resp = requests.get(f"{UPQ_CHAIN}/dividends/query", params={
            "tickers": ticker, "start": start_date, "end": end_date,
        }, timeout=30)
        divs = resp.json() if resp.status_code == 200 else []
    except Exception:
        divs = []

    total_divs = sum(d.get("amount", 0) for d in divs)
    return (end_price - start_price + total_divs) / start_price


def compute_initial_cash(stock_price: float, stock_qty: int,
                         cash_buffer_pct: float = 0.20) -> float:
    """Compute initial cash = stock notional + cash buffer (paper spec).

    E.g. QQQ $480 * 10,000 shares = $4.8M notional, 20% buffer = $960k,
    total = $5.76M.
    """
    stock_notional = stock_price * stock_qty
    cash_buffer = stock_notional * cash_buffer_pct
    return stock_notional + cash_buffer


def query_stock_price(underlying: str, date: str) -> float | None:
    """Get stock close price from UPQ for a specific date."""
    try:
        resp = requests.get(f"{UPQ_CHAIN}/stock/daily", params={
            "tickers": underlying, "start": date, "end": date,
            "fields": "ticker,date,close",
        }, timeout=10)
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return rows[0]["close"]
    except Exception:
        pass
    return None


def discover_contracts(underlying: str, start_date: str, end_date: str,
                       option_type: str, otm_pct: float,
                       ref_price: float) -> list[dict]:
    """Pre-discover all option contracts needed for the backtest period.

    Uses dynamic stock price per month for strike range calculation.
    Falls back to ref_price if UPQ price query fails.

    Args:
        underlying: Stock symbol
        start_date/end_date: Backtest period
        option_type: "C" or "P"
        otm_pct: OTM percentage for strike target (e.g. 0.05 for 5%)
        ref_price: Reference stock price (fallback if UPQ unavailable)

    Returns:
        List of selected contracts with {ticker, strike, expiry, close, query_date}
    """
    months = get_monthly_option_dates(start_date, end_date)
    contracts = []

    for query_date, expiry_min, expiry_max in months:
        # Dynamic price: query actual stock price for this month
        month_price = query_stock_price(underlying, query_date) or ref_price

        if option_type == "C":
            strike_min = month_price * (1 + otm_pct * 0.5)
            strike_max = month_price * (1 + otm_pct * 2.0)
            target_strike = month_price * (1 + otm_pct)
        else:  # P
            strike_min = month_price * (1 - otm_pct * 2.0)
            strike_max = month_price * (1 - otm_pct * 0.5)
            target_strike = month_price * (1 - otm_pct)

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
            print(f"  [DISCOVERY] {query_date} (spot=${month_price:.2f}): {selected['ticker']} "
                  f"strike=${selected['strike']:.2f} expiry={selected['expiry']} "
                  f"premium=${selected['close']:.2f}")
        else:
            print(f"  [DISCOVERY] {query_date} (spot=${month_price:.2f}): "
                  f"no suitable {option_type} contract found")

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
            "option_spread_pct": 0.05,
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


def place_spread(session_id: str, account_id: str, client_order_id: str,
                 legs: list[dict], spread_id: str | None = None) -> list[dict]:
    """Place a multi-leg spread order via PMB.

    Each leg is: {"instrument": {...}, "side": str, "qty": int}
    All legs share the same spread_id for atomic execution.
    spread_id is a top-level field on CreateOrderRequest (not inside OrderSpec).
    """
    import uuid
    sid = spread_id or str(uuid.uuid4())[:8]
    responses = []
    for i, leg in enumerate(legs):
        resp = requests.post(f"{PMB_BASE}/v1/orders", json={
            "session_id": session_id,
            "account_id": account_id,
            "client_order_id": f"{client_order_id}_leg{i}",
            "spread_id": sid,
            "order": {
                "instrument": leg["instrument"],
                "side": leg["side"],
                "order_type": "MARKET",
                "qty": leg["qty"],
                "time_in_force": "GTC",
            },
        })
        responses.append(resp.json())
    return responses


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


def query_option_greeks(contract: str, date: str) -> dict | None:
    """Get greeks for a specific option contract from UPQ."""
    try:
        resp = requests.get(f"{UPQ_CHAIN}/option/ticker_query", params={
            "contract": contract, "start": date, "end": date,
            "resolution": "day", "include_greeks": "true",
            "fields": "ticker,close,delta",
        }, timeout=10)
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return rows[0]
    except Exception:
        pass
    return None


def compute_effective_delta(stock_qty: int, option_positions: list[dict]) -> float:
    """Compute portfolio effective delta.

    Args:
        stock_qty: Number of shares held (positive = long)
        option_positions: List of {contract, qty, delta} where qty is signed
            (negative = short), delta is per-share delta from greeks

    Returns:
        Effective delta in share-equivalents.
    """
    delta = float(stock_qty)
    for pos in option_positions:
        # Each contract covers 100 shares
        # qty is signed: -1 = short 1 contract
        contract_delta = pos.get("delta", 0.0) * pos["qty"] * 100
        delta += contract_delta
    return delta


def print_section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")
