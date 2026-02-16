# UPQ (Rust Price Query Service)

UPQ is a Rust implementation of the price query service with API compatibility goals against the Python `price_query_service`.

## Quick Start

```bash
# 1. Sync data from qlib server
scp scripts/sync_from_qlib.sh qlib:~/
ssh qlib "./sync_from_qlib.sh"

# 2. Build
cargo build --release

# 3. Ingest data
cargo run -p upq-ingest -- ingest \
  --raw-root ~/upq_data \
  --storage-root ~/upq_storage \
  --manifest ~/upq_state/manifest.sqlite

# 4. Configure environment
cp .env.example .env
# Edit .env to set your STORAGE_ROOT and PORT

# 5. Run service
cargo run -p upq-service

# 6. Test
curl http://127.0.0.1:19350/health
```

## Configuration

Create a `.env` file from `.env.example`:

```bash
cp .env.example .env
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `STORAGE_ROOT` | Yes | - | Path to ingested parquet data directory |
| `PORT` | No | 19350 | Server port to bind |
| `RUST_LOG` | No | info | Log level (trace, debug, info, warn, error) |

Example `.env`:
```bash
PORT=19350
STORAGE_ROOT=/home/qlib/upq_storage
RUST_LOG=info
```

## Workspace
- `crates/upq-core`: schema/validation/OPRA parser/SQL builders
- `crates/upq-service`: Axum API routes and request validation
- `crates/upq-ingest`: ingest metadata manifest and idempotency utilities
- `crates/upq-bench`: latency/throughput benchmark for CSV.GZ baseline vs DuckDB Parquet

## Docs
- Design: `docs/plans/2026-02-09-upq-design.md`
- Implementation plan: `docs/plans/2026-02-09-upq-implementation-plan.md`
- Schemas: `docs/schemas.md`
- Test strategy: `docs/testing/test-strategy.md`
- Test matrix: `docs/testing/test-matrix.md`
- Benchmark report: `docs/testing/benchmark-report.md`
- Server read-only validation: `docs/testing/server-readonly-validation.md`

## Build and Test
```bash
cargo fmt --all
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

## Sync Data from qlib Server

The service requires data from the qlib server. Run the sync script to copy data to the expected directory structure:

```bash
# Copy sync script to qlib server
scp scripts/sync_from_qlib.sh qlib:~/

# Run sync (creates ~/upq_data with ~30GB of data)
ssh qlib "./sync_from_qlib.sh"

# Or test with dry-run first
ssh qlib "./sync_from_qlib.sh --dry-run"
```

Expected output:
- Stock day files: 1003
- Stock minute files: 1003
- Option day files: 543
- Option minute files: 543
- Treasury yields: 1

## Run Service
```bash
cargo run -p upq-service
```
Default bind: `127.0.0.1:19350`

API routes:
- `GET /health`
- `GET /stock`
- `GET /stock/daily`
- `GET /option`
- `GET /option/ticker_query`
- `GET /option/chain_query`
- `GET /rates/query`

## Production Deployment (Concise)
1. Build release binaries:
```bash
cargo build --release -p upq-ingest -p upq-service
```

2. Prepare runtime directories:
```bash
sudo mkdir -p /opt/upq/bin /var/lib/upq/storage /var/lib/upq/state
sudo cp target/release/upq-ingest target/release/upq-service /opt/upq/bin/
```

3. Run one-time ingest (using synced data from ~/upq_data):
```bash
/opt/upq/bin/upq-ingest ingest \
  --raw-root /home/qlib/upq_data \
  --storage-root /var/lib/upq/storage \
  --manifest /var/lib/upq/state/manifest.sqlite
```

4. Run service with storage path:
```bash
STORAGE_ROOT=/var/lib/upq/storage /opt/upq/bin/upq-service
```

5. `systemd` service example (`/etc/systemd/system/upq.service`):
```ini
[Unit]
Description=UPQ Price Query Service
After=network.target

[Service]
Type=simple
Environment=STORAGE_ROOT=/var/lib/upq/storage
ExecStart=/opt/upq/bin/upq-service
Restart=always
RestartSec=3
User=qlib
WorkingDirectory=/opt/upq

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now upq
sudo systemctl status upq
```

6. Health check:
```bash
curl -sS http://127.0.0.1:19350/health
```

Notes:
- Service currently binds `127.0.0.1:19350`; expose externally via reverse proxy if needed.
- Rollback: keep previous binary under `/opt/upq/bin` and restart `upq` service.

## Ingest Sample Data
In this workspace, sample data is expected under `./raw_sample`:
- `raw_sample/stock/day/*.csv.gz`
- `raw_sample/stock/minute/*.csv.gz`
- `raw_sample/options/day/*.csv.gz`
- `raw_sample/options/minute/*.csv.gz`
- `raw_sample/assets/treasury_yields.csv`

Run ingest:
```bash
cargo run -p upq-ingest -- ingest \
  --raw-root ./raw_sample \
  --storage-root ./storage \
  --manifest ./state/manifest.sqlite
```

Compact partition files (merge multiple parquet files in each `trade_date=` partition):
```bash
cargo run -p upq-ingest -- compact --storage-root ./storage
```

## Benchmark
Run stock-minute benchmark against gzip CSV baseline and DuckDB Parquet:
```bash
cargo run -p upq-bench -- \
  --raw-root ./raw_sample \
  --storage-root ./storage \
  --ticker AAPL \
  --start 2025-12-31T09:30:00 \
  --end 2025-12-31T16:00:00 \
  --iterations 20 \
  --warmup 3
```

## Server Read-Only Validation
```bash
./scripts/validate_server_readonly.sh qlib
```
