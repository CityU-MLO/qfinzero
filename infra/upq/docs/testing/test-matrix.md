# Test Matrix

Date: 2026-02-09

## Command Matrix

1. `cargo test -p upq-core -p upq-service -p upq-ingest`
- Result: PASS
- Coverage intent: core behavior + API contract smoke + manifest idempotency

2. `cargo fmt --all`
- Result: PASS

3. `cargo clippy --workspace --all-targets --all-features -- -D warnings`
- Result: PASS

4. `cargo test --workspace`
- Result: PASS

5. `cargo test -p upq-bench`
- Result: PASS
- Coverage intent: benchmark statistics and time-range parsing correctness

6. `cargo run -p upq-bench -- --raw-root ./raw_sample --storage-root ./storage --ticker AAPL --start 2025-12-31T09:30:00 --end 2025-12-31T16:00:00 --iterations 20 --warmup 3`
- Result: PASS
- Evidence: benchmark numbers captured in `docs/testing/benchmark-report.md`

## Implemented Test Cases

### `upq-core`
- `validation_tests.rs`
  - invalid resolution rejected
  - unknown fields rejected
  - allowed fields accepted
- `opra_tests.rs`
  - valid OPRA contract parse
  - malformed contract rejected
- `sql_builder_tests.rs`
  - stock SQL contains partition/ticker predicates and limit
  - chain SQL contains single-day and underlying filters
  - tenor projection only includes requested fields

### `upq-service`
- `api_contract_tests.rs`
  - `/stock` accepts valid query
  - `/option/ticker_query` rejects invalid resolution
  - `/rates/query` rejects missing required parameters

### `upq-ingest`
- `manifest_tests.rs`
  - unchanged file gets skipped
  - changed file gets reprocessed
  - mark_error sets status to error
- `ingest_tests.rs`
  - gzip CSV sample ingests into partitioned Parquet
  - option parquet includes both `ticker` and `contract` columns
  - second run skips unchanged files via manifest

### `upq-bench`
- `main.rs` unit tests
  - benchmark time range parsing
- `stats.rs` unit tests
  - percentile and throughput calculations
