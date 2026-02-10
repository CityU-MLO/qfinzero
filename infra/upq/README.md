# UPQ (Rust Price Query Service)

UPQ is a Rust implementation of the price query service with API compatibility goals against the Python `price_query_service`.

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

## Run Service
```bash
cargo run -p upq-service
```
Default bind: `127.0.0.1:23333`

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

3. Run one-time ingest (sample or full data):
```bash
/opt/upq/bin/upq-ingest ingest \
  --raw-root /home/qlib/data \
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
curl -sS http://127.0.0.1:23333/health
```

Notes:
- Service currently binds `127.0.0.1:23333`; expose externally via reverse proxy if needed.
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
