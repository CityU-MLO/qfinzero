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
./scripts/test-env.sh start npp
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
| PMB | 19701 | Paper Money Broker |
| NPP | 19702 | News Pushing Pipeline |
| UPQ | 19703 | Unified Price Query (Rust) |
| Playground | 19704 | LangGraph playground |
| Web | 19700 | Next.js dashboard |

---

### `run_all.sh` — Local service start

Starts all services locally (on the machine where the script runs). Used for local development.

```bash
./scripts/run_all.sh           # start all
./scripts/run_all.sh pmb npp   # start specific services
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
