# QFinZero

**A Unified Trading Environment for LLM Agents**

QFinZero unifies price data, event/news retrieval, and brokerage simulation behind consistent, time-aligned APIs so LLM agents can query, reason, and trade in a coherent environment.

> Haochen Luo1*, Binh Minh An1, Ho Tin Ko2, Junjie Xu5, Pok Hin Tang1, Wang Chak Wong1, Yifan Li1, Yuan Gao1, Zhengzhao Lai4, Yuan Zhang3, Chen Liu1
>
> 1 City University of Hong Kong, 2 Yuen Long Merchants Association Secondary School, 3 Shanghai University of Finance and Economics, 4 University of Science and Technology of China, 5 The Chinese University of Hong Kong (Shenzhen)
>
> Correspondence: chester.hc.luo@my.cityu.edu.hk, zhang.yuan@sufe.edu.cn, chen.liu@cityu.edu.hk

## Abstract

Large language model (LLM) agents are increasingly applied to financial decision-making tasks that require interaction with external tools such as market data, news, and trade execution. Existing systems are fragmented across task-specific APIs, which introduces inconsistent schemas, brittle integration, and weak reproducibility. QFinZero addresses this gap with a unified trading environment that standardizes three core capabilities: multi-frequency market and derivatives data access (UPQ), structured news and event retrieval (ESP), and a stateful brokerage simulator with explicit order lifecycle management (PMB). All tools expose consistent JSON schemas and time-aligned interfaces, enabling agents to autonomously retrieve information, manage portfolio state, and execute trades within a coherent framework. By abstracting financial interaction into composable, agent-invokable primitives, QFinZero reduces engineering overhead and supports reproducible evaluation with deterministic replay and comprehensive logging.

## Services

| Service | Full Name | Port | Description |
|---------|-----------|------|-------------|
| **Dashboard Web** | Next.js monitoring frontend | 19300 | Status dashboard and web UI for service browsing and playground access |
| **PMB** | Paper Money Broker | 19380 | Stateful brokerage simulation with order lifecycle and margin management (Python/FastAPI) |
| **ESP** | News Pushing Pipeline | 19330 | Unified event query: earnings, economic calendar, market news (Python/FastAPI) |
| **UPQ** | Unified Price Query | 19350 | Multi-resolution stock, option, and rates data (Rust/Axum) |
| **Playground** | Agent playground service | 19390 | LLM agent backend used by the web playground UI |

### Port Layout

| Port | Service | Primary Endpoint |
|------|---------|------------------|
| `19300` | Dashboard Web | `http://127.0.0.1:19300/` |
| `19380` | PMB | `http://127.0.0.1:19380/v1/health` |
| `19330` | ESP | `http://127.0.0.1:19330/esp/health` |
| `19350` | UPQ | `http://127.0.0.1:19350/health` |
| `19390` | Playground | `http://127.0.0.1:19390/health` |

## Architecture

```
┌─────────────────────────────────────────────────┐
│              LLM Agent / User                    │
└────────┬──────────────┬──────────────┬───────────┘
         │              │              │
         v              v              v
    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │   UPQ   │    │   ESP   │    │   PMB   │
    │ Client  │    │ Client  │    │ Client  │
    └────┬────┘    └────┬────┘    └────┬────┘
         │              │              │
         v              v              v
    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │   UPQ   │    │   ESP   │    │   PMB   │
    │ :19350  │    │ :19330  │    │ :19380  │
    └─────────┘    └────┬────┘    └────┬────┘
         ▲              │              │
         │              v              │
         │         ┌─────────┐         │
         │         │MongoDB  │         │
         │         │SQLite x2│         │
         │         └─────────┘         │
         └─────────────────────────────┘
                 PMB reads market
                 data from UPQ
```

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
