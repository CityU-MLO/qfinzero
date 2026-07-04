> **English** (below) · [中文](#中文文档) (在下方)

# Paper Money Broker (PMB)

A step-driven paper trading broker for backtesting AI trading agents. Supports stocks and options with full margin accounting, deterministic replay, and comprehensive event streams.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the server (requires UPQ on port 19350)
python main.py

# 3. Run demos
python demos/daily_buy_close.py
```

Server will listen on **http://127.0.0.1:19380**

---

## Architecture

PMB is a **FastAPI-based paper broker** designed for deterministic backtesting with these principles:

- **Step-driven**: Time advances via `POST /sessions/{id}/step` (no wall-clock dependency)
- **In-memory state**: Sessions are ephemeral replay episodes (fast, no DB overhead)
- **Event-sourced**: Every step returns typed events (MARKET_TICK, ORDER_EVENT, TRADE_EVENT, etc.)
- **Margin-aware**: Full initial/maintenance margin tracking with margin calls
- **Idempotent orders**: `client_order_id` prevents duplicate submissions

---

## Features

### Core Capabilities

- **Assets**: Stocks + Options (OPRA contracts)
- **Order Types**: MARKET, LIMIT, STOP, STOP_LIMIT
- **Time-in-Force**: DAY, GTC, GTD
- **Margin**: Initial/maintenance margins, buying power, margin calls
- **Execution**: Configurable slippage, commission models, partial fills
- **History**: Full order/trade/equity curve export (JSON/CSV)

### Trading Frequencies

- **Minute (1m)**: Intraday strategies with minute bars
- **Daily (1d)**: Multi-day strategies with daily bars

### Data Source

Integrates with **UPQ** (Unified Price Query) service:
- REST API at http://127.0.0.1:19350
- Stocks: minute/daily OHLCV bars
- Options: contract data with OPRA IDs
- See: [infra/upq/docs/api-usage.md](../upq/docs/api-usage.md)

---

## Broker Accounts (day-gated) + Terminal UI

On top of the replay engine, PMB exposes a **self-contained broker account** designed
for AI agents to drive directly — no backtest session required.

- **Unique 10-digit account id** is allocated per account. The leading digit encodes
  the market (`1`→US, `6`→CN, `3`→HK), so the number is self-describing — like a real
  brokerage routing prefix.
- **Multi-market**: each account is opened against a `market` (`us` / `cn` / `hk`),
  which sets the base currency (USD / CNY / HKD) and the exchange timezone.
- **Query by id**: any user or agent can pull full status from just the account id.
- **Trading history by step**: every closed trading day is appended to the account's
  history as one record (opening/closing equity, day P&L, the day's fills, positions).
- **Day-gating / freeze**: trading is allowed while `ACTIVE`. Calling **end_day**
  freezes the account (`FROZEN`) and records the day; trades are rejected until the
  agent calls **next_day**, which advances the simulated calendar to the next weekday
  and re-opens the book.

### Terminal UI

A dependency-free single-page UI ships with the server (served same-origin, no build):

```
open  http://127.0.0.1:19380/        # redirects to /ui/
```

It supports **two themes** (toggle, top-right; preference persists):

- **Modern** — dark glassy trading terminal.
- **Windows 98** — classic silver chrome, beveled windows, navy title bars.

From the UI you can allocate an account, query status by id, place buy/sell tickets,
end the day (freeze), advance to the next day, and browse the step-by-step history.

### Broker API

```bash
# Allocate a US account → returns a 10-digit account_id
curl -X POST http://127.0.0.1:19380/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{"market": "us", "initial_cash": 100000, "open_date": "2024-01-02"}'

# Query status by id
curl http://127.0.0.1:19380/v1/accounts/1840293756/status

# Trade (immediate fill at supplied price; only while ACTIVE)
curl -X POST http://127.0.0.1:19380/v1/accounts/1840293756/trade \
  -H 'Content-Type: application/json' \
  -d '{"symbol": "AAPL", "side": "BUY", "qty": 100, "price": 187.4}'

# End the day (freeze) → records a history step
curl -X POST http://127.0.0.1:19380/v1/accounts/1840293756/end_day

# Next day (unfreeze + advance calendar)
curl -X POST http://127.0.0.1:19380/v1/accounts/1840293756/next_day

# Step-by-step trading history
curl http://127.0.0.1:19380/v1/accounts/1840293756/history
```

Python client / MCP equivalents: `pmb.create_account(market=...)`, `pmb.get_status`,
`pmb.trade` / `broker_buy` / `broker_sell`, `pmb.end_day`, `pmb.next_day`,
`pmb.get_history`; MCP tools `pmb_create_account`, `pmb_get_status`, `pmb_trade`,
`pmb_end_day`, `pmb_next_day`, `pmb_get_history`.

---

## API Overview

**Base URL**: `http://127.0.0.1:19380/v1`

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/accounts` | POST | Allocate account (`market`, initial cash, open_date) → 10-digit id |
| `/accounts/{id}` | GET | Account snapshot (live session snapshot if attached, else broker book) |
| `/accounts/{id}/status` | GET | Canonical broker status (balances, P&L, day-gate state) |
| `/accounts/{id}/trade` | POST | Immediate paper fill (ACTIVE only) |
| `/accounts/{id}/end_day` | POST | Close trading day → freeze + record history step |
| `/accounts/{id}/next_day` | POST | Unfreeze + advance to next trading day |
| `/accounts/{id}/history` | GET | Step-by-step trading history (one record per day) |
| `/accounts/{id}/close` | POST | Permanently close the account |
| `/sessions` | POST | Create replay session (prefetches data) |
| `/sessions/{id}/step` | POST | Advance clock, return events |
| `/sessions/{id}/summary` | GET | Session metrics (return, drawdown, fees) |
| `/orders` | POST | Place order (idempotent via client_order_id) |
| `/orders/{id}/cancel` | POST | Cancel order |
| `/ui/` | GET | Broker Terminal UI (modern + Windows 98 themes) |

See full API spec in the [original design doc](../../.claude/plans/cozy-nibbling-wombat.md).

---

## Project Structure

```
pmb/
├── main.py                      # FastAPI app entry
├── config.py                    # Settings (ports, UPQ URL)
├── requirements.txt
│
├── models/                      # Pydantic models (no logic)
│   ├── enums.py                 # OrderSide, OrderType, OrderStatus, etc.
│   ├── instrument.py            # STOCK/OPTION instruments, OPRA helpers
│   ├── account.py               # Account, MarginConfig, AccountState
│   ├── session.py               # Session, ClockState, SessionSummary
│   ├── order.py                 # Order, OrderRequest
│   ├── trade.py                 # Trade (fill record)
│   ├── position.py              # Position
│   ├── event.py                 # Event payloads (6 event types)
│   └── market.py                # StockBar, OptionBar
│
├── domain/                      # Pure business logic (no I/O)
│   ├── session_clock.py         # Time management, step increments
│   ├── market_data_cache.py     # Prefetched bars, zero I/O during step
│   ├── order_manager.py         # Order state machine, idempotency
│   ├── execution_engine.py      # Match orders vs bars, fill logic
│   ├── margin_engine.py         # IM/MM calculation, margin calls
│   ├── ledger.py                # Cash, positions, P&L, avg cost
│   └── history_store.py         # Event/order/trade/snapshot log
│
├── clients/
│   └── upq_client.py            # Async UPQ HTTP client
│
├── services/                    # Orchestration (thin layer)
│   ├── account_service.py       # Account CRUD
│   ├── session_service.py       # Session lifecycle + step loop
│   ├── order_service.py         # Order placement/cancel/modify
│   └── history_service.py       # Query/export history
│
├── routes/                      # FastAPI routes (thin handlers)
│   ├── health.py
│   ├── accounts.py
│   ├── sessions.py
│   ├── orders.py
│   └── market.py
│
├── demos/                       # Strategy examples
│   ├── README.md                # Demo documentation
│   ├── result_saver.py          # Utility to save results
│   ├── daily_buy_close.py       # Daily accumulation strategy
│   ├── intraday_5min_signal.py  # Mean reversion (5-min signal)
│   ├── covered_call.py          # Option covered call
│   └── run_all.py               # Run all demos in sequence
│
└── results/                     # Demo outputs (gitignored)
    └── {strategy}_{timestamp}/
        ├── summary.json
        ├── holdings.json/csv
        ├── operations.json
        ├── orders.csv
        ├── trades.csv
        ├── equity_curve.json/csv
        └── report.txt
```

---

## Usage Examples

### 1. Create Account

```bash
curl -X POST http://127.0.0.1:19380/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{
    "account_type": "MARGIN",
    "initial_cash": 100000.0,
    "start_date": "2025-01-06"
  }'
