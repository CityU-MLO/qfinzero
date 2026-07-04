# QFinZero

> **English** (below) · [中文](#中文文档) (在下方)

**A Unified Trading Environment for LLM Agents**

QFinZero unifies price data, event/news retrieval, and brokerage simulation behind consistent, time-aligned APIs so LLM agents can query, reason, and trade in a coherent environment.

> Haochen Luo1*, Binh Minh An1, Ho Tin Ko2, Junjie Xu5, Pok Hin Tang1, Wang Chak Wong1, Yifan Li1, Yuan Gao1, Zhengzhao Lai4, Yuan Zhang3, Chen Liu1
>
> 1 City University of Hong Kong, 2 Yuen Long Merchants Association Secondary School, 3 Shanghai University of Finance and Economics, 4 University of Science and Technology of China, 5 The Chinese University of Hong Kong (Shenzhen)
>
> Correspondence: chester.hc.luo@my.cityu.edu.hk, zhang.yuan@sufe.edu.cn, chen.liu@cityu.edu.hk

## Abstract

Large language model (LLM) agents are increasingly applied to financial decision-making tasks that require interaction with external tools such as market data, news, and trade execution. Existing systems are fragmented across task-specific APIs, which introduces inconsistent schemas, brittle integration, and weak reproducibility. QFinZero addresses this gap with a unified trading environment that standardizes three core capabilities: multi-frequency market and derivatives data access (UPQ), structured news and event retrieval (ESP), and a stateful brokerage simulator with explicit order lifecycle management (PMB). All tools expose consistent JSON schemas and time-aligned interfaces, enabling agents to autonomously retrieve information, manage portfolio state, and execute trades within a coherent framework. By abstracting financial interaction into composable, agent-invokable primitives, QFinZero reduces engineering overhead and supports reproducible evaluation with deterministic replay and comprehensive logging.

## The unified server

QFinZero runs as **one server on a single public port** (`19777`). It fronts
everything:

| Path | Serves |
|------|--------|
| `/` | Web UI (dashboard) — **incl. its own `/api/*` backend** |
| `/svc/upq/*` | Market data (UPQ) — raw REST |
| `/svc/esp/*` | News & events (ESP) — raw REST |
| `/svc/pmb/*` | Paper broker (PMB) — raw REST |
| `/svc/playground/*` | Chat agent backend — raw REST |
| `/svc/data-admin/*` | Data protocol control plane — raw REST |
| `/mcp` | MCP server (streamable-HTTP) — LLM tools |
| `/health` | Hub + all children status |

`/api/*` is reserved for the web UI's backend-for-frontend (it maps to the
services with the UI's own path conventions); direct/raw service REST lives under
`/svc/*` so the two never collide.

```bash
./scripts/serve.sh                 # start everything on http://127.0.0.1:19777
# open http://127.0.0.1:19777           (web UI)
# curl http://127.0.0.1:19777/health    (hub + children)
# curl http://127.0.0.1:19777/api/upq/health
```

You launch one command and hit one port. Under the hood the hub **supervises**
the individual services on localhost (they're no longer exposed directly), and
mounts the **MCP** server in-process. Override the port with `QFZ_SERVER_PORT`.

### Architecture

```
        LLM Agent / User / MCP client
                     │
                     v
   ┌──────────────────────────────────────────┐
   │        qfinzero-server  :19777           │   one public port
   │  /  → Web UI      /mcp → MCP (in-proc)     │
   │  /api/* → reverse proxy ↓                 │
   └───┬─────┬─────┬─────┬─────┬───────────────┘
       │     │     │     │     │  (localhost children, supervised by the hub)
       v     v     v     v     v
     UPQ   ESP   PMB  playgr. data-admin      + Next.js dashboard
    (Rust)                                     (Node)
       ▲     │
       │     v
       │  MongoDB + SQLite
       └── PMB reads market data from UPQ
```

**Modes:** `QFZ_SUPERVISE=0` runs the hub as a pure gateway to services managed
elsewhere; `QFZ_SERVE_UI=0` skips the Next.js UI. The internal service ports
(193xx) still exist for standalone/debug use via `scripts/run_all.sh`.

### Core Components

**Unified Price Query (UPQ)** provides multi-resolution price data (minute and daily bars) for equities (US + CN A-shares), options (OPRA), and treasury yields through a single API. Agents query structured market states without handling vendor-specific formatting. Stock prices are stored raw/as-traded; pass `adjust=split` or `adjust=total` to apply split / split+dividend adjustment on read (default `none`).

**News Pushing Pipeline (ESP)** aggregates news articles (MongoDB), earnings calendars (Benzinga), and US economic events (NASDAQ) into a canonical event schema. Supports three query modes: upcoming events, recently occurred events, and arbitrary time windows. All times normalized to UTC.

**Paper Money Broker (PMB)** is a step-driven brokerage simulator supporting market/limit/stop orders, margin accounts, and explicit order lifecycle (pending, filled, canceled). Time advances only when the agent calls `step`, enabling deterministic replay.

### Service Dependencies

- **PMB -> UPQ**: PMB fetches market data from UPQ at session creation.
- **ESP -> MongoDB + SQLite**: ESP reads from three local data sources.
- **UPQ** is fully independent.

## Data Pipeline

UPQ is fed by a built-in, out-of-the-box pipeline (`qfz-data`) that manages two
raw market-data sources **in place** (never copied) and converts them into UPQ's
storage format:

| Vendor | Markets | Raw location (default) |
|--------|---------|------------------------|
| massive | US stocks, options (OPRA), treasury yields, corporate actions | `/data/massive_data` |
| tushare | CN A-shares (+ dividends) | `/data/tushare_data` |

Both sources are normalized into one storage root with a single unified
**corporate-actions** table. Splits use fractional ratios (e.g. CN 送转 "10转15"
→ 1.5; reverse splits supported), and each dividend carries a precomputed price
ratio so UPQ applies split / dividend adjustment on read without re-deriving it.

```bash
pip install -e ".[pipeline]"          # adds duckdb + pyarrow + polars

# Defaults live under the data root (QFZ_DATA_ROOT=/data/qfinzero); override if needed:
export QFZ_DATA_ROOT=/data/qfinzero    # STORAGE_ROOT defaults to $QFZ_DATA_ROOT/upq
export RAW_MASSIVE_DIR=/data/massive_data
export RAW_TUSHARE_DIR=/data/tushare_data

qfz-data status                       # what raw data exists + conversion state
qfz-data convert --market us --all    # US stocks + options + rates + corp actions
qfz-data convert --market cn --all    # CN A-shares + corp actions
qfz-data convert --all                # everything (incremental + idempotent)
qfz-data validate                     # row-count / schema checks on storage
```

The converter writes byte-compatible parquet (`stock_daily/`, `stock_minute/`,
`option_day/`, `option_minute/` partitioned by `trade_date=`; plus `rates/` and
`corporate_actions/`) that the UPQ service reads directly. Point the UPQ service
at the same `STORAGE_ROOT`.

### Data-admin — the operator control plane (CLI + Web)

Beyond convert, `qfz-data` manages vendor credentials, permission scans,
downloads, the update schedule, and data exploration — the "Integrated Data
Protocol" surface:

```bash
qfz-data config --set tushare.token=…      # masked, stored at $QFZ_DATA_ROOT/_state/qfz.config.json
qfz-data scan massive                       # list flat-files datasets your S3 key can read
qfz-data scan tushare                       # validate the CN token
qfz-data acquire us_prices                  # trigger the MASSIVE download script (dry-run by default; --run)
qfz-data schedule apply                     # install the cron cadence from the config
qfz-data explore --symbols stock_daily      # per-symbol coverage in a store
qfz-data setup-state                         # first-run wizard vs. status
```

The same surface is served by the **data-admin service** (`infra/data-admin`,
`:19340`) — config/scan, freshness sources, update/download **jobs with SSE log
streaming**, schedule, and explorer — and driven from the dashboard-web **Data**
tab (setup wizard, credentials + scan, pipeline manager, schedule, explorer).
Start it with the rest: `./scripts/run_all.sh` (or `./scripts/run_all.sh data-admin`).

### Data root

All QFinZero-owned data lives under a single root, `QFZ_DATA_ROOT` (default
`/data/qfinzero`):

```
/data/qfinzero/
├── upq/    UPQ price storage (STORAGE_ROOT) — built by `qfz-data convert`
├── esp/    ESP event databases (benzinga_earnings.sqlite3, nasdaq_econ_events.sqlite3)
└── raw/    symlinks to shared raw vendor data (massive, tushare) — read in place
```

## Installation

```bash
pip install -e .
```

This installs the `qfinzero` package with all client libraries:

```python
from qfinzero.clients.upq import UPQClient
from qfinzero.clients.esp import ESPClient
from qfinzero.clients.pmb import PMBClient
```

## Quick Start

Ports default to `19300` to `19390`. Override them with environment variables, or create a root `.env` from `.env.example` for local development overrides.

### Start All Services

```bash
./scripts/run_all.sh           # start all
./scripts/run_all.sh pmb esp   # start specific services
./scripts/status.sh            # check what's running
./scripts/stop_all.sh          # stop all
```

### Start Individually

```bash
# Dashboard Web (Next.js frontend)
cd infra/dashboard-web
pnpm install --no-frozen-lockfile
pnpm build
PORT=19300 \
PMB_BASE_URL=http://127.0.0.1:19380 \
ESP_BASE_URL=http://127.0.0.1:19330 \
UPQ_BASE_URL=http://127.0.0.1:19350 \
PLAYGROUND_SERVICE_URL=http://127.0.0.1:19390 \
pnpm start
# open http://127.0.0.1:19300

# UPQ (Rust — build first)
cd infra/upq
cargo build --release
STORAGE_ROOT=~/upq_storage cargo run -p upq-service
# curl http://127.0.0.1:19350/health

# ESP (Python)
cd infra/esp
pip install -r requirements.txt
python main.py
# curl http://127.0.0.1:19330/esp/health

# PMB (Python — requires UPQ running)
cd infra/pmb
pip install -r requirements.txt
python main.py
# curl http://127.0.0.1:19380/v1/health

# Playground (Python — expects PMB/ESP/UPQ running)
cd infra/playground
pip install -r requirements.txt
PLAYGROUND_PORT=19390 \
QFINZERO_PMB_URL=http://127.0.0.1:19380 \
QFINZERO_ESP_URL=http://127.0.0.1:19330 \
QFINZERO_UPQ_URL=http://127.0.0.1:19350 \
python main.py
# curl http://127.0.0.1:19390/health
```

### Start Monitoring Frontend (Dev Mode)

```bash
cd infra/dashboard-web
pnpm install --no-frozen-lockfile
pnpm dev
# open http://127.0.0.1:19400
```

### Use the Clients

```python
from qfinzero.clients.upq import UPQClient
from qfinzero.clients.esp import ESPClient
from qfinzero.clients.pmb import PMBClient

# Price data
with UPQClient() as upq:
    bars = upq.stock_daily(["AAPL", "NVDA"], "2025-01-06", "2025-01-31")

# News and events
with ESPClient() as esp:
    events = esp.query_events(mode="upcoming", horizon_minutes=120)
    earnings = esp.earnings_calendar(tickers=["AAPL"], start_date="2025-01-01", end_date="2025-03-31")
    triggers = esp.next_triggers(tickers=["SPY", "QQQ"], min_importance="high")

# Paper trading
with PMBClient() as pmb:
    acct = pmb.create_account(initial_cash=100000.0, start_date="2025-01-06")
    sess = pmb.create_session(
        account_id=acct["account_id"],
        frequency="1d", start_ts="2025-01-06", end_ts="2025-01-31",
        universe={"stocks": ["AAPL"]},
    )
    result = pmb.step(sess["session_id"])
    pmb.buy(sess["session_id"], acct["account_id"], "AAPL", 100)
```

## Project Structure

```
qfinzero/
├── qfinzero/                   # Python package
│   ├── __init__.py
│   └── config.py               # Global port/path configuration
├── clients/                    # Client libraries
│   ├── upq/                    #   UPQ Python client
│   ├── esp/                    #   ESP Python client
│   └── pmb/                    #   PMB Python client
├── infra/                      # Service implementations
│   ├── upq/                    #   UPQ server (Rust workspace)
│   ├── esp/                    #   ESP server (FastAPI)
│   ├── pmb/                    #   PMB server (FastAPI)
│   ├── playground/             #   Playground backend (FastAPI / LangGraph)
│   └── dashboard-web/          #   Next.js frontend
├── demos/                      # Usage examples
│   ├── upq/                    #   Price query demos
│   ├── esp/                    #   Event query demos
│   └── pmb/                    #   Paper trading demos
├── docs/                       # Service documentation
│   ├── upq/                    #   UPQ API docs + OpenAPI
│   ├── esp/                    #   ESP API docs + OpenAPI
│   └── pmb/                    #   PMB API docs + OpenAPI
├── qfinzero/pipeline/          # qfz-data pipeline (raw-source mgmt + UPQ conversion)
├── .env.example                # Example local overrides
├── scripts/                    # Service management
│   ├── run_all.sh
│   ├── stop_all.sh
│   └── status.sh
└── pyproject.toml

# Data lives OUTSIDE the repo under QFZ_DATA_ROOT (default /data/qfinzero):
/data/qfinzero/
├── upq/                        # UPQ price storage (parquet)
├── esp/                        # ESP databases (benzinga_earnings, nasdaq_econ_events)
└── raw/                        # symlinks to shared raw vendor data (massive, tushare)
```

## Configuration

Configuration follows a simple layered model:

1. Environment variables take highest priority.
2. Root `.env` is an optional local development override.
3. Code defaults fall back to the standard `19300` to `19390` port range.

Start by copying `.env.example` if you want local overrides:

```bash
cp .env.example .env
```

`qfinzero/config.py` reads the same environment variables so clients and services stay consistent.

| Service | Port | Env Override |
|---------|------|-------------|
| Dashboard Web | 19300 | `DASHBOARD_PORT` |
| PMB | 19380 | `PMB_PORT` |
| ESP | 19330 | `ESP_PORT` |
| UPQ | 19350 | `UPQ_PORT` (service reads `PORT`) |
| Playground | 19390 | `PLAYGROUND_PORT` |

Related service URL overrides:

- `PMB_BASE_URL`, `ESP_BASE_URL`, `UPQ_BASE_URL` for `dashboard-web`
- `PLAYGROUND_SERVICE_URL` for the web playground proxy
- `QFINZERO_PMB_URL`, `QFINZERO_ESP_URL`, `QFINZERO_UPQ_URL` for `playground`

Data paths (all default under `QFZ_DATA_ROOT`, default `/data/qfinzero`):

| Data | Default | Env Override |
|------|---------|-------------|
| Data root | `/data/qfinzero` | `QFZ_DATA_ROOT` |
| UPQ price storage | `$QFZ_DATA_ROOT/upq` | `STORAGE_ROOT` |
| ESP earnings DB | `$QFZ_DATA_ROOT/esp/benzinga_earnings.sqlite3` | `EARNINGS_DB` |
| ESP econ-events DB | `$QFZ_DATA_ROOT/esp/nasdaq_econ_events.sqlite3` | `ECON_EVENTS_DB` |
| Raw massive (shared) | `/data/massive_data` | `RAW_MASSIVE_DIR` |
| Raw tushare (shared) | `/data/tushare_data` | `RAW_TUSHARE_DIR` |

## Documentation

- [UPQ API Reference](docs/upq/README.md) | [Agent Guide](docs/upq/agent-guide.md) | [OpenAPI](docs/upq/openapi.yaml)
- [ESP API Reference](docs/esp/README.md) | [Agent Guide](docs/esp/agent-guide.md) | [OpenAPI](docs/esp/openapi.yaml)
- [PMB API Reference](docs/pmb/README.md) | [Agent Guide](docs/pmb/agent-guide.md) | [OpenAPI](docs/pmb/openapi.yaml)

## License

MIT License

---

<a id="中文文档"></a>

# 中文文档

# QFinZero

**面向 LLM 智能体的统一交易环境**

QFinZero 将价格数据、事件/新闻检索与券商模拟统一在一致的、时间对齐的 API 之下，使 LLM 智能体能够在一个连贯的环境中查询、推理与交易。

> Haochen Luo1*, Binh Minh An1, Ho Tin Ko2, Junjie Xu5, Pok Hin Tang1, Wang Chak Wong1, Yifan Li1, Yuan Gao1, Zhengzhao Lai4, Yuan Zhang3, Chen Liu1
>
> 1 香港城市大学, 2 元朗商会中学, 3 上海财经大学, 4 中国科学技术大学, 5 香港中文大学（深圳）
>
> 通讯作者: chester.hc.luo@my.cityu.edu.hk, zhang.yuan@sufe.edu.cn, chen.liu@cityu.edu.hk

## 摘要

大语言模型（LLM）智能体正越来越多地被应用于需要与外部工具交互的金融决策任务，例如市场数据、新闻与交易执行。现有系统在各类任务专用 API 之间高度割裂，导致 schema 不一致、集成脆弱以及可复现性差。QFinZero 通过一个统一交易环境来弥补这一空缺，将三项核心能力标准化：多频率市场与衍生品数据访问 (UPQ)、结构化新闻与事件检索 (ESP)，以及具备显式订单生命周期管理的有状态券商模拟器 (PMB)。所有工具都暴露一致的 JSON schema 与时间对齐的接口，使智能体能够在一个连贯的框架内自主检索信息、管理组合状态并执行交易。通过将金融交互抽象为可组合、可被智能体调用的原语，QFinZero 降低了工程开销，并借助确定性重放与全面日志记录支持可复现的评估。

## 统一服务器

QFinZero 作为**单一公开端口上的单一服务器**（`19777`）运行。它统一对外承载所有内容：

| 路径 | 提供内容 |
|------|--------|
| `/` | Web UI（仪表盘）—— **含其自有的 `/api/*` 后端** |
| `/svc/upq/*` | 市场数据 (UPQ) —— 原始 REST |
| `/svc/esp/*` | 新闻与事件 (ESP) —— 原始 REST |
| `/svc/pmb/*` | 模拟券商 (PMB) —— 原始 REST |
| `/svc/playground/*` | 聊天智能体后端 —— 原始 REST |
| `/svc/data-admin/*` | 数据协议控制平面 —— 原始 REST |
| `/mcp` | MCP 服务器（streamable-HTTP）—— LLM 工具 |
| `/health` | Hub 及所有子服务状态 |

`/api/*` 保留给 Web UI 的 backend-for-frontend（它按照 UI 自身的路径约定映射到各服务）；直连/原始服务 REST 位于 `/svc/*` 之下，因此两者永不冲突。

```bash
./scripts/serve.sh                 # start everything on http://127.0.0.1:19777
# open http://127.0.0.1:19777           (web UI)
# curl http://127.0.0.1:19777/health    (hub + children)
# curl http://127.0.0.1:19777/api/upq/health
```

你只需启动一条命令并访问一个端口。在底层，hub **监督**localhost 上的各个独立服务（它们不再被直接暴露），并在进程内挂载 **MCP** 服务器。使用 `QFZ_SERVER_PORT` 覆盖端口。

### 架构

```
        LLM Agent / User / MCP client
                     │
                     v
   ┌──────────────────────────────────────────┐
   │        qfinzero-server  :19777           │   one public port
   │  /  → Web UI      /mcp → MCP (in-proc)     │
   │  /api/* → reverse proxy ↓                 │
   └───┬─────┬─────┬─────┬─────┬───────────────┘
       │     │     │     │     │  (localhost children, supervised by the hub)
       v     v     v     v     v
     UPQ   ESP   PMB  playgr. data-admin      + Next.js dashboard
    (Rust)                                     (Node)
       ▲     │
       │     v
       │  MongoDB + SQLite
       └── PMB reads market data from UPQ
```

**运行模式：** `QFZ_SUPERVISE=0` 让 hub 作为纯网关，指向别处托管的服务；`QFZ_SERVE_UI=0` 跳过 Next.js UI。内部服务端口（193xx）仍然存在，可通过 `scripts/run_all.sh` 用于独立运行/调试。

### 核心组件

**统一价格查询 (UPQ)** 通过单一 API 提供多分辨率价格数据（分钟与日线），涵盖股票（美股 + 中国 A 股）、期权（OPRA）与国债收益率。智能体查询结构化的市场状态，无需处理供应商特定的格式。股票价格以原始/成交价存储；传入 `adjust=split` 或 `adjust=total` 可在读取时应用拆分 / 拆分+分红复权（默认 `none`）。

**新闻推送管道 (ESP)** 将新闻文章（MongoDB）、财报日历（Benzinga）与美国经济事件（NASDAQ）聚合为一个规范化的事件 schema。支持三种查询模式：即将发生的事件、近期已发生的事件，以及任意时间窗口。所有时间统一归一化为 UTC。

**模拟货币券商 (PMB)** 是一个步进驱动的券商模拟器，支持市价/限价/止损单、保证金账户以及显式的订单生命周期（pending、filled、canceled）。只有当智能体调用 `step` 时时间才推进，从而实现确定性重放。

### 服务依赖关系

- **PMB -> UPQ**：PMB 在会话创建时从 UPQ 获取市场数据。
- **ESP -> MongoDB + SQLite**：ESP 从三个本地数据源读取。
- **UPQ** 完全独立。

## 数据管道

UPQ 由一个内置、开箱即用的管道（`qfz-data`）提供数据，该管道**原地**管理两个原始市场数据源（从不复制），并将它们转换为 UPQ 的存储格式：

| 供应商 | 市场 | 原始位置（默认） |
|--------|---------|------------------------|
| massive | 美股、期权（OPRA）、国债收益率、公司行动 | `/data/massive_data` |
| tushare | 中国 A 股（+ 分红） | `/data/tushare_data` |

两个数据源都被归一化到一个存储根目录下，并统一为单一的**公司行动 (corporate-actions)** 表。拆分使用分数比率（例如中国 送转 "10转15" → 1.5；支持反向拆分），每笔分红都携带预计算好的价格比率，因此 UPQ 在读取时应用拆分 / 分红复权而无需重新推导。

```bash
pip install -e ".[pipeline]"          # adds duckdb + pyarrow + polars

# Defaults live under the data root (QFZ_DATA_ROOT=/data/qfinzero); override if needed:
export QFZ_DATA_ROOT=/data/qfinzero    # STORAGE_ROOT defaults to $QFZ_DATA_ROOT/upq
export RAW_MASSIVE_DIR=/data/massive_data
export RAW_TUSHARE_DIR=/data/tushare_data

qfz-data status                       # what raw data exists + conversion state
qfz-data convert --market us --all    # US stocks + options + rates + corp actions
qfz-data convert --market cn --all    # CN A-shares + corp actions
qfz-data convert --all                # everything (incremental + idempotent)
qfz-data validate                     # row-count / schema checks on storage
```

转换器写出字节兼容的 parquet（`stock_daily/`、`stock_minute/`、`option_day/`、`option_minute/`，按 `trade_date=` 分区；以及 `rates/` 与 `corporate_actions/`），UPQ 服务可直接读取。将 UPQ 服务指向同一个 `STORAGE_ROOT`。

### Data-admin —— 运维控制平面（CLI + Web）

除了转换之外，`qfz-data` 还管理供应商凭证、权限扫描、下载、更新计划以及数据探查 —— 即"集成数据协议 (Integrated Data Protocol)"层面：

```bash
qfz-data config --set tushare.token=…      # masked, stored at $QFZ_DATA_ROOT/_state/qfz.config.json
qfz-data scan massive                       # list flat-files datasets your S3 key can read
qfz-data scan tushare                       # validate the CN token
qfz-data acquire us_prices                  # trigger the MASSIVE download script (dry-run by default; --run)
qfz-data schedule apply                     # install the cron cadence from the config
qfz-data explore --symbols stock_daily      # per-symbol coverage in a store
qfz-data setup-state                         # first-run wizard vs. status
```

同一层面也由 **data-admin 服务**（`infra/data-admin`，`:19340`）对外提供 —— 配置/扫描、新鲜度来源、带 **SSE 日志流的更新/下载任务**、计划以及探查器 —— 并由 dashboard-web 的 **Data** 标签页驱动（设置向导、凭证 + 扫描、管道管理器、计划、探查器）。与其余服务一起启动：`./scripts/run_all.sh`（或 `./scripts/run_all.sh data-admin`）。

### 数据根目录

所有 QFinZero 自有的数据都位于单一根目录 `QFZ_DATA_ROOT`（默认 `/data/qfinzero`）之下：

```
/data/qfinzero/
├── upq/    UPQ price storage (STORAGE_ROOT) — built by `qfz-data convert`
├── esp/    ESP event databases (benzinga_earnings.sqlite3, nasdaq_econ_events.sqlite3)
└── raw/    symlinks to shared raw vendor data (massive, tushare) — read in place
```

## 安装

```bash
pip install -e .
```

这会安装 `qfinzero` 包及其所有客户端库：

```python
from qfinzero.clients.upq import UPQClient
from qfinzero.clients.esp import ESPClient
from qfinzero.clients.pmb import PMBClient
```

## 快速开始

端口默认为 `19300` 到 `19390`。可用环境变量覆盖，或从 `.env.example` 创建一个根 `.env` 用于本地开发覆盖。

### 启动所有服务

```bash
./scripts/run_all.sh           # start all
./scripts/run_all.sh pmb esp   # start specific services
./scripts/status.sh            # check what's running
./scripts/stop_all.sh          # stop all
```

### 单独启动

```bash
# Dashboard Web (Next.js frontend)
cd infra/dashboard-web
pnpm install --no-frozen-lockfile
pnpm build
PORT=19300 \
PMB_BASE_URL=http://127.0.0.1:19380 \
ESP_BASE_URL=http://127.0.0.1:19330 \
UPQ_BASE_URL=http://127.0.0.1:19350 \
PLAYGROUND_SERVICE_URL=http://127.0.0.1:19390 \
pnpm start
# open http://127.0.0.1:19300

# UPQ (Rust — build first)
cd infra/upq
cargo build --release
STORAGE_ROOT=~/upq_storage cargo run -p upq-service
# curl http://127.0.0.1:19350/health

# ESP (Python)
cd infra/esp
pip install -r requirements.txt
python main.py
# curl http://127.0.0.1:19330/esp/health

# PMB (Python — requires UPQ running)
cd infra/pmb
pip install -r requirements.txt
python main.py
# curl http://127.0.0.1:19380/v1/health

# Playground (Python — expects PMB/ESP/UPQ running)
cd infra/playground
pip install -r requirements.txt
PLAYGROUND_PORT=19390 \
QFINZERO_PMB_URL=http://127.0.0.1:19380 \
QFINZERO_ESP_URL=http://127.0.0.1:19330 \
QFINZERO_UPQ_URL=http://127.0.0.1:19350 \
python main.py
# curl http://127.0.0.1:19390/health
```

### 启动监控前端（开发模式）

```bash
cd infra/dashboard-web
pnpm install --no-frozen-lockfile
pnpm dev
# open http://127.0.0.1:19400
```

### 使用客户端

```python
from qfinzero.clients.upq import UPQClient
from qfinzero.clients.esp import ESPClient
from qfinzero.clients.pmb import PMBClient

# Price data
with UPQClient() as upq:
    bars = upq.stock_daily(["AAPL", "NVDA"], "2025-01-06", "2025-01-31")

# News and events
with ESPClient() as esp:
    events = esp.query_events(mode="upcoming", horizon_minutes=120)
    earnings = esp.earnings_calendar(tickers=["AAPL"], start_date="2025-01-01", end_date="2025-03-31")
    triggers = esp.next_triggers(tickers=["SPY", "QQQ"], min_importance="high")

# Paper trading
with PMBClient() as pmb:
    acct = pmb.create_account(initial_cash=100000.0, start_date="2025-01-06")
    sess = pmb.create_session(
        account_id=acct["account_id"],
        frequency="1d", start_ts="2025-01-06", end_ts="2025-01-31",
        universe={"stocks": ["AAPL"]},
    )
    result = pmb.step(sess["session_id"])
    pmb.buy(sess["session_id"], acct["account_id"], "AAPL", 100)
```

## 项目结构

```
qfinzero/
├── qfinzero/                   # Python package
│   ├── __init__.py
│   └── config.py               # Global port/path configuration
├── clients/                    # Client libraries
│   ├── upq/                    #   UPQ Python client
│   ├── esp/                    #   ESP Python client
│   └── pmb/                    #   PMB Python client
├── infra/                      # Service implementations
│   ├── upq/                    #   UPQ server (Rust workspace)
│   ├── esp/                    #   ESP server (FastAPI)
│   ├── pmb/                    #   PMB server (FastAPI)
│   ├── playground/             #   Playground backend (FastAPI / LangGraph)
│   └── dashboard-web/          #   Next.js frontend
├── demos/                      # Usage examples
│   ├── upq/                    #   Price query demos
│   ├── esp/                    #   Event query demos
│   └── pmb/                    #   Paper trading demos
├── docs/                       # Service documentation
│   ├── upq/                    #   UPQ API docs + OpenAPI
│   ├── esp/                    #   ESP API docs + OpenAPI
│   └── pmb/                    #   PMB API docs + OpenAPI
├── qfinzero/pipeline/          # qfz-data pipeline (raw-source mgmt + UPQ conversion)
├── .env.example                # Example local overrides
├── scripts/                    # Service management
│   ├── run_all.sh
│   ├── stop_all.sh
│   └── status.sh
└── pyproject.toml

# Data lives OUTSIDE the repo under QFZ_DATA_ROOT (default /data/qfinzero):
/data/qfinzero/
├── upq/                        # UPQ price storage (parquet)
├── esp/                        # ESP databases (benzinga_earnings, nasdaq_econ_events)
└── raw/                        # symlinks to shared raw vendor data (massive, tushare)
```

## 配置

配置遵循一个简单的分层模型：

1. 环境变量优先级最高。
2. 根 `.env` 是可选的本地开发覆盖。
3. 代码默认值回退到标准的 `19300` 到 `19390` 端口范围。

如果你需要本地覆盖，先复制 `.env.example`：

```bash
cp .env.example .env
```

`qfinzero/config.py` 读取相同的环境变量，因此客户端与服务保持一致。

| 服务 | 端口 | 环境变量覆盖 |
|---------|------|-------------|
| Dashboard Web | 19300 | `DASHBOARD_PORT` |
| PMB | 19380 | `PMB_PORT` |
| ESP | 19330 | `ESP_PORT` |
| UPQ | 19350 | `UPQ_PORT`（服务读取 `PORT`） |
| Playground | 19390 | `PLAYGROUND_PORT` |

相关的服务 URL 覆盖：

- `PMB_BASE_URL`、`ESP_BASE_URL`、`UPQ_BASE_URL` 用于 `dashboard-web`
- `PLAYGROUND_SERVICE_URL` 用于 Web playground 代理
- `QFINZERO_PMB_URL`、`QFINZERO_ESP_URL`、`QFINZERO_UPQ_URL` 用于 `playground`

数据路径（全部默认位于 `QFZ_DATA_ROOT` 下，默认 `/data/qfinzero`）：

| 数据 | 默认 | 环境变量覆盖 |
|------|---------|-------------|
| 数据根目录 | `/data/qfinzero` | `QFZ_DATA_ROOT` |
| UPQ 价格存储 | `$QFZ_DATA_ROOT/upq` | `STORAGE_ROOT` |
| ESP 财报数据库 | `$QFZ_DATA_ROOT/esp/benzinga_earnings.sqlite3` | `EARNINGS_DB` |
| ESP 经济事件数据库 | `$QFZ_DATA_ROOT/esp/nasdaq_econ_events.sqlite3` | `ECON_EVENTS_DB` |
| 原始 massive（共享） | `/data/massive_data` | `RAW_MASSIVE_DIR` |
| 原始 tushare（共享） | `/data/tushare_data` | `RAW_TUSHARE_DIR` |

## 文档

- [UPQ API Reference](docs/upq/README.md) | [Agent Guide](docs/upq/agent-guide.md) | [OpenAPI](docs/upq/openapi.yaml)
- [ESP API Reference](docs/esp/README.md) | [Agent Guide](docs/esp/agent-guide.md) | [OpenAPI](docs/esp/openapi.yaml)
- [PMB API Reference](docs/pmb/README.md) | [Agent Guide](docs/pmb/agent-guide.md) | [OpenAPI](docs/pmb/openapi.yaml)

## 许可证

MIT License
