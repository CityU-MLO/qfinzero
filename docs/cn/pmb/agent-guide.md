> English: [../../en/pmb/agent-guide.md](../../en/pmb/agent-guide.md)

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
