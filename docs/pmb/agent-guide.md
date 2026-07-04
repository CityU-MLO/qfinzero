> **English** (below) · [中文](#中文文档) (在下方)

# PMB Agent Tool Reference

This document describes the PMB (Paper Money Broker) client as a set of callable tools for an AI agent. Each tool maps to a `PMBClient` method.

PMB is a step-driven paper trading simulator. The typical workflow is: **create account → create session → step loop (observe market + place orders) → review summary**.

## Setup

```python
from qfinzero.clients.pmb import PMBClient, StepResult, PMBError
pmb = PMBClient()  # default: http://127.0.0.1:19380
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

---

<a id="中文文档"></a>

# 中文文档

# PMB Agent 工具参考

本文档将 PMB（Paper Money Broker）客户端描述为一组可供 AI 代理调用的工具。每个工具对应一个 `PMBClient` 方法。

PMB 是一个步进驱动的模拟交易模拟器。典型的工作流程是：**创建账户 → 创建会话 → 步进循环（观察市场 + 下单）→ 查看汇总**。

## 设置

```python
from qfinzero.clients.pmb import PMBClient, StepResult, PMBError
pmb = PMBClient()  # default: http://127.0.0.1:19380
```

---

## 核心工作流程

```
create_account() → create_session() → step() loop → get_summary()
                                         ↑     ↓
                                    observe  place orders
                                    market   (buy/sell)
```

### 最小示例

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

## 工具

### 1. `create_account` — 创建交易账户

**参数：**

| Name | Type | 是否必填 | 默认值 | 描述 |
|------|------|----------|---------|-------------|
| `initial_cash` | `float` | 是 | — | 初始现金余额 |
| `account_type` | `str` | 否 | `"MARGIN"` | `"MARGIN"` 或 `"CASH"` |
| `start_date` | `str` | 否 | — | 账户创建日期 `YYYY-MM-DD` |
| `margin_config` | `dict` | 否 | — | 自定义保证金设置 |

**示例：**
```python
acct = pmb.create_account(initial_cash=100000.0, start_date="2025-01-06")
```

**返回：**
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

**关键字段：** `account_id` — 后续所有调用都需要它。

---

### 2. `create_session` — 创建模拟会话

会话定义了要模拟的时间范围、频率和标的集合。

**参数：**

| Name | Type | 是否必填 | 描述 |
|------|------|----------|-------------|
| `account_id` | `str` | 是 | 来自 `create_account` 的账户 ID |
| `frequency` | `str` | 是 | `"1d"`（日级）或 `"1m"`（分钟级） |
| `start_ts` | `str` | 是 | 模拟开始 `YYYY-MM-DD` 或 `YYYY-MM-DDTHH:MM:SS` |
| `end_ts` | `str` | 是 | 模拟结束 |
| `universe` | `dict` | 是 | 标的：`{"stocks": ["AAPL"], "options": ["O:NVDA..."]}` |
| `execution_config` | `dict` | 否 | 执行设置（滑点、费用） |
| `reproducibility` | `dict` | 否 | 随机种子设置 |

**示例：**
```python
sess = pmb.create_session(
    account_id="acct_2a3c6e",
    frequency="1d",
    start_ts="2025-01-06",
    end_ts="2025-01-31",
    universe={"stocks": ["AAPL", "MSFT"]},
)
```

**返回：**
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

**关键字段：** `session_id` — step/order/market 调用都需要它。

**频率指南：**
- `"1d"`：一步 = 一个交易日。市场数据为日级 OHLCV。
- `"1m"`：一步 = 一分钟。市场数据为分钟级 OHLCV。

---

### 3. `step` — 推进模拟

将模拟时钟推进一步。返回市场数据以及任何事件（订单成交、账户更新等）。

**参数：**

| Name | Type | 是否必填 | 默认值 | 描述 |
|------|------|----------|---------|-------------|
| `session_id` | `str` | 是 | — | 会话 ID |
| `n` | `int` | 否 | `1` | 推进的步数 |

**示例：**
```python
result = pmb.step("sess_a1b2c3d4")
```

**返回：** 封装了以下内容的 `StepResult` 对象：
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

#### StepResult 辅助方法

| Method / Property | Returns | 描述 |
|-------------------|---------|-------------|
| `result.is_running` | `bool` | 若会话仍活跃则为 `True` |
| `result.current_ts` | `str` | 当前模拟时间戳 |
| `result.status` | `str` | `"RUNNING"`、`"STOPPED"` 或 `"FINISHED"` |
| `result.events` | `list` | 原始事件字典列表 |
| `result.get_stock_price("AAPL")` | `float \| None` | 来自 MARKET_TICK 的收盘价 |
| `result.get_stock_bar("AAPL")` | `dict \| None` | 来自 MARKET_TICK 的完整 OHLCV K 线 |
| `result.get_market_tick()` | `dict \| None` | 完整的市场 tick 载荷 |
| `result.get_snapshot()` | `dict \| None` | 账户快照载荷 |
| `result.get_event("ORDER_EVENT")` | `dict \| None` | 给定类型的第一个事件 |

**步进循环模式：**
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

### 4. `buy` — 买入股票

**参数：**

| Name | Type | 是否必填 | 默认值 | 描述 |
|------|------|----------|---------|-------------|
| `session_id` | `str` | 是 | — | 会话 ID |
| `account_id` | `str` | 是 | — | 账户 ID |
| `symbol` | `str` | 是 | — | 股票代码，例如 `"AAPL"` |
| `qty` | `int` | 是 | — | 股数 |
| `order_type` | `str` | 否 | `"MARKET"` | `"MARKET"`、`"LIMIT"`、`"STOP"`、`"STOP_LIMIT"` |
| `limit_price` | `float` | 否 | — | LIMIT / STOP_LIMIT 订单必填 |
| `stop_price` | `float` | 否 | — | STOP / STOP_LIMIT 订单必填 |
| `time_in_force` | `str` | 否 | `"DAY"` | `"DAY"`、`"GTC"`、`"GTD"` |
| `client_order_id` | `str` | 否 | — | 用于追踪的自定义订单 ID |

**示例：**
```python
order = pmb.buy("sess_a1b2c3d4", "acct_2a3c6e", "AAPL", 10)
# Limit order:
order = pmb.buy(sid, aid, "AAPL", 10, order_type="LIMIT", limit_price=240.00)
```

**返回：**
```json
{
  "ok": true,
  "order_id": "ord_1a2b3c4d",
  "client_order_id": null,
  "status": "ACCEPTED"
}
```

**注意：** 订单在下一次 `step()` 时处理。step 响应会包含成交对应的 `ORDER_EVENT` 和 `TRADE_EVENT`：

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

### 5. `sell` — 卖出股票

参数与 `buy` 相同。Side 自动设置为 `"SELL"`。

```python
order = pmb.sell(sid, aid, "AAPL", 10)
```

---

### 6. `buy_option` — 买入期权合约

**参数：**

| Name | Type | 是否必填 | 默认值 | 描述 |
|------|------|----------|---------|-------------|
| `session_id` | `str` | 是 | — | 会话 ID |
| `account_id` | `str` | 是 | — | 账户 ID |
| `contract` | `str` | 是 | — | OPRA 合约 ID，例如 `"O:NVDA250117C00136000"` |
| `qty` | `int` | 是 | — | 合约数量 |
| `order_type` | `str` | 否 | `"MARKET"` | 订单类型 |
| `limit_price` | `float` | 否 | — | 限价 |
| `time_in_force` | `str` | 否 | `"GTC"` | 有效期 |

**示例：**
```python
order = pmb.buy_option(sid, aid, "O:NVDA250117C00136000", 2)
```

---

### 7. `sell_option` — 卖出期权合约

参数与 `buy_option` 相同。Side 自动设置为 `"SELL"`。

```python
order = pmb.sell_option(sid, aid, "O:NVDA250117C00136000", 2)
```

---

### 8. `cancel_order` — 取消挂单

**参数：**

| Name | Type | 是否必填 | 描述 |
|------|------|----------|-------------|
| `order_id` | `str` | 是 | 要取消的订单 ID |
| `session_id` | `str` | 是 | 会话 ID |
| `account_id` | `str` | 是 | 账户 ID |

```python
result = pmb.cancel_order("ord_1a2b3c4d", sid, aid)
```

---

### 9. `get_account` — 获取账户状态

**参数：**

| Name | Type | 是否必填 | 描述 |
|------|------|----------|-------------|
| `account_id` | `str` | 是 | 账户 ID |

**返回：**
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

### 10. `get_positions` — 获取当前持仓

**参数：**

| Name | Type | 是否必填 | 描述 |
|------|------|----------|-------------|
| `account_id` | `str` | 是 | 账户 ID |

**返回：** `list[dict]` — 每个持仓：
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

### 11. `get_orders` — 获取订单历史

**参数：**

| Name | Type | 是否必填 | 描述 |
|------|------|----------|-------------|
| `account_id` | `str` | 是 | 账户 ID |
| `session_id` | `str` | 否 | 按会话过滤 |

**返回：** `list[dict]` — 每个订单：
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

**订单状态：** `NEW`、`ACCEPTED`、`PARTIALLY_FILLED`、`FILLED`、`CANCELLED`、`REJECTED`、`EXPIRED`

---

### 12. `get_trades` — 获取成交历史

**参数：**

| Name | Type | 是否必填 | 描述 |
|------|------|----------|-------------|
| `account_id` | `str` | 是 | 账户 ID |
| `session_id` | `str` | 否 | 按会话过滤 |

**返回：** `list[dict]` — 每笔成交：
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

### 13. `get_market` — 获取当前市场快照

**参数：**

| Name | Type | 是否必填 | 描述 |
|------|------|----------|-------------|
| `session_id` | `str` | 是 | 会话 ID |

**返回：**
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

### 14. `get_summary` — 获取会话绩效汇总

**参数：**

| Name | Type | 是否必填 | 描述 |
|------|------|----------|-------------|
| `session_id` | `str` | 是 | 会话 ID |

**返回：**
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

**关键指标：**
- `total_return`：小数（0.025 = 2.5%）。格式化为 `f"{summary['total_return']:.2%}"`。
- `max_drawdown`：以小数表示的最大峰谷回撤。
- `reject_rate`：被拒绝订单的比例（例如保证金不足）。

---

### 15. `stop_session` — 提前停止会话

```python
pmb.stop_session("sess_a1b2c3d4")
```

---

### 16. `export` — 导出完整会话数据

**参数：**

| Name | Type | 是否必填 | 默认值 | 描述 |
|------|------|----------|---------|-------------|
| `session_id` | `str` | 是 | — | 会话 ID |
| `fmt` | `str` | 否 | `"json"` | `"json"` 或 `"csv"` |

**返回 (JSON)：**
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

## 事件类型参考

事件在 `step()` 期间发出，可通过 `result.events` 访问：

| Event Type | 描述 | 关键载荷字段 |
|------------|-------------|-------------------|
| `MARKET_TICK` | 新的价格数据 | `stocks[].symbol/open/high/low/close/volume`、`options[]` |
| `ORDER_EVENT` | 订单状态变化 | `order_id`、`status`、`filled_qty`、`avg_fill_price` |
| `TRADE_EVENT` | 成交执行 | `trade_id`、`order_id`、`instrument_id`、`side`、`qty`、`price`、`fees` |
| `ACCOUNT_SNAPSHOT` | 账户状态更新 | `cash_available`、`equity`、`positions[]`、`margin_status` |
| `RISK_EVENT` | 保证金警告/强平 | `level`、`reason_code`、`equity`、`action` |
| `ERROR_EVENT` | 发生错误 | `error_code`、`message` |

---

## 枚举

| Enum | Values |
|------|--------|
| Frequency | `"1d"`（日级）、`"1m"`（分钟级） |
| Order Type | `"MARKET"`、`"LIMIT"`、`"STOP"`、`"STOP_LIMIT"` |
| Side | `"BUY"`、`"SELL"` |
| Time in Force | `"DAY"`、`"GTC"`、`"GTD"` |
| Order Status | `"NEW"`、`"ACCEPTED"`、`"PARTIALLY_FILLED"`、`"FILLED"`、`"CANCELLED"`、`"REJECTED"`、`"EXPIRED"` |
| Margin Status | `"NORMAL"`、`"MARGIN_CALL"`、`"RESTRICTED"`、`"LIQUIDATION"` |
| Session Status | `"RUNNING"`、`"STOPPED"`、`"FINISHED"` |
| Instrument ID | `"STOCK:AAPL"`、`"OPTION:O:NVDA250117C00136000"` |

---

## 错误处理

所有方法在失败时抛出 `PMBError`：

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

## 代理工作流程示例

### 示例 1：每日定投策略

每个交易日买入 10 股 AAPL：

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

### 示例 2：价格触发交易

价格跌破阈值时买入，涨破阈值时卖出：

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

### 示例 3：结合 UPQ 的期权交易

使用 UPQ 查找期权合约，然后在 PMB 中交易它：

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
