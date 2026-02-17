# UPQ — Unified Price Query

A high-performance Rust-based price query service providing REST API access to stock, option, and treasury rates data. Uses DuckDB + Parquet for efficient storage and querying.

## Server

- **Language**: Rust (Axum)
- **Default Port**: 19350
- **Entry Point**: `cargo run -p upq-service`

```bash
cd infra/upq
cargo build --release
cargo run -p upq-ingest -- ingest --raw-root ~/upq_data --storage-root ~/upq_storage
STORAGE_ROOT=~/upq_storage cargo run -p upq-service
# http://127.0.0.1:19350
```

## API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/stock` | GET | Stock minute OHLCV data (ISO datetime format) |
| `/stock/daily` | GET | Stock daily OHLCV data (date format) |
| `/option` | GET | Option endpoints metadata |
| `/option/ticker_query` | GET | Query option by OPRA contract |
| `/option/chain_query` | GET | Query option chain by underlying with filters |
| `/rates/query` | GET | Treasury yield curve data |

## Key Concepts

### Date/Time Formats

- **Minute endpoints** (`/stock`): ISO datetime `YYYY-MM-DDTHH:MM:SS`
- **Daily endpoints** (`/stock/daily`, `/rates/query`): Date `YYYY-MM-DD`
- **Option endpoints**: Accept both formats depending on resolution

### Data Types

- **Stock**: Minute and daily OHLCV with volume and transaction counts
- **Options**: Contract-level data with OPRA symbol support, chain queries with strike/expiry/type filters
- **Rates**: Treasury yields for tenors 1M, 3M, 1Y, 2Y, 5Y, 10Y, 30Y

### Workspace Crates

| Crate | Purpose |
|-------|---------|
| `upq-core` | Schema, validation, OPRA parser, SQL builders |
| `upq-service` | Axum API routes and request validation |
| `upq-ingest` | Data ingestion, manifest tracking, idempotency |
| `upq-bench` | Latency/throughput benchmarks |

## Quick Example

```bash
# Stock daily data
curl "http://127.0.0.1:19350/stock/daily?tickers=AAPL&start=2025-01-01&end=2025-01-31"

# Stock minute data
curl "http://127.0.0.1:19350/stock?tickers=AAPL&start=2025-01-06T09:30:00&end=2025-01-06T16:00:00"

# Option chain
curl "http://127.0.0.1:19350/option/chain_query?underlying=NVDA&date=2025-01-15&type=C"

# Treasury yields
curl "http://127.0.0.1:19350/rates/query?start=2025-01-01&end=2025-01-31&tenors=1M,10Y"
```

## Configuration

| Environment Variable | Required | Default | Description |
|---------------------|----------|---------|-------------|
| `STORAGE_ROOT` | Yes | — | Path to ingested Parquet data |
| `PORT` | No | 19350 | Server port |
| `RUST_LOG` | No | info | Log level |

## References

- [OpenAPI Specification](openapi.yaml)
- [Server Implementation](../../infra/upq/)
- [Client Library](../../clients/upq/)
- [Demos](../../demos/upq/)