```

### 2. Create Session

```bash
curl -X POST http://127.0.0.1:19380/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{
    "account_id": "acct_abc123",
    "frequency": "1m",
    "start_ts": "2025-01-06T09:30:00",
    "end_ts": "2025-01-06T16:00:00",
    "universe": {"stocks": ["AAPL"]},
    "reproducibility": {"seed": 42}
  }'
```

### 3. Step Simulation

```bash
curl -X POST http://127.0.0.1:19380/v1/sessions/sess_xyz/step \
  -H 'Content-Type: application/json' \
  -d '{"step": 1}'
```

Returns:
```json
{
  "ok": true,
  "clock": {
    "current_ts": "2025-01-06T09:31:00-05:00",
    "status": "RUNNING"
  },
  "events": [
    {"type": "MARKET_TICK", "payload": {...}},
    {"type": "ACCOUNT_SNAPSHOT", "payload": {...}}
  ]
}
```

### 4. Place Order

```bash
curl -X POST http://127.0.0.1:19380/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "sess_xyz",
    "account_id": "acct_abc123",
    "client_order_id": "my_buy_1",
    "order": {
      "instrument": {"type": "STOCK", "symbol": "AAPL"},
      "side": "BUY",
      "order_type": "MARKET",
      "qty": 10,
      "time_in_force": "DAY"
    }
  }'
