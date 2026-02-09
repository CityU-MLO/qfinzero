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
