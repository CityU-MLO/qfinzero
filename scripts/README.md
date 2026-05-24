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
| PMB | 19701 | Paper Money Broker |
| ESP | 19702 | News Pushing Pipeline |
| UPQ | 19703 | Unified Price Query (Rust) |
| Playground | 19704 | LangGraph playground |
| Web | 19700 | Next.js dashboard |

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
