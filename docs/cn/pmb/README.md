> English: [../../en/pmb/README.md](../../en/pmb/README.md)

# PMB — Paper Money Broker

一个基于步进驱动的模拟交易经纪商，用于回测 AI 交易代理。支持股票和期权，具备完整的保证金核算、确定性回放以及全面的事件流。

> 🖥️ **交易终端与期权/策略指南：** [broker-terminal.md](broker-terminal.md) — 独立的 `/broker` 站点（自选、K 线、期权链、时间旅行）以及对应的 agent REST/MCP 接口。

## Server

- **语言**: Python (FastAPI)
- **默认端口**: 19380
- **入口点**: `infra/pmb/main.py`
- **依赖**: 需要运行 UPQ 服务以提供市场数据

```bash
cd infra/pmb
pip install -r requirements.txt
python main.py
# http://127.0.0.1:19380
```

## API 概览

**Base URL**: `http://127.0.0.1:19380/v1`

| Endpoint | Method | 描述 |
|----------|--------|-------------|
| `/health` | GET | 健康检查 |
| `/accounts` | POST | 创建账户，并配置初始现金 + 保证金 |
| `/accounts/{id}` | GET | 获取账户快照（现金、持仓、权益） |
| `/sessions` | POST | 创建回放会话（从 UPQ 预取市场数据） |
| `/sessions/{id}/step` | POST | 推进模拟时钟，返回事件 |
| `/sessions/{id}/summary` | GET | 会话指标（收益、回撤、费用） |
| `/orders` | POST | 下单（通过 `client_order_id` 保证幂等） |
| `/orders/{id}/cancel` | POST | 取消一个挂单 |

## 核心概念

### 步进驱动的模拟

时间仅通过 `POST /sessions/{id}/step` 推进。不依赖真实挂钟时间——由代理控制时间进程。每一步按固定顺序返回带类型的事件：

```
MARKET_TICK → ORDER_EVENT → TRADE_EVENT → ACCOUNT_SNAPSHOT → RISK_EVENT
```

### 支持的资产

- **股票**: 分钟/日级别的 OHLCV K 线
- **期权**: 带完整期权链数据的 OPRA 合约

### 订单类型

- `MARKET`、`LIMIT`、`STOP`、`STOP_LIMIT`
- 有效期（Time-in-force）: `DAY`、`GTC`、`GTD`
- 通过 `client_order_id` 保证幂等

### 保证金核算

- 初始保证金 / 维持保证金跟踪
- 购买力计算
- 追加保证金（Margin call）事件

### 交易频率

- `1m` — 使用分钟 K 线的日内策略
- `1d` — 使用日 K 线的多日策略

## 快速示例

```bash
# Create account
curl -X POST http://127.0.0.1:19380/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{"account_type": "MARGIN", "initial_cash": 100000.0, "start_date": "2025-01-06"}'

# Create session
curl -X POST http://127.0.0.1:19380/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{
    "account_id": "<account_id>",
    "frequency": "1d",
    "start_ts": "2025-01-06",
    "end_ts": "2025-02-06",
    "universe": {"stocks": ["AAPL"]}
  }'

# Step simulation
curl -X POST http://127.0.0.1:19380/v1/sessions/<session_id>/step \
  -H 'Content-Type: application/json' \
  -d '{"step": 1}'

# Place order
curl -X POST http://127.0.0.1:19380/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "<session_id>",
    "account_id": "<account_id>",
    "client_order_id": "buy_1",
    "order": {
      "instrument": {"type": "STOCK", "symbol": "AAPL"},
      "side": "BUY", "order_type": "MARKET", "qty": 10, "time_in_force": "DAY"
    }
  }'
```

## Python 客户端

PMB 客户端库（`clients/pmb/`）封装了 REST API，以便在 Python 中简洁使用。

### 安装

无需额外依赖——使用 `requests`（与服务端的依赖相同）。

### 基本用法

```python
from qfinzero.clients.pmb import PMBClient

with PMBClient() as pmb:
    # Create account and session
    acct = pmb.create_account(initial_cash=50000.0, start_date="2025-01-06")
    sess = pmb.create_session(
        account_id=acct["account_id"],
        frequency="1d",
        start_ts="2025-01-06",
        end_ts="2025-01-31",
        universe={"stocks": ["AAPL"]},
    )

    # Step through simulation
    while True:
        result = pmb.step(sess["session_id"])
        if not result.is_running:
            break

        price = result.get_stock_price("AAPL")
        snap = result.get_snapshot()

        # Place orders
        pmb.buy(sess["session_id"], acct["account_id"], "AAPL", 10)

    # Get results
    summary = pmb.get_summary(sess["session_id"])
    print(f"Return: {summary['total_return']*100:+.2f}%")
```

### 客户端 API

| Method | 描述 |
|--------|-------------|
| `create_account(initial_cash, ...)` | 创建交易账户 |
| `get_account(account_id)` | 获取账户状态 |
| `get_positions(account_id)` | 获取当前持仓 |
| `create_session(account_id, frequency, start_ts, end_ts, universe, ...)` | 创建回放会话 |
| `step(session_id, n=1)` | 推进时钟，返回 `StepResult` |
| `buy(session_id, account_id, symbol, qty, ...)` | 买入股票 |
| `sell(session_id, account_id, symbol, qty, ...)` | 卖出股票 |
| `buy_option(session_id, account_id, contract, qty, ...)` | 买入期权 |
| `sell_option(session_id, account_id, contract, qty, ...)` | 卖出期权 |
| `cancel_order(order_id, session_id, account_id)` | 取消订单 |
| `get_summary(session_id)` | 获取会话绩效指标 |
| `export(session_id, fmt="json")` | 导出订单、成交、权益曲线 |
| `get_market(session_id)` | 获取当前市场快照 |

### StepResult

`step()` 返回一个带便捷访问器的 `StepResult`：

```python
result = pmb.step(session_id)

result.is_running          # bool: session still active
result.current_ts          # str: current timestamp
result.get_stock_price("AAPL")  # float: close price
result.get_stock_bar("AAPL")    # dict: full OHLCV bar
result.get_market_tick()   # dict: {"stocks": [...], "options": [...]}
result.get_snapshot()      # dict: account snapshot (cash, equity, positions)
```

### 错误处理

```python
from qfinzero.clients.pmb import PMBClient, PMBError

try:
    pmb.buy(session_id, account_id, "AAPL", 10)
except PMBError as e:
    print(f"Error: {e}, status={e.status_code}")
```

## 配置

| Environment Variable | 默认值 | 描述 |
|---------------------|---------|-------------|
| `PMB_HOST` | 127.0.0.1 | 绑定主机 |
| `PMB_PORT` | 19380 | 绑定端口 |
| `PMB_UPQ_BASE_URL` | http://127.0.0.1:19350 | UPQ 服务 URL |
| `PMB_LOG_LEVEL` | INFO | 日志级别 |

## 参考资料

- [OpenAPI Specification](openapi.yaml)
- [Server Implementation](../../infra/pmb/)
- [Client Library](../../clients/pmb/)
- [Demos](../../demos/pmb/)