```

### 5. Get Summary

```bash
curl http://127.0.0.1:19380/v1/sessions/sess_xyz/summary
```

Returns:
```json
{
  "final_equity": 101234.5,
  "total_return": 0.012345,
  "max_drawdown": 0.0231,
  "fees_paid": 12.34,
  "num_orders": 120,
  "num_trades": 98
}
```

---

## Demos

Three complete strategy examples under `demos/`:

1. **Daily Buy-at-Close** ([daily_buy_close.py](demos/daily_buy_close.py))
   - Buy 10 shares AAPL every day at close for one month
   - Demonstrates daily frequency + accumulation

2. **Intraday 5-Min Mean Reversion** ([intraday_5min_signal.py](demos/intraday_5min_signal.py))
   - Every 5 minutes: if price down → buy, if price up → sell
   - Demonstrates minute frequency + signal-based trading

3. **Covered Call** ([covered_call.py](demos/covered_call.py))
   - Buy 100 NVDA shares + sell 1 OTM call
   - Demonstrates option trading + margin

Each demo saves detailed results to `results/` folder (holdings, operations, equity curve).

See [demos/README.md](demos/README.md) for full documentation.

---

## Configuration

Edit [config.py](config.py) or set environment variables:

```bash
export PMB_HOST=127.0.0.1
export PMB_PORT=19380
export PMB_UPQ_BASE_URL=http://127.0.0.1:19350
export PMB_LOG_LEVEL=INFO
```

---

## Development

### Run Server

```bash
python main.py
# or with reload:
uvicorn main:app --host 127.0.0.1 --port 19380 --reload
```

### Run Tests

```bash
# Import check
python -c "from main import app; print('OK')"

