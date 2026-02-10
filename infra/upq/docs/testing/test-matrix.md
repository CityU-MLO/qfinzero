# Test Matrix

Date: 2026-02-10

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

7. `cargo test -p upq-ingest --test compact_tests`
- Result: PASS
- Coverage intent: partition compaction merges multi-file parquet partitions without data loss

8. `./scripts/validate_server_readonly.sh qlib`
- Result: PASS
- Evidence: `docs/testing/server-readonly-validation.md`

9. `cargo run -p upq-ingest -- compact --storage-root ./storage`
- Result: PASS
- Output: `partitions_scanned=56 partitions_compacted=0` on current 14-day sample storage

10. `cargo test -p upq-service --test api_contract_tests`
- Result: PASS
- Coverage intent: empty `fields` fallback behavior, rates default projection behavior, and `/health` parity endpoint

11. `cargo test -p upq-ingest sync_remote`
- Result: PASS
- Coverage intent: rsync source discovery command path correctness for options day/minute datasets

12. `cargo test -p upq-service --test api_contract_tests option_chain_query_rejects_non_finite_strike_filters`
- Result: PASS
- Coverage intent: reject non-finite numeric filters (`NaN`/`inf`) for chain strike bounds

13. `cargo test -p upq-service --test api_contract_tests rates_cache_retains_recent_entry_when_capacity_exceeded`
- Result: PASS
- Coverage intent: rates cache eviction preserves most-recently-used entries after capacity overflow

14. `cargo test -p upq-ingest --test manifest_tests should_process_treats_canonical_and_dotted_paths_as_same_file`
- Result: PASS
- Coverage intent: manifest path normalization prevents duplicate ingest for equivalent file paths

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
  - empty tenor filter returns full default rates projection

### `upq-service`
- `api_contract_tests.rs`
  - `/stock` accepts valid query
  - `/option/ticker_query` rejects invalid resolution
  - `/rates/query` rejects missing required parameters
  - blank `fields` fallback for `/stock`, `/stock/daily`, `/option/ticker_query`, `/option/chain_query`
  - blank/missing `tenors` fallback returns full rates projection
  - `/health` returns `{"status":"ok"}`
  - non-finite option chain strike filters are rejected with 400
  - rates cache retains recently-used key after crossing capacity boundary

### `upq-ingest`
- `manifest_tests.rs`
  - unchanged file gets skipped
  - changed file gets reprocessed
  - mark_error sets status to error
  - canonical and dotted paths resolve to the same manifest key
- `ingest_tests.rs`
  - gzip CSV sample ingests into partitioned Parquet
  - option parquet includes both `ticker` and `contract` columns
  - second run skips unchanged files via manifest
- `compact_tests.rs`
  - multi-file partition is compacted to a single parquet file
  - compacted output preserves row count
- `sync_remote.rs` unit tests
  - option day/minute remote `find` commands target exact dataset directories (no duplicated path segment)

### `upq-bench`
- `main.rs` unit tests
  - benchmark time range parsing
- `stats.rs` unit tests
  - percentile and throughput calculations
