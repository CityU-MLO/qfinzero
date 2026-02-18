# PMB Agent Tool Reference

This document describes the PMB (Paper Money Broker) client as a set of callable tools for an AI agent. Each tool maps to a `PMBClient` method.

PMB is a step-driven paper trading simulator. The typical workflow is: **create account → create session → step loop (observe market + place orders) → review summary**.

## Setup

```python
from qfinzero.clients.pmb import PMBClient, StepResult, PMBError
pmb = PMBClient()  # default: http://127.0.0.1:24444
```

---

## Core Workflow

```
create_account() → create_session() → step() loop → get_summary()
                                         ↑     ↓
                                    observe  place orders
                                    market   (buy/sell)
```

### Minimal Example

```python
with PMBClient() as pmb:
    acct = pmb.create_account(initial_cash=50000.0, start_date="2025-01-06")
    sess = pmb.create_session(
        account_id=acct["account_id"],
        frequency="1d",
        start_ts="2025-01-06",
        end_ts="2025-01-31",
        universe={"stocks": ["AAPL"]},
    )
    sid, aid = sess["session_id"], acct["account_id"]

    while True:
        result = pmb.step(sid)
        if not result.is_running:
            break
        price = result.get_stock_price("AAPL")
        if price and price < 240:
            pmb.buy(sid, aid, "AAPL", 10)

    summary = pmb.get_summary(sid)
    print(f"Return: {summary['total_return']:.2%}")
```

---

## Tools

### 1. `create_account` — Create Trading Account

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `initial_cash` | `float` | Yes | — | Starting cash balance |
| `account_type` | `str` | No | `"MARGIN"` | `"MARGIN"` or `"CASH"` |
| `start_date` | `str` | No | — | Account creation date `YYYY-MM-DD` |
| `margin_config` | `dict` | No | — | Custom margin settings |

**Example:**
```python
acct = pmb.create_account(initial_cash=100000.0, start_date="2025-01-06")
```

**Returns:**
```json
{
  "ok": true,
  "account_id": "acct_2a3c6e",
  "created_at": "2026-02-17T06:08:27.127088+00:00",
  "account_state": {
    "cash_available": 100000.0,
    "cash_locked": 0.0,
    "loan": 0.0,
    "equity": 100000.0,
    "initial_margin_req": 0.0,
    "maintenance_margin_req": 0.0,
    "margin_excess": 100000.0,
    "buying_power": 200000.0,
    "margin_status": "NORMAL",
    "positions": [],
    "open_orders": []
  }
}
```

**Key field:** `account_id` — needed for all subsequent calls.

---

### 2. `create_session` — Create Simulation Session

A session defines the time range, frequency, and universe of instruments to simulate.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `account_id` | `str` | Yes | Account ID from `create_account` |
| `frequency` | `str` | Yes | `"1d"` (daily) or `"1m"` (minute) |
| `start_ts` | `str` | Yes | Simulation start `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS` |
| `end_ts` | `str` | Yes | Simulation end |
| `universe` | `dict` | Yes | Instruments: `{"stocks": ["AAPL"], "options": ["O:NVDA..."]}` |
| `execution_config` | `dict` | No | Execution settings (slippage, fees) |
| `reproducibility` | `dict` | No | Random seed settings |

**Example:**
```python
sess = pmb.create_session(
    account_id="acct_2a3c6e",
    frequency="1d",
    start_ts="2025-01-06",
    end_ts="2025-01-31",
    universe={"stocks": ["AAPL", "MSFT"]},
)
```

**Returns:**
```json
{
  "ok": true,
  "session_id": "sess_a1b2c3d4",
  "account_id": "acct_2a3c6e",
  "clock": {
    "frequency": "1d",
    "current_ts": "2025-01-06T00:00:00",
    "end_ts": "2025-01-31T00:00:00",
    "status": "RUNNING"
  }
}
```

**Key field:** `session_id` — needed for step/order/market calls.

**Frequency guide:**
- `"1d"`: One step = one trading day. Market data is daily OHLCV.
- `"1m"`: One step = one minute. Market data is minute OHLCV.