# Manual API test
curl http://127.0.0.1:19380/v1/health
```

---

## Key Design Decisions

| Aspect | Choice | Rationale |
|---|---|---|
| **Web Framework** | FastAPI | Async, Pydantic validation, auto OpenAPI docs |
| **State Storage** | In-memory | Fast, deterministic, no DB overhead for ephemeral sessions |
| **Time Model** | Step-driven | Agent controls time progression (no wall-clock race conditions) |
| **Data Source** | UPQ prefetch | Fetch all bars at session creation (zero I/O during stepping) |
| **Order Idempotency** | client_order_id | Replay-safe, prevents duplicate submissions |
| **Event Order** | Fixed sequence | MARKET_TICK → ORDER → TRADE → SNAPSHOT → RISK (predictable) |

---

## Limitations (v0.1)

- No database persistence (sessions lost on server restart)
- No portfolio optimization / rebalancing endpoints
- Options: simplified margin (no spread recognition)
- No real-time mode (step-driven only)
- No order modify endpoint yet (use cancel + new order)

---

## References

- [Plan Document](../../.claude/plans/cozy-nibbling-wombat.md) - Full implementation plan
- [UPQ API Docs](../upq/docs/api-usage.md) - Market data service API
- [Demo Guide](demos/README.md) - Strategy examples + result analysis

---

## License

Internal tool for qfinzero project.

---

<a id="中文文档"></a>

# 中文文档

# Paper Money Broker (PMB)

一个以步进（step）驱动的模拟交易券商，用于回测 AI 交易 agent。支持股票和期权，具备完整的保证金核算、确定性重放以及全面的事件流。

---

## 快速开始

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the server (requires UPQ on port 19350)
python main.py

# 3. Run demos
python demos/daily_buy_close.py
```

服务将监听 **http://127.0.0.1:19380**

---

## 架构

PMB 是一个**基于 FastAPI 的模拟券商**，为确定性回测而设计，遵循以下原则：

- **步进驱动**：时间通过 `POST /sessions/{id}/step` 推进（不依赖真实时钟）
- **内存状态**：会话是短暂的重放回合（快速、无数据库开销）
- **事件溯源**：每一步都返回带类型的事件（MARKET_TICK、ORDER_EVENT、TRADE_EVENT 等）
- **保证金感知**：完整的初始/维持保证金追踪与追加保证金（margin call）
- **幂等下单**：`client_order_id` 防止重复提交

---

## 功能特性

### 核心能力

- **资产**：股票 + 期权（OPRA 合约）
- **订单类型**：MARKET、LIMIT、STOP、STOP_LIMIT
- **订单有效期（Time-in-Force）**：DAY、GTC、GTD
- **保证金**：初始/维持保证金、购买力、追加保证金
- **成交执行**：可配置的滑点、佣金模型、部分成交
- **历史**：完整的订单/成交/净值曲线导出（JSON/CSV）

### 交易频率

- **分钟（1m）**：使用分钟 K 线的日内策略
- **日线（1d）**：使用日线 K 线的多日策略

### 数据源

集成 **UPQ**（Unified Price Query，统一价格查询）服务：
- REST API 位于 http://127.0.0.1:19350
- 股票：分钟/日线 OHLCV K 线
- 期权：带 OPRA ID 的合约数据
- 参见：[infra/upq/docs/api-usage.md](../upq/docs/api-usage.md)

---

## 券商账户（按日门控）+ 终端 UI

在重放引擎之上，PMB 暴露了一个**自包含的券商账户**，专为 AI agent 直接驱动而设计——无需回测会话。

