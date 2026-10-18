> English: [../../README.md](../../README.md)

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
| `/` | 网站：首页、`/login`，以及登录后的控制台（`/chat`、`/broker`、`/data`、`/account` 等）—— **含其自有的 `/api/*` 后端** |
| `/auth/*` | 登录、API key 和用户管理 |
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

## Agent：时间锁、交易时段与研究

- **时间锁。** 每个 UPQ 查询都接受 `as_of`。把 agent 绑定到一个 PMB session（`X-QFZ-Session` header、`QFZ_TIME_LOCK_SESSION` 或 `session_id`）后，所有数据工具都按该 session 当前的 bar 作答，由服务器强制执行。
- **交易时段。** 委托带有 `REGULAR`、`EXTENDED` 或 `OVERNIGHT` 交易时间（美东 20:00–04:00 的夜盘归属下一个交易日）；DAY/GTD 过期和按成交量限制的部分成交都会执行；`pmb_step_until` 在成交、价格触发、到点或开盘时才唤醒 agent。
- **报价。** 股票和期权的分钟 NBBO 存储、按中间价计算 Greeks 的日内期权链快照，以及分钟级 session 中按报价成交的期权。
- **研究。** `qfz-research eval|backtest "cs_rank(-pct(close, 15))" …`（以及 MCP 工具 `research_eval_factor` / `research_backtest`）用 IC、分层价差、换手率和计入成本的回测来评估因子表达式。

详见 [平台指南](platform-guide.md)。

## 账号与登录

hub 要求登录后才能使用控制台、`/svc/*` 和 `/mcp`。角色分为 viewer（只读）、researcher（交易、研究、MCP）和 admin（另可管理数据和用户）。agent 使用账号页或 `qfz-auth create-key` 生成的 API key（`Authorization: Bearer qfz_…`）。PMB 的账户和 session 只对创建者可见。

```bash
qfz-auth create-user you --role admin    # 或在首次启动前设置 QFZ_ADMIN_PASSWORD
qfz-server                                # 然后打开 http://127.0.0.1:19777/login
```

