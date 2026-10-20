> English: [../../../scripts/README.md](../../../scripts/README.md)

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