---

### 3. `step` — Advance Simulation

Advances the simulation clock by one step. Returns market data and any events (order fills, account updates, etc.).

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `session_id` | `str` | Yes | — | Session ID |
| `n` | `int` | No | `1` | Number of steps to advance |

**Example:**
```python
result = pmb.step("sess_a1b2c3d4")
```

**Returns:** `StepResult` object wrapping:
```json
{
  "ok": true,
  "session_id": "sess_a1b2c3d4",
  "clock": {
    "prev_ts": "2025-01-06T00:00:00",
    "current_ts": "2025-01-07T00:00:00",
    "frequency": "1d",
    "status": "RUNNING"
  },
  "events": [
    {
      "event_id": "evt_000001",
      "ts": "2025-01-07T00:00:00",
      "type": "MARKET_TICK",
      "payload": {
        "frequency": "1d",
        "stocks": [
          {
            "symbol": "AAPL",
            "window_start_ns": 1736155800000000000,
            "open": 243.74,
            "high": 244.13,
            "low": 241.35,
            "close": 242.21,
            "volume": 45036584
          }
        ],
        "options": []
      }
    },
    {
      "event_id": "evt_000002",
      "ts": "2025-01-07T00:00:00",
      "type": "ACCOUNT_SNAPSHOT",
      "payload": {
        "cash_available": 50000.0,
        "cash_locked": 0.0,
        "loan": 0.0,
        "equity": 50000.0,
        "initial_margin_req": 0.0,
        "maintenance_margin_req": 0.0,
        "margin_excess": 50000.0,
        "buying_power": 100000.0,
        "margin_status": "NORMAL",
        "positions": [],
        "open_orders": []
      }
    }
  ]
}
```

#### StepResult Helper Methods

| Method / Property | Returns | Description |
|-------------------|---------|-------------|
| `result.is_running` | `bool` | `True` if session still active |
| `result.current_ts` | `str` | Current simulation timestamp |
| `result.status` | `str` | `"RUNNING"`, `"STOPPED"`, or `"FINISHED"` |
| `result.events` | `list` | Raw list of event dicts |
| `result.get_stock_price("AAPL")` | `float \| None` | Close price from MARKET_TICK |
| `result.get_stock_bar("AAPL")` | `dict \| None` | Full OHLCV bar from MARKET_TICK |
| `result.get_market_tick()` | `dict \| None` | Full market tick payload |
| `result.get_snapshot()` | `dict \| None` | Account snapshot payload |
| `result.get_event("ORDER_EVENT")` | `dict \| None` | First event of given type |

**Step loop pattern:**
```python
while True:
    result = pmb.step(sid)
    if not result.is_running:
        break
    # Read market data
    price = result.get_stock_price("AAPL")
    # Read account state
    snap = result.get_snapshot()
    cash = snap["cash_available"] if snap else 0
    # Make decisions and place orders...
```

---

### 4. `buy` — Buy Stock

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `session_id` | `str` | Yes | — | Session ID |
| `account_id` | `str` | Yes | — | Account ID |
| `symbol` | `str` | Yes | — | Stock ticker, e.g. `"AAPL"` |
| `qty` | `int` | Yes | — | Number of shares |
| `order_type` | `str` | No | `"MARKET"` | `"MARKET"`, `"LIMIT"`, `"STOP"`, `"STOP_LIMIT"` |
| `limit_price` | `float` | No | — | Required for LIMIT / STOP_LIMIT orders |
| `stop_price` | `float` | No | — | Required for STOP / STOP_LIMIT orders |
| `time_in_force` | `str` | No | `"DAY"` | `"DAY"`, `"GTC"`, `"GTD"` |
| `client_order_id` | `str` | No | — | Custom order ID for tracking |

**Example:**
```python
order = pmb.buy("sess_a1b2c3d4", "acct_2a3c6e", "AAPL", 10)
# Limit order:
order = pmb.buy(sid, aid, "AAPL", 10, order_type="LIMIT", limit_price=240.00)
```