- 每个账户分配一个**唯一的 10 位账户 id**。首位数字编码了市场（`1`→美股，`6`→A 股，`3`→港股），因此该号码具有自描述性——就像真实券商的路由前缀。
- **多市场**：每个账户针对某个 `market`（`us` / `cn` / `hk`）开立，由此确定基础货币（USD / CNY / HKD）和交易所时区。
- **按 id 查询**：任何用户或 agent 都可以仅凭账户 id 拉取完整状态。
- **按步记录的交易历史**：每个已收盘的交易日会作为一条记录追加到账户历史中（开盘/收盘净值、当日盈亏、当日成交、持仓）。
- **按日门控 / 冻结**：账户处于 `ACTIVE` 时允许交易。调用 **end_day** 会冻结账户（`FROZEN`）并记录当天；在 agent 调用 **next_day** 之前交易会被拒绝，**next_day** 会将模拟日历推进到下一个工作日并重新开盘。

### 终端 UI

服务器随附一个无依赖的单页 UI（同源提供，无需构建）：

```
open  http://127.0.0.1:19380/        # redirects to /ui/
```

它支持**两种主题**（右上角切换，偏好会持久保存）：

- **Modern** —— 深色玻璃质感交易终端。
- **Windows 98** —— 经典银色边框、斜面窗口、藏青色标题栏。

在 UI 中你可以分配账户、按 id 查询状态、下达买入/卖出委托、结束当天（冻结）、推进到下一天，以及浏览逐步的历史记录。

### 券商 API

```bash
# Allocate a US account → returns a 10-digit account_id
curl -X POST http://127.0.0.1:19380/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{"market": "us", "initial_cash": 100000, "open_date": "2024-01-02"}'

# Query status by id
curl http://127.0.0.1:19380/v1/accounts/1840293756/status

# Trade (immediate fill at supplied price; only while ACTIVE)
curl -X POST http://127.0.0.1:19380/v1/accounts/1840293756/trade \
  -H 'Content-Type: application/json' \
  -d '{"symbol": "AAPL", "side": "BUY", "qty": 100, "price": 187.4}'

# End the day (freeze) → records a history step
curl -X POST http://127.0.0.1:19380/v1/accounts/1840293756/end_day

# Next day (unfreeze + advance calendar)
curl -X POST http://127.0.0.1:19380/v1/accounts/1840293756/next_day

# Step-by-step trading history
curl http://127.0.0.1:19380/v1/accounts/1840293756/history
```

Python 客户端 / MCP 等价形式：`pmb.create_account(market=...)`、`pmb.get_status`、`pmb.trade` / `broker_buy` / `broker_sell`、`pmb.end_day`、`pmb.next_day`、`pmb.get_history`；MCP 工具 `pmb_create_account`、`pmb_get_status`、`pmb_trade`、`pmb_end_day`、`pmb_next_day`、`pmb_get_history`。

---

## API 概览

**Base URL**：`http://127.0.0.1:19380/v1`

| Endpoint | Method | 说明 |
|---|---|---|
| `/health` | GET | 健康检查 |
| `/accounts` | POST | 分配账户（`market`、初始资金、open_date）→ 10 位 id |
| `/accounts/{id}` | GET | 账户快照（若已附加实时会话则为会话快照，否则为券商账本） |
| `/accounts/{id}/status` | GET | 规范化券商状态（余额、盈亏、按日门控状态） |
| `/accounts/{id}/trade` | POST | 立即模拟成交（仅限 ACTIVE） |
| `/accounts/{id}/end_day` | POST | 结束交易日 → 冻结 + 记录历史步 |
| `/accounts/{id}/next_day` | POST | 解冻 + 推进到下一个交易日 |
| `/accounts/{id}/history` | GET | 逐步交易历史（每天一条记录） |
| `/accounts/{id}/close` | POST | 永久关闭账户 |
| `/sessions` | POST | 创建重放会话（预取数据） |
| `/sessions/{id}/step` | POST | 推进时钟，返回事件 |
| `/sessions/{id}/summary` | GET | 会话指标（收益、回撤、费用） |
| `/orders` | POST | 下单（通过 client_order_id 幂等） |
| `/orders/{id}/cancel` | POST | 取消订单 |
| `/ui/` | GET | 券商终端 UI（modern + Windows 98 主题） |

