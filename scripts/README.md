> **English** (below) · [中文](#中文文档) (在下方)

# QFinZero Scripts

Operational scripts for managing QFinZero services and data pipelines.

---

## Service Management

### `test-env.sh` — Remote test environment (primary workflow)

Manages the five QFinZero services on the remote `qlib` server via SSH. Handles git pull, build-if-needed, start/stop/restart, and health checks.

**Runs from:** your local Mac
**Targets:** `ssh qlib` → `/home/qlib/qfinzero`

```bash
# Start all services (git pull + build + start)
./scripts/test-env.sh start

# Start a specific service
./scripts/test-env.sh start pmb
./scripts/test-env.sh start esp
./scripts/test-env.sh start upq
./scripts/test-env.sh start web
./scripts/test-env.sh start playground

# Stop / restart
./scripts/test-env.sh stop
./scripts/test-env.sh restart web

# Show status of all services
./scripts/test-env.sh status
```

Services and ports on qlib:

| Service | Port | Description |
|---|---|---|
| Web | 19300 | Next.js dashboard |
| ESP | 19330 | News Pushing Pipeline |
| UPQ | 19350 | Unified Price Query (Rust) |
| PMB | 19380 | Paper Money Broker |
| Playground | 19390 | LangGraph playground |

---

### `run_all.sh` — Local service start

Starts all services locally (on the machine where the script runs). Used for local development.

```bash
./scripts/run_all.sh           # start all
./scripts/run_all.sh pmb esp   # start specific services
```

### `stop_all.sh` — Local service stop

```bash
./scripts/stop_all.sh
```

### `status.sh` — Local service health check

```bash
./scripts/status.sh
```

---

## Data Pipeline

### `news_data.sh` — News data pipeline

Manages all market news and financial calendar data on the qlib server. Wraps four Python scrapers in `/home/qlib/news/`.

**Must be run directly on the qlib server** (not via SSH from your Mac).

```bash
# On qlib: full historical init (downloads everything through today)
./scripts/news_data.sh init

# On qlib: daily incremental update (idempotent, safe to re-run)
./scripts/news_data.sh update

# On qlib: install cron job (runs update daily at 06:00 UTC)
./scripts/news_data.sh deploy-cron

# On qlib: show current status of all data sources
./scripts/news_data.sh status
```

**Data sources managed:**

| Source | Output | Coverage |
|---|---|---|
| Massive.com news API | `output_news_by_day/` + MongoDB `market_news.ticker_news` | 2022-01-01 → today |
| NASDAQ economic calendar | `nasdaq_econ_events.sqlite3` | 2020-01-01 → today |
| Benzinga earnings (Massive API) | `benzinga_earnings.sqlite3` | FY2011 → current year |

**Deploying to qlib:**

```bash
# From your Mac — push changes, then pull on server
git push origin <branch>
ssh qlib "cd /home/qlib/qfinzero && git pull origin <branch>"
```

**Logs** are written to `/home/qlib/news/logs/` with timestamped filenames per run. The cron job appends to `cron.log`.

---

### `upq_flatfiles.sh` — UPQ market data daily sync (AWS S3 Flat Files)

Syncs stock/options flat files from Massive/Polygon S3 (`https://files.polygon.io`, bucket `flatfiles`) into UPQ raw layout, then runs `upq-ingest`.

**Safety default:** runs in **test mode** and writes only to `/tmp/upq_flatfiles_test` (does not touch `/home/qlib/data`).

```bash
# 1) Test mode (safe, /tmp only)
./scripts/upq_flatfiles.sh update

# 2) Preview actions only
./scripts/upq_flatfiles.sh update --dry-run

# 3) Production paths (/home/qlib/upq_*)
./scripts/upq_flatfiles.sh update --prod

# 4) Check current status/freshness hints
./scripts/upq_flatfiles.sh status
./scripts/upq_flatfiles.sh status --prod

# 5) Sync ONLY data-layout hierarchy (compatible with /home/qlib/data), date-range scoped
./scripts/upq_flatfiles.sh sync-data-range --from 2026-01-01 --to 2026-02-27 --no-rates

# 6) Install daily cron (weekday 17:30 UTC by default)
./scripts/upq_flatfiles.sh deploy-cron --prod

# 7) Stock-only daily incremental update (recommended for current permissions)
./scripts/upq_flatfiles.sh daily-stock-update --prod
```

Required env vars before `update`:

```bash
export POLYGON_S3_ACCESS_KEY_ID=...
export POLYGON_S3_SECRET_ACCESS_KEY=...
```

Prerequisites on server:

- `aws` CLI installed
- `infra/upq/target/release/upq-ingest` built and executable

Notes:

- Uses staging dir (`/tmp/upq_flatfiles_test/stage` in test mode, `/home/qlib/upq_stage` in prod mode), then flattens files into `upq-ingest` expected raw layout.
- Copy step is append-only (`cp -n`), so existing raw files are not overwritten.
- `sync-data-range` writes with `/home/qlib/data`-compatible hierarchy:
  - `stock/us_stocks_sip_day_aggs_v1_YYYY_MM_YYYY-MM-DD.csv.gz`
  - `stock/us_stocks_sip_minute_aggs_v1_YYYY_MM_YYYY-MM-DD.csv.gz`
  - `us_options_opra/day_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`
  - `us_options_opra/minute_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`

Incremental ingest design:

- Use `daily-stock-update --prod` for daily operations.
- It computes range from `upq_storage/stock_daily` latest partition + 1 day to today (UTC).
- It syncs only stock files from S3 into `/home/qlib/data/stock`.
- It runs `ingest-stock-range` with a temporary raw root containing only date-range stock files, avoiding full 3000+ file re-scan.

---

<a id="中文文档"></a>

# 中文文档

# QFinZero Scripts

用于管理 QFinZero 服务和数据管道的运维脚本。

---

## 服务管理

### `test-env.sh` — 远程测试环境（主要工作流）

通过 SSH 管理远程 `qlib` 服务器上的五个 QFinZero 服务。负责 git pull、按需构建、启动/停止/重启以及健康检查。

**运行位置：** 你的本地 Mac
**目标：** `ssh qlib` → `/home/qlib/qfinzero`

```bash
# Start all services (git pull + build + start)
./scripts/test-env.sh start

# Start a specific service
./scripts/test-env.sh start pmb
./scripts/test-env.sh start esp
./scripts/test-env.sh start upq
./scripts/test-env.sh start web
./scripts/test-env.sh start playground

# Stop / restart
./scripts/test-env.sh stop
./scripts/test-env.sh restart web

# Show status of all services
./scripts/test-env.sh status
```

qlib 上的服务与端口：

| 服务 | 端口 | 说明 |
|---|---|---|
| Web | 19300 | Next.js 仪表盘 |
| ESP | 19330 | 新闻推送管道 |
| UPQ | 19350 | 统一价格查询（Rust） |
| PMB | 19380 | 模拟资金经纪商 |
| Playground | 19390 | LangGraph playground |

---

### `run_all.sh` — 本地服务启动

在本地（脚本运行所在的机器上）启动所有服务。用于本地开发。

```bash
./scripts/run_all.sh           # start all
./scripts/run_all.sh pmb esp   # start specific services
```

### `stop_all.sh` — 本地服务停止

```bash
./scripts/stop_all.sh
```

### `status.sh` — 本地服务健康检查

```bash
./scripts/status.sh
```

---

## 数据管道

### `news_data.sh` — 新闻数据管道

管理 qlib 服务器上所有市场新闻和财经日历数据。封装了 `/home/qlib/news/` 中的四个 Python 抓取器。

**必须直接在 qlib 服务器上运行**（而非从你的 Mac 通过 SSH 运行）。

```bash
# On qlib: full historical init (downloads everything through today)
./scripts/news_data.sh init

# On qlib: daily incremental update (idempotent, safe to re-run)
./scripts/news_data.sh update

# On qlib: install cron job (runs update daily at 06:00 UTC)
./scripts/news_data.sh deploy-cron

# On qlib: show current status of all data sources
./scripts/news_data.sh status
```

**管理的数据源：**

| 数据源 | 输出 | 覆盖范围 |
|---|---|---|
| Massive.com news API | `output_news_by_day/` + MongoDB `market_news.ticker_news` | 2022-01-01 → today |
| NASDAQ economic calendar | `nasdaq_econ_events.sqlite3` | 2020-01-01 → today |
| Benzinga earnings (Massive API) | `benzinga_earnings.sqlite3` | FY2011 → current year |

**部署到 qlib：**

```bash
# From your Mac — push changes, then pull on server
git push origin <branch>
ssh qlib "cd /home/qlib/qfinzero && git pull origin <branch>"
```

**日志**写入 `/home/qlib/news/logs/`，每次运行使用带时间戳的文件名。cron 任务追加到 `cron.log`。

---

### `upq_flatfiles.sh` — UPQ 市场数据每日同步（AWS S3 Flat Files）

将股票/期权 flat files 从 Massive/Polygon S3（`https://files.polygon.io`，bucket `flatfiles`）同步到 UPQ 原始布局中，然后运行 `upq-ingest`。

**安全默认值：** 以**测试模式**运行，仅写入 `/tmp/upq_flatfiles_test`（不会触及 `/home/qlib/data`）。

```bash
# 1) Test mode (safe, /tmp only)
./scripts/upq_flatfiles.sh update

# 2) Preview actions only
./scripts/upq_flatfiles.sh update --dry-run

# 3) Production paths (/home/qlib/upq_*)
./scripts/upq_flatfiles.sh update --prod

# 4) Check current status/freshness hints
./scripts/upq_flatfiles.sh status
./scripts/upq_flatfiles.sh status --prod

# 5) Sync ONLY data-layout hierarchy (compatible with /home/qlib/data), date-range scoped
./scripts/upq_flatfiles.sh sync-data-range --from 2026-01-01 --to 2026-02-27 --no-rates

# 6) Install daily cron (weekday 17:30 UTC by default)
./scripts/upq_flatfiles.sh deploy-cron --prod

# 7) Stock-only daily incremental update (recommended for current permissions)
./scripts/upq_flatfiles.sh daily-stock-update --prod
```

执行 `update` 前所需的环境变量：

```bash
export POLYGON_S3_ACCESS_KEY_ID=...
export POLYGON_S3_SECRET_ACCESS_KEY=...
```

服务器上的前置条件：

- 已安装 `aws` CLI
- `infra/upq/target/release/upq-ingest` 已构建且可执行

注意事项：

- 使用暂存目录（测试模式下为 `/tmp/upq_flatfiles_test/stage`，生产模式下为 `/home/qlib/upq_stage`），然后将文件展平为 `upq-ingest` 所需的原始布局。
- 复制步骤为仅追加（`cp -n`），因此已有的原始文件不会被覆盖。
- `sync-data-range` 以与 `/home/qlib/data` 兼容的层级结构写入：
  - `stock/us_stocks_sip_day_aggs_v1_YYYY_MM_YYYY-MM-DD.csv.gz`
  - `stock/us_stocks_sip_minute_aggs_v1_YYYY_MM_YYYY-MM-DD.csv.gz`
  - `us_options_opra/day_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`
  - `us_options_opra/minute_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`

增量摄取设计：

- 日常操作使用 `daily-stock-update --prod`。
- 它从 `upq_storage/stock_daily` 最新分区 + 1 天到今天（UTC）计算日期范围。
- 它仅将股票文件从 S3 同步到 `/home/qlib/data/stock`。
- 它使用仅包含日期范围股票文件的临时原始根目录运行 `ingest-stock-range`，避免对全部 3000+ 文件重新扫描。