**Returns:**
```json
{
  "ok": true,
  "order_id": "ord_1a2b3c4d",
  "client_order_id": null,
  "status": "ACCEPTED"
}
```

**Note:** Orders are processed on the next `step()`. The step response will include `ORDER_EVENT` and `TRADE_EVENT` for fills:

```json
{
  "type": "ORDER_EVENT",
  "payload": {
    "order_id": "ord_1a2b3c4d",
    "status": "FILLED",
    "filled_qty": 10,
    "remaining_qty": 0,
    "avg_fill_price": 242.21
  }
}
```

```json
{
  "type": "TRADE_EVENT",
  "payload": {
    "trade_id": "trd_5e6f7g8h",
    "order_id": "ord_1a2b3c4d",
    "instrument_id": "STOCK:AAPL",
    "side": "BUY",
    "qty": 10,
    "price": 242.21,
    "fees": 0.05
  }
}
```

---

### 5. `sell` — Sell Stock

Same parameters as `buy`. Side is automatically set to `"SELL"`.

```python
order = pmb.sell(sid, aid, "AAPL", 10)
```

---

### 6. `buy_option` — Buy Option Contract

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `session_id` | `str` | Yes | — | Session ID |
| `account_id` | `str` | Yes | — | Account ID |
| `contract` | `str` | Yes | — | OPRA contract ID, e.g. `"O:NVDA250117C00136000"` |
| `qty` | `int` | Yes | — | Number of contracts |
| `order_type` | `str` | No | `"MARKET"` | Order type |
| `limit_price` | `float` | No | — | Limit price |
| `time_in_force` | `str` | No | `"GTC"` | Time in force |

**Example:**
```python
order = pmb.buy_option(sid, aid, "O:NVDA250117C00136000", 2)
```

---

### 7. `sell_option` — Sell Option Contract

Same parameters as `buy_option`. Side is automatically set to `"SELL"`.

```python
order = pmb.sell_option(sid, aid, "O:NVDA250117C00136000", 2)
```

---

### 8. `cancel_order` — Cancel Open Order

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `order_id` | `str` | Yes | Order ID to cancel |
| `session_id` | `str` | Yes | Session ID |
| `account_id` | `str` | Yes | Account ID |

```python
result = pmb.cancel_order("ord_1a2b3c4d", sid, aid)
```

---

### 9. `get_account` — Get Account State

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `account_id` | `str` | Yes | Account ID |

**Returns:**
```json
{
  "cash_available": 47578.90,
  "cash_locked": 0.0,
  "loan": 0.0,
  "equity": 50000.00,
  "initial_margin_req": 1210.50,
  "maintenance_margin_req": 605.25,
  "margin_excess": 49394.75,
  "buying_power": 98789.50,
  "margin_status": "NORMAL",
  "positions": [
    {
      "instrument_id": "STOCK:AAPL",
      "type": "STOCK",
      "qty": 10,
      "avg_price": 242.21,
      "mark_price": 243.50,
      "unrealized_pnl": 12.90,
      "realized_pnl": 0.0
    }
  ],
  "open_orders": []
}
```

---

### 10. `get_positions` — Get Current Positions

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `account_id` | `str` | Yes | Account ID |

**Returns:** `list[dict]` — each position:
```json
{
  "instrument_id": "STOCK:AAPL",
  "type": "STOCK",
  "qty": 10,
  "avg_price": 242.21,
  "mark_price": 243.50,
  "unrealized_pnl": 12.90,
  "realized_pnl": 0.0
}
```

---

### 11. `get_orders` — Get Order History

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `account_id` | `str` | Yes | Account ID |
| `session_id` | `str` | No | Filter by session |

**Returns:** `list[dict]` — each order:
```json
{
  "order_id": "ord_1a2b3c4d",
  "client_order_id": null,
  "session_id": "sess_a1b2c3d4",
  "account_id": "acct_2a3c6e",
  "instrument_id": "STOCK:AAPL",
  "side": "BUY",
  "order_type": "MARKET",
  "qty": 10,
  "filled_qty": 10,
  "remaining_qty": 0,
  "limit_price": null,
  "stop_price": null,
  "avg_fill_price": 242.21,
  "time_in_force": "DAY",
  "status": "FILLED",
  "created_ts": "2025-01-07T00:00:00",
  "last_update_ts": "2025-01-07T00:00:00",
  "reject_reason": null
}
```

