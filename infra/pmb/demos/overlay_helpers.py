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
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1, day=2)
        else:
            current = current.replace(month=current.month + 1, day=2)

    return result


def query_stock_price(underlying: str, date: str) -> float | None:
    """Get stock close price from UPQ for a specific date."""
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
