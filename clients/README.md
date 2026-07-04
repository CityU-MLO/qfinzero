> **English** (below) · [中文](#中文文档) (在下方)

# QFinZero Clients

Python client libraries for each QFinZero service. Each client wraps the service's REST API and provides a clean interface for agent integration.

## Structure

```
clients/
├── esp/     # ESP client — news and event queries
├── pmb/     # PMB client — paper trading session management
└── upq/     # UPQ client — price data queries
```

## Implemented Clients

| Client | Import | Default Port | Agent Guide |
|--------|--------|-------------|-------------|
| PMB | `from qfinzero.clients.pmb import PMBClient` | 19380 | [docs/pmb/agent-guide.md](../docs/pmb/agent-guide.md) |
| ESP | `from qfinzero.clients.esp import ESPClient` | 19330 | [docs/esp/agent-guide.md](../docs/esp/agent-guide.md) |
| UPQ | `from qfinzero.clients.upq import UPQClient` | 19350 | [docs/upq/agent-guide.md](../docs/upq/agent-guide.md) |

### Quick Start

```python
from qfinzero.clients.pmb import PMBClient, StepResult, PMBError
from qfinzero.clients.esp import ESPClient, ESPError
from qfinzero.clients.upq import UPQClient, UPQError

# All clients support context manager
with PMBClient() as pmb, ESPClient() as esp, UPQClient() as upq:
    # Query stock prices via UPQ
    bars = upq.stock_daily(["AAPL"], "2025-01-06", "2025-01-31")

    # Fetch upcoming events via ESP
    events = esp.query_events(mode="upcoming", horizon_minutes=120)

    # Run a paper trading simulation via PMB
    acct = pmb.create_account(initial_cash=50000.0, start_date="2025-01-06")
    sess = pmb.create_session(
        account_id=acct["account_id"],
        frequency="1d",
        start_ts="2025-01-06",
        end_ts="2025-01-31",
        universe={"stocks": ["AAPL"]},
    )
```

## Agent Integration

The agent guide documents describe each client method as a callable tool with exact parameters, return types, and JSON response schemas. Use these when building agent skills:

- **[PMB Agent Guide](../docs/pmb/agent-guide.md)** — 16 tools for paper trading (account, session, orders, market)
- **[ESP Agent Guide](../docs/esp/agent-guide.md)** — 6 tools for news, earnings, and macro events
- **[UPQ Agent Guide](../docs/upq/agent-guide.md)** — 6 tools + 2 utilities for price data queries

---

<a id="中文文档"></a>

# 中文文档

# QFinZero Clients

面向每个 QFinZero 服务的 Python 客户端库。每个客户端封装了该服务的 REST API，并为 agent 集成提供简洁的接口。

## 结构

```
clients/
├── esp/     # ESP client — news and event queries
├── pmb/     # PMB client — paper trading session management
└── upq/     # UPQ client — price data queries
```

## 已实现的客户端

| 客户端 | 导入 | 默认端口 | Agent 指南 |
|--------|--------|-------------|-------------|
| PMB | `from qfinzero.clients.pmb import PMBClient` | 19380 | [docs/pmb/agent-guide.md](../docs/pmb/agent-guide.md) |
| ESP | `from qfinzero.clients.esp import ESPClient` | 19330 | [docs/esp/agent-guide.md](../docs/esp/agent-guide.md) |
| UPQ | `from qfinzero.clients.upq import UPQClient` | 19350 | [docs/upq/agent-guide.md](../docs/upq/agent-guide.md) |

### 快速开始

```python
from qfinzero.clients.pmb import PMBClient, StepResult, PMBError
from qfinzero.clients.esp import ESPClient, ESPError
from qfinzero.clients.upq import UPQClient, UPQError

# All clients support context manager
with PMBClient() as pmb, ESPClient() as esp, UPQClient() as upq:
    # Query stock prices via UPQ
    bars = upq.stock_daily(["AAPL"], "2025-01-06", "2025-01-31")

    # Fetch upcoming events via ESP
    events = esp.query_events(mode="upcoming", horizon_minutes=120)

    # Run a paper trading simulation via PMB
    acct = pmb.create_account(initial_cash=50000.0, start_date="2025-01-06")
    sess = pmb.create_session(
        account_id=acct["account_id"],
        frequency="1d",
        start_ts="2025-01-06",
        end_ts="2025-01-31",
        universe={"stocks": ["AAPL"]},
    )
```

## Agent 集成

Agent 指南文档将每个客户端方法描述为一个可调用的工具，包含确切的参数、返回类型以及 JSON 响应模式。在构建 agent 技能时可参考这些文档：

- **[PMB Agent Guide](../docs/pmb/agent-guide.md)** — 用于模拟交易的 16 个工具（账户、会话、订单、市场）
- **[ESP Agent Guide](../docs/esp/agent-guide.md)** — 用于新闻、财报和宏观事件的 6 个工具
- **[UPQ Agent Guide](../docs/upq/agent-guide.md)** — 用于价格数据查询的 6 个工具 + 2 个实用工具