**Order statuses:** `NEW`, `ACCEPTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, `REJECTED`, `EXPIRED`

---

### 12. `get_trades` — Get Trade History

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `account_id` | `str` | Yes | Account ID |
| `session_id` | `str` | No | Filter by session |

**Returns:** `list[dict]` — each trade:
```json
{
  "trade_id": "trd_5e6f7g8h",
  "order_id": "ord_1a2b3c4d",
  "instrument_id": "STOCK:AAPL",
  "side": "BUY",
  "qty": 10,
  "price": 242.21,
  "fees": 0.05,
  "ts": "2025-01-07T00:00:00"
}
```

---

### 13. `get_market` — Get Current Market Snapshot

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | `str` | Yes | Session ID |

**Returns:**
```json
{
  "ts": "2025-01-07T00:00:00",
  "stocks": [
    {
      "symbol": "AAPL",
      "open": 243.74,
      "high": 244.13,
      "low": 241.35,
      "close": 242.21,
      "volume": 45036584
    }
  ],
  "options": []
}
```

---

### 14. `get_summary` — Get Session Performance Summary

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | `str` | Yes | Session ID |

**Returns:**
```json
{
  "session_id": "sess_a1b2c3d4",
  "run_id": null,
  "start_ts": "2025-01-06T00:00:00",
  "end_ts": "2025-01-31T00:00:00",
  "final_equity": 51250.50,
  "total_return": 0.02501,
  "max_drawdown": 0.015,
  "fees_paid": 2.50,
  "num_orders": 5,
  "num_trades": 5,
  "reject_rate": 0.0,
  "invalid_action_rate": 0.0,
  "margin_call_count": 0
}
```

**Key metrics:**
- `total_return`: Decimal (0.025 = 2.5%). Format as `f"{summary['total_return']:.2%}"`.
- `max_drawdown`: Maximum peak-to-trough decline as decimal.
- `reject_rate`: Fraction of orders rejected (e.g. insufficient margin).

---

### 15. `stop_session` — Stop Session Early

```python
pmb.stop_session("sess_a1b2c3d4")
```

---

### 16. `export` — Export Full Session Data

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `session_id` | `str` | Yes | — | Session ID |
| `fmt` | `str` | No | `"json"` | `"json"` or `"csv"` |

**Returns (JSON):**
```json
{
  "orders": [ ... ],
  "order_events": [ ... ],
  "trades": [ ... ],
  "equity_curve": [
    {"ts": "2025-01-06T00:00:00", "equity": 50000.0},
    {"ts": "2025-01-07T00:00:00", "equity": 50125.0}
  ],
  "snapshots": [ ... ]
}
```

---

## Event Types Reference

Events are emitted during `step()` and accessed via `result.events`:

| Event Type | Description | Key Payload Fields |
|------------|-------------|-------------------|
| `MARKET_TICK` | New price data | `stocks[].symbol/open/high/low/close/volume`, `options[]` |
| `ORDER_EVENT` | Order status change | `order_id`, `status`, `filled_qty`, `avg_fill_price` |
| `TRADE_EVENT` | Trade execution | `trade_id`, `order_id`, `instrument_id`, `side`, `qty`, `price`, `fees` |
| `ACCOUNT_SNAPSHOT` | Account state update | `cash_available`, `equity`, `positions[]`, `margin_status` |
| `RISK_EVENT` | Margin warning/liquidation | `level`, `reason_code`, `equity`, `action` |
| `ERROR_EVENT` | Error occurred | `error_code`, `message` |

---

## Enumerations

| Enum | Values |
|------|--------|
| Frequency | `"1d"` (daily), `"1m"` (minute) |
| Order Type | `"MARKET"`, `"LIMIT"`, `"STOP"`, `"STOP_LIMIT"` |
| Side | `"BUY"`, `"SELL"` |
| Time in Force | `"DAY"`, `"GTC"`, `"GTD"` |
| Order Status | `"NEW"`, `"ACCEPTED"`, `"PARTIALLY_FILLED"`, `"FILLED"`, `"CANCELLED"`, `"REJECTED"`, `"EXPIRED"` |
| Margin Status | `"NORMAL"`, `"MARGIN_CALL"`, `"RESTRICTED"`, `"LIQUIDATION"` |
| Session Status | `"RUNNING"`, `"STOPPED"`, `"FINISHED"` |
| Instrument ID | `"STOCK:AAPL"`, `"OPTION:O:NVDA250117C00136000"` |

---

## Error Handling

All methods raise `PMBError` on failure:

```python
from qfinzero.clients.pmb import PMBError

