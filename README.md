# QFinZero

**A Unified Trading Environment for LLM Agents**

QFinZero unifies price data, event/news retrieval, and brokerage simulation behind consistent, time-aligned APIs so LLM agents can query, reason, and trade in a coherent environment.

> Haochen Luo1*, Binh Minh An1, Ho Tin Ko2, Junjie Xu5, Pok Hin Tang1, Wang Chak Wong1, Yifan Li1, Yuan Gao1, Zhengzhao Lai4, Yuan Zhang3, Chen Liu1
>
> 1 City University of Hong Kong, 2 Yuen Long Merchants Association Secondary School, 3 Shanghai University of Finance and Economics, 4 University of Science and Technology of China, 5 The Chinese University of Hong Kong (Shenzhen)
>
> Correspondence: chester.hc.luo@my.cityu.edu.hk, zhang.yuan@sufe.edu.cn, chen.liu@cityu.edu.hk

## Abstract

Large language model (LLM) agents are increasingly applied to financial decision-making tasks that require interaction with external tools such as market data, news, and trade execution. Existing systems are fragmented across task-specific APIs, which introduces inconsistent schemas, brittle integration, and weak reproducibility. QFinZero addresses this gap with a unified trading environment that standardizes three core capabilities: multi-frequency market and derivatives data access (UPQ), structured news and event retrieval (NPP), and a stateful brokerage simulator with explicit order lifecycle management (PMB). All tools expose consistent JSON schemas and time-aligned interfaces, enabling agents to autonomously retrieve information, manage portfolio state, and execute trades within a coherent framework. By abstracting financial interaction into composable, agent-invokable primitives, QFinZero reduces engineering overhead and supports reproducible evaluation with deterministic replay and comprehensive logging.

## Services

| Service | Full Name | Port | Description |
|---------|-----------|------|-------------|
| **UPQ** | Unified Price Query | 19350 | Multi-resolution stock, option, and rates data (Rust/Axum) |
| **NPP** | News Pushing Pipeline | 19330 | Unified event query: earnings, economic calendar, market news (Python/FastAPI) |
| **PMB** | Paper Money Broker | 19320 | Stateful brokerage simulation with order lifecycle and margin management (Python/FastAPI) |

Port 19380 is reserved for a future system status dashboard.

## Architecture

```
┌─────────────────────────────────────────────────┐
│              LLM Agent / User                    │
└────────┬──────────────┬──────────────┬───────────┘
         │              │              │
         v              v              v
    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │   UPQ   │    │   NPP   │    │   PMB   │
    │ Client  │    │ Client  │    │ Client  │
    └────┬────┘    └────┬────┘    └────┬────┘
         │              │              │
         v              v              v
    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │   UPQ   │    │   NPP   │    │   PMB   │
    │ :19350  │    │ :19330  │    │ :19320  │
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

**Unified Price Query (UPQ)** provides multi-resolution price data (minute and daily bars) for equities, options (OPRA), and treasury yields through a single API. Agents query structured market states without handling vendor-specific formatting.

**News Pushing Pipeline (NPP)** aggregates news articles (MongoDB), earnings calendars (Benzinga), and US economic events (NASDAQ) into a canonical event schema. Supports three query modes: upcoming events, recently occurred events, and arbitrary time windows. All times normalized to UTC.

**Paper Money Broker (PMB)** is a step-driven brokerage simulator supporting market/limit/stop orders, margin accounts, and explicit order lifecycle (pending, filled, canceled). Time advances only when the agent calls `step`, enabling deterministic replay.

### Service Dependencies

- **PMB -> UPQ**: PMB fetches market data from UPQ at session creation.
- **NPP -> MongoDB + SQLite**: NPP reads from three local data sources.
- **UPQ** is fully independent.

## Installation

```bash
pip install -e .
```

This installs the `qfinzero` package with all client libraries:

```python
from qfinzero.clients.upq import UPQClient
from qfinzero.clients.npp import NPPClient
from qfinzero.clients.pmb import PMBClient
```

## Quick Start

Edit `config/qfinzero.env` if you want to change ports, host, or data paths.

### Start All Services

```bash
./scripts/run_all.sh           # start all
./scripts/run_all.sh pmb npp   # start specific services
./scripts/status.sh            # check what's running
./scripts/stop_all.sh          # stop all
```

### Start Individually

```bash
# UPQ (Rust — build first)
cd infra/upq
cargo build --release
STORAGE_ROOT=~/upq_storage cargo run -p upq-service
# curl http://127.0.0.1:19350/health

