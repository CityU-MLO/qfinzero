# UPQ Test Strategy

## Principles
- Spec-driven: tests derive from API/data contracts in docs.
- TDD: write failing tests first, verify failure reason, then minimal implementation.
- Compatibility-first: compare Rust behavior to existing Python contract.

## Test Layers
1. Unit tests (`upq-core`)
- validation
- OPRA parsing
- SQL fragment construction

2. Service integration tests (`upq-service`)
- endpoint path/query compatibility
- status code behavior
- error payload shape

3. Ingest tests (`upq-ingest`)
- manifest transitions (`pending/done/error`)
- idempotent skip/rebuild logic

4. Benchmark smoke (`upq-bench`)
- local 14-day sample latency/throughput capture

## Contract Assertions
- `/stock`, `/stock/daily`, `/option/ticker_query`, `/option/chain_query`, `/rates/query` exist.
- Required query params enforced.
- `resolution` only supports `day` and `minute`.
- `fields` must be allowlisted.
- rates policy returns only raw source dates.

## Target Commands
- `cargo test -p upq-core`
- `cargo test -p upq-service`
- `cargo test -p upq-ingest`
- `cargo test --workspace`
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`
