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