完整 API 规范参见[原始设计文档](../../.claude/plans/cozy-nibbling-wombat.md)。

---

## 项目结构

```
pmb/
├── main.py                      # FastAPI app entry
├── config.py                    # Settings (ports, UPQ URL)
├── requirements.txt
│
├── models/                      # Pydantic models (no logic)
│   ├── enums.py                 # OrderSide, OrderType, OrderStatus, etc.
│   ├── instrument.py            # STOCK/OPTION instruments, OPRA helpers
│   ├── account.py               # Account, MarginConfig, AccountState
│   ├── session.py               # Session, ClockState, SessionSummary
│   ├── order.py                 # Order, OrderRequest
│   ├── trade.py                 # Trade (fill record)
│   ├── position.py              # Position
│   ├── event.py                 # Event payloads (6 event types)
│   └── market.py                # StockBar, OptionBar
│
├── domain/                      # Pure business logic (no I/O)
│   ├── session_clock.py         # Time management, step increments
│   ├── market_data_cache.py     # Prefetched bars, zero I/O during step
│   ├── order_manager.py         # Order state machine, idempotency
│   ├── execution_engine.py      # Match orders vs bars, fill logic
│   ├── margin_engine.py         # IM/MM calculation, margin calls
│   ├── ledger.py                # Cash, positions, P&L, avg cost
│   └── history_store.py         # Event/order/trade/snapshot log
│
├── clients/
│   └── upq_client.py            # Async UPQ HTTP client
│
├── services/                    # Orchestration (thin layer)
│   ├── account_service.py       # Account CRUD
│   ├── session_service.py       # Session lifecycle + step loop
│   ├── order_service.py         # Order placement/cancel/modify
│   └── history_service.py       # Query/export history
│
├── routes/                      # FastAPI routes (thin handlers)
│   ├── health.py
│   ├── accounts.py
│   ├── sessions.py
│   ├── orders.py
│   └── market.py
│
├── demos/                       # Strategy examples
│   ├── README.md                # Demo documentation
│   ├── result_saver.py          # Utility to save results
│   ├── daily_buy_close.py       # Daily accumulation strategy
│   ├── intraday_5min_signal.py  # Mean reversion (5-min signal)
│   ├── covered_call.py          # Option covered call
│   └── run_all.py               # Run all demos in sequence
│
└── results/                     # Demo outputs (gitignored)
    └── {strategy}_{timestamp}/
        ├── summary.json
        ├── holdings.json/csv
        ├── operations.json
        ├── orders.csv
        ├── trades.csv
        ├── equity_curve.json/csv
        └── report.txt
```

---

## 使用示例

### 1. 创建账户

```bash
curl -X POST http://127.0.0.1:19380/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{
    "account_type": "MARGIN",
    "initial_cash": 100000.0,
    "start_date": "2025-01-06"
  }'
```

### 2. 创建会话

```bash
curl -X POST http://127.0.0.1:19380/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{
    "account_id": "acct_abc123",
    "frequency": "1m",
    "start_ts": "2025-01-06T09:30:00",
    "end_ts": "2025-01-06T16:00:00",
    "universe": {"stocks": ["AAPL"]},
    "reproducibility": {"seed": 42}
  }'
```

### 3. 步进模拟

```bash
curl -X POST http://127.0.0.1:19380/v1/sessions/sess_xyz/step \
  -H 'Content-Type: application/json' \
  -d '{"step": 1}'
```