`QFZ_AUTH_MODE=off` 可在本地开发时关闭登录。全部设置见[平台指南第 5 节](platform-guide.md#5-账号角色与-api-key)。

## 数据管道

UPQ 由一个内置、开箱即用的管道（`qfz-data`）提供数据，该管道**原地**管理三个原始市场数据源（从不复制），并将它们转换为 UPQ 的存储格式：

| 供应商 | 市场 | 原始位置（默认） |
|--------|---------|------------------------|
| massive | 美股、期权（OPRA）、国债收益率、公司行动 | `/data/massive_data` |
| tushare | 中国 A 股（+ 分红） | `/data/tushare_data` |
| databento | 美股 + 美股期权（OPRA），DBN 或 parquet | `/data/databento` |

两个数据源都被归一化到一个存储根目录下，并统一为单一的**公司行动 (corporate-actions)** 表。拆分使用分数比率（例如中国 送转 "10转15" → 1.5；支持反向拆分），每笔分红都携带预计算好的价格比率，因此 UPQ 在读取时应用拆分 / 分红复权而无需重新推导。

```bash
pip install -e ".[pipeline]"          # adds duckdb + pyarrow + polars

# Defaults live under the data root (QFZ_DATA_ROOT=/data/qfinzero); override if needed:
export QFZ_DATA_ROOT=/data/qfinzero    # STORAGE_ROOT defaults to $QFZ_DATA_ROOT/upq
export RAW_MASSIVE_DIR=/data/massive_data
export RAW_TUSHARE_DIR=/data/tushare_data
export RAW_DATABENTO_DIR=/data/databento

qfz-data status                       # what raw data exists + conversion state
qfz-data convert --market us --all    # US stocks + options + rates + corp actions
qfz-data convert --market cn --all    # CN A-shares + corp actions
qfz-data convert --all                # everything (incremental + idempotent)
qfz-data convert --vendor databento   # only Databento files (--jobs N to parallelize)
qfz-data validate                     # row-count / schema checks on storage
```

转换器写出字节兼容的 parquet（`stock_daily/`、`stock_minute/`、`option_day/`、`option_minute/`，按 `trade_date=` 分区；以及 `rates/` 与 `corporate_actions/`），UPQ 服务可直接读取。将 UPQ 服务指向同一个 `STORAGE_ROOT`。

### Databento

完整说明见 [数据适配器](data-adapters.md)。`pip install -e ".[databento]"` 安装 DBN 读取器和历史 API 客户端。把 `RAW_DATABENTO_DIR` 指向任意存放 Databento 文件的目录即可：每个 `*.dbn`、`*.dbn.zst` 或 Databento 导出的 `*.parquet` 都按文件自身的头信息识别，所以批量下载、按代码分目录、混合布局都能用。

| Databento schema | 写入的 UPQ 存储 |
|------------------|------------|
| `ohlcv-1m`、`ohlcv-1s` | 分钟线 + 日线 |
| `ohlcv-1h`、`ohlcv-1d`、`ohlcv-eod` | 日线 |
| `trades`、`tbbo`、`tcbbo`、`mbp-1`、`mbp-10`、`cmbp-1`、`mbo` | 由逐笔成交聚合出分钟线 + 日线 |
| `cmbp-1`、`cbbo-*`、`bbo-*` | `option_quote_minute` / `stock_quote_minute`（每分钟最后的盘口） |
| definition、statistics、status | 只索引不转换 |

`OCEA.MEMOIR`（Blue Ocean）提供美东 20:00–04:00 的夜盘分钟线。

`OPRA.*` 数据集写入 `option_minute` / `option_day`，OSI 合约代码改写为 UPQ 格式（`SPY   250117C00500000` → `O:SPY250117C00500000`）。美股数据集（`XNAS.ITCH`、`EQUS.*`、`DBEQ.*` 等）写入 `stock_minute` / `stock_daily`；期货交易所数据集（`GLBX.MDP3`、ICE、Nodal）按 CME 交易时段写入 `future_minute` / `future_daily` / `future_quote_minute`。分钟线按 `ts_event` 切分；交易日和日线按美东时间，日线开高低收取 09:30–16:00 常规时段，成交量取全天。MBO 里只有 `T` 记录计为成交（`F` 是同一笔成交的被动方回报）。

Databento 在每个 `trade_date=` 分区里写 `part-databento-0000.parquet`，与 massive 的分片并存，并且只**补齐** massive 当天没有的代码，两家数据不会重复计量。单一交易所的数据（如 `XNAS.ITCH`）只包含该交易所的成交量；同一代码有多个来源时，优先全市场合并数据（`EQUS.*`、`OPRA.*`）。每个原始文件抽取出的K线缓存在 `$STORAGE_ROOT/_staging/databento`，重跑只读取新增或改动过的文件。

```bash
qfz-data config --set databento.api_key=db-…
qfz-data scan databento                      # 列出该 key 可查询的数据集
# 默认 dry-run：只报价并列出将写入的文件
qfz-data acquire databento --dataset OPRA.PILLAR --schema tcbbo \
    --symbols SPY.OPT --stype-in parent --start 2026-09-01 --end 2026-09-05
# 付费数据必须显式给出费用上限（美元）
qfz-data acquire databento --dataset EQUS.MINI --schema ohlcv-1m \
    --symbols SPY,QQQ --start 2026-01-02 --end 2026-01-31 --max-cost 5 --run
qfz-data convert --vendor databento --jobs 8
```

### Data-admin —— 运维控制平面（CLI + Web）

除了转换之外，`qfz-data` 还管理供应商凭证、权限扫描、下载、更新计划以及数据探查 —— 即"集成数据协议 (Integrated Data Protocol)"层面：

```bash
qfz-data config --set tushare.token=…      # masked, stored at $QFZ_DATA_ROOT/_state/qfz.config.json
qfz-data scan massive                       # list flat-files datasets your S3 key can read
qfz-data scan tushare                       # validate the CN token
qfz-data scan databento                     # validate the Databento key
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
└── raw/    symlinks to shared raw vendor data (massive, tushare, databento) — read in place
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
└── raw/                        # symlinks to shared raw vendor data (massive, tushare, databento)
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
| 原始 Databento（共享） | `/data/databento` | `RAW_DATABENTO_DIR` |

## 文档

网页界面在 `/docs` 提供可搜索的中英文文档中心，内容与下列文件相同。

- 入门：[快速开始](getting-started.md) · [平台指南](platform-guide.md)（时间锁、交易时段、报价、研究、账号）
- 指南：[Agent 行情工具](upq/agent-guide.md) · [Agent 交易工具](pmb/agent-guide.md) · [交易终端](pmb/broker-terminal.md) · [Agent 基准测试](bench.md) · [样本数据集](sample-data.md) · [数据适配器](data-adapters.md)
- 参考：[MCP 工具](../en/mcp-tools.md)（英文） · [UPQ](upq/README.md)（[OpenAPI](../upq/openapi.yaml)） · [ESP](esp/README.md)（[OpenAPI](../esp/openapi.yaml)） · [PMB](pmb/README.md)（[OpenAPI](../pmb/openapi.yaml)） · [配置](configuration.md) · [时区约定](conventions/timezone.md)
- 运维：[部署与运维](operations.md) · [更新日志](../../CHANGELOG.md)（英文）

## 许可证

MIT License