try:
    pmb.buy(sid, aid, "INVALID", 10)
except PMBError as e:
    print(e)              # Human-readable message
    print(e.status_code)  # HTTP status (400, 422, etc.)
    print(e.response)     # Full error response dict
```

---

## Agent Workflow Examples

### Example 1: Daily Accumulation Strategy

Buy 10 shares of AAPL every trading day:

```python
with PMBClient() as pmb:
    acct = pmb.create_account(initial_cash=100000.0, start_date="2025-01-06")
    sess = pmb.create_session(
        account_id=acct["account_id"],
        frequency="1d",
        start_ts="2025-01-06",
        end_ts="2025-01-31",
        universe={"stocks": ["AAPL"]},
    )
    sid, aid = sess["session_id"], acct["account_id"]

    while True:
        result = pmb.step(sid)
        if not result.is_running:
            break
        pmb.buy(sid, aid, "AAPL", 10)

    summary = pmb.get_summary(sid)
    print(f"Final equity: ${summary['final_equity']:,.2f}")
    print(f"Return: {summary['total_return']:.2%}")
    print(f"Max drawdown: {summary['max_drawdown']:.2%}")
```

### Example 2: Price-Triggered Trading

Buy when price dips below threshold, sell when above:

```python
with PMBClient() as pmb:
    acct = pmb.create_account(initial_cash=50000.0, start_date="2025-01-06")
    sess = pmb.create_session(
        account_id=acct["account_id"],
        frequency="1d",
        start_ts="2025-01-06",
        end_ts="2025-01-31",
        universe={"stocks": ["AAPL"]},
    )
    sid, aid = sess["session_id"], acct["account_id"]
    holding = 0

    while True:
        result = pmb.step(sid)
        if not result.is_running:
            break

        price = result.get_stock_price("AAPL")
        snap = result.get_snapshot()
        if not price or not snap:
            continue

        if price < 240 and holding == 0:
            pmb.buy(sid, aid, "AAPL", 20)
            holding = 20
        elif price > 245 and holding > 0:
            pmb.sell(sid, aid, "AAPL", holding)
            holding = 0

    print(pmb.get_summary(sid))
```

### Example 3: Options Trading with UPQ

Use UPQ to find an option contract, then trade it in PMB:

```python
from qfinzero.clients.upq import UPQClient

with PMBClient() as pmb, UPQClient() as upq:
    # Find a call option via UPQ
    chain = upq.option_chain("NVDA", "2025-01-06", type="C",
                              strike_min=130, strike_max=140)
    contract = chain[0]["ticker"]  # e.g. "O:NVDA250117C00130000"

    # Create PMB session with that option in the universe
    acct = pmb.create_account(initial_cash=100000.0, start_date="2025-01-06")
    sess = pmb.create_session(
        account_id=acct["account_id"],
        frequency="1d",
        start_ts="2025-01-06",
        end_ts="2025-01-17",
        universe={"stocks": ["NVDA"], "options": [contract]},
    )
    sid, aid = sess["session_id"], acct["account_id"]

    result = pmb.step(sid)
    # Buy the option
    pmb.buy_option(sid, aid, contract, 5)

    # Continue stepping...
    while True:
        result = pmb.step(sid)
        if not result.is_running:
            break

    print(pmb.get_summary(sid))
```
