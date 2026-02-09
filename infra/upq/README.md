# UPQ (Rust Price Query Service)

UPQ is a Rust implementation of the price query service with API compatibility goals against the Python `price_query_service`.

## Workspace
- `crates/upq-core`: schema/validation/OPRA parser/SQL builders
- `crates/upq-service`: Axum API routes and request validation
- `crates/upq-ingest`: ingest metadata manifest and idempotency utilities
- `crates/upq-bench`: benchmark entry point (placeholder)

## Docs
- Design: `docs/plans/2026-02-09-upq-design.md`
- Implementation plan: `docs/plans/2026-02-09-upq-implementation-plan.md`
- Schemas: `docs/schemas.md`
- Test strategy: `docs/testing/test-strategy.md`
- Test matrix: `docs/testing/test-matrix.md`

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
