> 中文: [../../cn/upq/README.md](../../cn/upq/README.md)


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

## Python Client

The UPQ client library (`clients/upq/`) wraps the REST API for clean Python usage.

### Basic Usage

```python
from qfinzero.clients.upq import UPQClient

with UPQClient() as upq:
    # Stock daily bars
    bars = upq.stock_daily(["AAPL", "MSFT"], "2025-01-06", "2025-01-31")
    for bar in bars:
        print(bar["ticker"], bar["date"], bar["close"])

    # Stock minute bars
    bars = upq.stock_minute(["AAPL"], "2025-01-06T09:30:00", "2025-01-06T16:00:00")

    # Option chain
    chain = upq.option_chain("NVDA", "2025-01-06", type="C",
                              strike_min=130, strike_max=150)

    # Specific option contract
    bars = upq.option_contract("O:NVDA250117C00136000",
                                "2025-01-06", "2025-01-17", resolution="day")

    # Treasury yields
    yields = upq.rates("2025-01-02", "2025-01-31", tenors="1M,10Y")
```

### Client API

| Method | Description |
|--------|-------------|
| `stock_daily(tickers, start, end)` | Daily OHLCV bars (date format) |
| `stock_minute(tickers, start, end)` | Minute OHLCV bars (datetime format) |
| `option_chain(underlying, date, ...)` | Option chain with strike/expiry/type filters |
| `option_contract(contract, start, end, resolution)` | Specific contract price data |
| `rates(start, end, tenors)` | Treasury yield curve |
| `health()` | Health check |

### Utilities

```python
# Build OPRA contract ID
UPQClient.make_opra("NVDA", "2025-01-17", "C", 136.0)
# -> "O:NVDA250117C00136000"

# Convert nanosecond timestamp to datetime
UPQClient.ns_to_datetime(1736155800000000000)
# -> datetime(2025, 1, 6, 9, 30, tzinfo=UTC)
```

### Error Handling

```python
from qfinzero.clients.upq import UPQClient, UPQError

try:
    bars = upq.stock_daily(["INVALID"], "bad-date", "2025-01-31")
except UPQError as e:
    print(f"Error: {e}, code={e.code}, status={e.status_code}")
```

### Greeks Computation (Optional)

Both `/option/chain_query` and `/option/ticker_query` support optional realtime BSM-European Greeks computation via `include_greeks=true`.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `include_greeks` | bool | `false` | Enable Greeks computation |
| `greek_model` | string | `bsm` | Pricing model (only `bsm` in V1) |
| `greek_price_field` | string | `close` | Price field for IV inversion (only `close` in V1) |

**Response Fields (when `include_greeks=true`):**
Each option row is enriched with: `iv`, `delta`, `gamma`, `theta`, `vega`, `rho`, `greek_status`, `greek_meta`.

**Greek Status Values:**
- `ok` — Computation succeeded
- `below_intrinsic` — Option price is below intrinsic value, IV cannot be computed
- `no_bracket` — IV solver could not bracket a solution
- `no_convergence` — IV solver did not converge within iteration limit
- `non_finite_input` — Input values contain NaN or infinity
- `near_expiry_approx` — Near-expiry approximation used (may be less accurate)
- `missing_spot` — Spot price not available for this row
- `missing_rate` — Risk-free rate not available for this date
- `model_error` — General model computation error

**Important:** Greeks use European-style BSM approximation. This is an approximation for American-style options. The `greek_meta` field in each response row documents the exact model, conventions, and data sources used.

**Expiry Fallback & Greeks:** When an exact-expiry chain query triggers fallback (no rows for the requested expiry), Greeks are computed using the **actual returned expiry**, not the requested date. Always verify the `expiry` field in response rows to avoid misinterpreting which contract the Greeks belong to.

**Conventions:**
- `theta_unit`: per_day
- `vega_unit`: per_1pct_vol (per 1 percentage point of volatility)
- `rho_unit`: per_1pct_rate (per 1 percentage point of rate)
- `t_convention`: `calendar_days_over_365` (day-level), or `minute_precise` for minute resolution
- `expiry_anchor`: expiry_date_16_00_ET (4:00 PM Eastern Time on expiry date)

**Example with Greeks (curl):**
```bash
# Option chain with Greeks
curl "http://127.0.0.1:19350/option/chain_query?underlying=NVDA&date=2025-01-15&type=C&include_greeks=true"

# Contract history with Greeks
curl "http://127.0.0.1:19350/option/ticker_query?contract=O:NVDA250221C00140000&start=2025-01-06&end=2025-01-17&include_greeks=true"
```

**Example with Greeks (Python):**
```python
with UPQClient() as upq:
    # Chain with Greeks
    chain = upq.option_chain("NVDA", "2025-01-15", type="C",
                              strike_min=130, strike_max=150,
                              include_greeks=True)
    for row in chain:
        if row.get("greek_status") == "ok":
            print(f"K={row['strike']} IV={row['iv']:.4f} "
                  f"delta={row['delta']:.4f} theta={row['theta']:.4f}")
        else:
            print(f"K={row['strike']} status={row['greek_status']}")

    # Contract history with Greeks
    bars = upq.option_contract("O:NVDA250221C00140000",
                                "2025-01-06", "2025-01-17",
                                include_greeks=True)
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
