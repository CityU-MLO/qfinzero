> 中文: [../../docs/cn/infra/upq/README.md](../../docs/cn/infra/upq/README.md)


# UPQ (Rust Price Query Service)

UPQ serves prices, quotes and option analytics over HTTP from the parquet
stores under `STORAGE_ROOT`. It does not ingest anything itself: the data
pipeline (`qfz-data`) catalogues the vendors' raw files in place and writes the
stores UPQ reads (see `docs/plans/2026-10-20-raw-index-design.md` and the data
setup guide). The QFinZero hub starts UPQ with the right `STORAGE_ROOT`.

## Quick Start

```bash
# 1. Catalogue and convert the raw data (from the repo root)
qfz-data index /data/massive_data /data/databento
qfz-data convert --market us --all

# 2. Build and run
cd infra/upq
cargo build --release -p upq-service
STORAGE_ROOT=/data/qfinzero/upq cargo run --release -p upq-service

# 3. Test
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
| `STORAGE_ROOT` | Yes | - | The parquet stores written by `qfz-data` |
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
- `crates/upq-bench`: latency/throughput benchmark for CSV.GZ baseline vs DuckDB Parquet

## Docs
- **API usage (human & agent):** `docs/api-usage.md`
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
cargo build --release -p upq-service
```

2. Prepare runtime directories:
```bash
sudo mkdir -p /opt/upq/bin /var/lib/upq/storage /var/lib/upq/state
sudo cp target/release/upq-service /opt/upq/bin/
```

3. Build the stores with `qfz-data` (from the repo root):
```bash
qfz-data index /data/massive_data /data/databento
qfz-data convert --market us --all
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