返回：
```json
{
  "ok": true,
  "clock": {
    "current_ts": "2025-01-06T09:31:00-05:00",
    "status": "RUNNING"
  },
  "events": [
    {"type": "MARKET_TICK", "payload": {...}},
    {"type": "ACCOUNT_SNAPSHOT", "payload": {...}}
  ]
}
```

### 4. 下单

```bash
curl -X POST http://127.0.0.1:19380/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "sess_xyz",
    "account_id": "acct_abc123",
    "client_order_id": "my_buy_1",
    "order": {
      "instrument": {"type": "STOCK", "symbol": "AAPL"},
      "side": "BUY",
      "order_type": "MARKET",
      "qty": 10,
      "time_in_force": "DAY"
    }
  }'
```

### 5. 获取汇总

```bash
curl http://127.0.0.1:19380/v1/sessions/sess_xyz/summary
```

返回：
```json
{
  "final_equity": 101234.5,
  "total_return": 0.012345,
  "max_drawdown": 0.0231,
  "fees_paid": 12.34,
  "num_orders": 120,
  "num_trades": 98
}
```

---

## 演示

`demos/` 下有三个完整的策略示例：

1. **Daily Buy-at-Close（每日收盘买入）**（[daily_buy_close.py](demos/daily_buy_close.py)）
   - 一个月内每天在收盘时买入 10 股 AAPL
   - 演示日线频率 + 累积建仓

2. **Intraday 5-Min Mean Reversion（日内 5 分钟均值回归）**（[intraday_5min_signal.py](demos/intraday_5min_signal.py)）
   - 每 5 分钟：价格下跌则买入，价格上涨则卖出
   - 演示分钟频率 + 基于信号的交易

3. **Covered Call（备兑看涨）**（[covered_call.py](demos/covered_call.py)）
   - 买入 100 股 NVDA + 卖出 1 张 OTM 看涨期权
   - 演示期权交易 + 保证金

每个演示会将详细结果保存到 `results/` 文件夹（持仓、操作、净值曲线）。

完整文档参见 [demos/README.md](demos/README.md)。

---

## 配置

编辑 [config.py](config.py) 或设置环境变量：

```bash
export PMB_HOST=127.0.0.1
export PMB_PORT=19380
export PMB_UPQ_BASE_URL=http://127.0.0.1:19350
export PMB_LOG_LEVEL=INFO
```

---

## 开发

### 运行服务

```bash
python main.py
# or with reload:
uvicorn main:app --host 127.0.0.1 --port 19380 --reload
```

### 运行测试

```bash
# Import check
python -c "from main import app; print('OK')"

# Manual API test
curl http://127.0.0.1:19380/v1/health
```

---

## 关键设计决策

| 方面 | 选择 | 理由 |
|---|---|---|
| **Web 框架** | FastAPI | 异步、Pydantic 校验、自动生成 OpenAPI 文档 |
| **状态存储** | 内存 | 快速、确定性，短暂会话无数据库开销 |
| **时间模型** | 步进驱动 | Agent 控制时间推进（无真实时钟竞态） |
| **数据源** | UPQ 预取 | 在会话创建时获取全部 K 线（步进期间零 I/O） |
| **订单幂等性** | client_order_id | 重放安全，防止重复提交 |
| **事件顺序** | 固定序列 | MARKET_TICK → ORDER → TRADE → SNAPSHOT → RISK（可预测） |

---

## 局限（v0.1）

- 无数据库持久化（服务器重启后会话丢失）
- 无组合优化 / 再平衡端点
- 期权：简化保证金（不识别价差组合）
- 无实时模式（仅步进驱动）
- 尚无订单修改端点（请使用取消 + 新建订单）

---

## 参考

- [计划文档](../../.claude/plans/cozy-nibbling-wombat.md) - 完整实现计划
- [UPQ API 文档](../upq/docs/api-usage.md) - 行情数据服务 API
- [演示指南](demos/README.md) - 策略示例 + 结果分析

---

## 许可证

qfinzero 项目内部工具。