# NPP (Python)
cd infra/npp
pip install -r requirements.txt
python main.py
# curl http://127.0.0.1:19330/npp/health

# PMB (Python — requires UPQ running)
cd infra/pmb
pip install -r requirements.txt
python main.py
# curl http://127.0.0.1:19320/v1/health
```

### Use the Clients

```python
from qfinzero.clients.upq import UPQClient
from qfinzero.clients.npp import NPPClient
from qfinzero.clients.pmb import PMBClient

# Price data
with UPQClient() as upq:
    bars = upq.stock_daily(["AAPL", "NVDA"], "2025-01-06", "2025-01-31")

# News and events
with NPPClient() as npp:
    events = npp.query_events(mode="upcoming", horizon_minutes=120)
    earnings = npp.earnings_calendar(tickers=["AAPL"], start_date="2025-01-01", end_date="2025-03-31")
    triggers = npp.next_triggers(tickers=["SPY", "QQQ"], min_importance="high")

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
│   ├── npp/                    #   NPP Python client
│   └── pmb/                    #   PMB Python client
├── infra/                      # Service implementations
│   ├── upq/                    #   UPQ server (Rust workspace)
│   ├── npp/                    #   NPP server (FastAPI)
│   └── pmb/                    #   PMB server (FastAPI)
├── demos/                      # Usage examples
│   ├── upq/                    #   Price query demos
│   ├── npp/                    #   Event query demos
│   └── pmb/                    #   Paper trading demos
├── docs/                       # Service documentation
│   ├── upq/                    #   UPQ API docs + OpenAPI
│   ├── npp/                    #   NPP API docs + OpenAPI
│   └── pmb/                    #   PMB API docs + OpenAPI
├── config/                     # Global service config
│   └── qfinzero.env
├── data/                       # Local databases
│   ├── benzinga_earnings.sqlite3
│   └── nasdaq_econ_events.sqlite3
├── scripts/                    # Service management
│   ├── run_all.sh
│   ├── stop_all.sh
│   └── status.sh
└── pyproject.toml
```

## Configuration

Global service configuration lives in `config/qfinzero.env` and can be overridden by environment variables. The service scripts automatically load this file.

`qfinzero/config.py` reads the same environment variables so clients stay consistent.

| Service | Port | Env Override |
|---------|------|-------------|
| PMB | 19320 | `PMB_PORT` |
| NPP | 19330 | `NPP_PORT` |
| UPQ | 19350 | `UPQ_PORT` (service reads `PORT`) |
| Dashboard | 19380 | `DASHBOARD_PORT` (reserved) |

Each service also accepts host/port via its own environment variables (e.g., `PMB_HOST`, `NPP_MONGO_URI`).

## Documentation

- [UPQ API Reference](docs/upq/README.md) | [Agent Guide](docs/upq/agent-guide.md) | [OpenAPI](docs/upq/openapi.yaml)
- [NPP API Reference](docs/npp/README.md) | [Agent Guide](docs/npp/agent-guide.md) | [OpenAPI](docs/npp/openapi.yaml)
- [PMB API Reference](docs/pmb/README.md) | [Agent Guide](docs/pmb/agent-guide.md) | [OpenAPI](docs/pmb/openapi.yaml)

## License

MIT License
