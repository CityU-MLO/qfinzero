# QFinZero

Modular infrastructure for quantitative finance research. Four services, each running as an independent REST API server with Python/Rust clients designed for agent integration.

## Services

| Service | Full Name | Language | Default Port | Description |
|---------|-----------|----------|--------------|-------------|
| **FFO** | Formulaic Factor Optimization | Python (Flask) | 19330 | Factor evaluation, IC metrics, portfolio backtesting, multi-factor combination |
| **NPP** | News Pushing Pipeline | Python | — | News ingestion, cleaning, tagging, and push to downstream consumers |
| **PMB** | Paper Money Broker | Python (FastAPI) | 24444 | Step-driven paper trading broker for backtesting AI trading agents |
| **UPQ** | Unified Price Query | Rust (Axum) | 19350 | High-performance stock/option/rates price data via REST API |

## Architecture

All services follow the same pattern: **Server (REST API) → Client Library → Agent Interface**.

```
┌─────────────────────────────────────────────────────┐
│                    Agent / User                      │
└──────────┬──────────┬──────────┬──────────┬─────────┘
           │          │          │          │
           v          v          v          v
      ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
      │  FFO   │ │  NPP   │ │  PMB   │ │  UPQ   │
      │ Client │ │ Client │ │ Client │ │ Client │
      └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘
          │          │          │          │
          v          v          v          v
      ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
      │  FFO   │ │  NPP   │ │  PMB   │ │  UPQ   │
      │ Server │ │ Server │ │ Server │ │ Server │
      │ :19330 │ │        │ │ :24444 │ │ :19350 │
      └────────┘ └────────┘ └───┬────┘ └────────┘
                                │          ▲
                                └──────────┘
                              PMB reads market
                              data from UPQ
```

### Service Dependencies

- **PMB → UPQ**: PMB fetches market data (stock/option bars) from UPQ at session creation time.
- All other services are independent.

## Project Structure

```
qfinzero/
├── README.md                   # This file
├── docs/                       # Centralized documentation
│   ├── ffo/                    #   FFO docs + OpenAPI spec
│   ├── npp/                    #   NPP docs + OpenAPI spec
│   ├── pmb/                    #   PMB docs + OpenAPI spec
│   └── upq/                    #   UPQ docs + OpenAPI spec
├── clients/                    # Client libraries (per-service)
│   ├── ffo/                    #   FFO Python client
│   ├── npp/                    #   NPP Python client
│   ├── pmb/                    #   PMB Python client
│   └── upq/                    #   UPQ Python client
├── demos/                      # Usage demos for all services
│   ├── ffo/                    #   FFO demo scripts
│   ├── npp/                    #   NPP demo scripts
│   ├── pmb/                    #   PMB demo scripts
│   └── upq/                    #   UPQ demo scripts
├── infra/                      # Service implementations
│   ├── ffo/                    #   FFO server
│   ├── npp/                    #   NPP server
│   ├── pmb/                    #   PMB server
│   └── upq/                    #   UPQ server (Rust workspace)
├── documents/                  # Legacy / research documents
└── server/                     # Legacy server code
```

## Quick Start

### 1. UPQ (Price Data)

```bash
cd infra/upq
cargo build --release
cargo run -p upq-ingest -- ingest --raw-root ~/upq_data --storage-root ~/upq_storage
STORAGE_ROOT=~/upq_storage cargo run -p upq-service
# Health check: curl http://127.0.0.1:19350/health
```

### 2. FFO (Factor Evaluation)

```bash
cd infra/ffo
pip install -r requirements.txt  # if needed
python backend_app.py
# Health check: curl http://127.0.0.1:19330/health
```

### 3. PMB (Paper Trading)

```bash
cd infra/pmb
pip install -r requirements.txt
python main.py                   # requires UPQ running
# Health check: curl http://127.0.0.1:24444/v1/health
```

### 4. NPP (News Pipeline)

```bash
cd infra/npp
pip install -r requirements.txt
python massive_news.py           # or other ingestion scripts
```

## Documentation

Per-service documentation lives in [docs/](docs/):

- [FFO Documentation](docs/ffo/README.md) — Factor evaluation API, OpenAPI spec
- [NPP Documentation](docs/npp/README.md) — News pipeline API, OpenAPI spec
- [PMB Documentation](docs/pmb/README.md) — Paper trading API, OpenAPI spec
- [UPQ Documentation](docs/upq/README.md) — Price query API, OpenAPI spec

OpenAPI specifications:

- [FFO OpenAPI](docs/ffo/openapi.yaml)
- [NPP OpenAPI](docs/npp/openapi.yaml)
- [PMB OpenAPI](docs/pmb/openapi.yaml)
- [UPQ OpenAPI](docs/upq/openapi.yaml)

## License

MIT License
