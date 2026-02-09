# UPQ Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver a Rust-based, API-compatible, Parquet-first price query service with idempotent ingest and benchmark coverage.

**Architecture:** Build a Rust workspace with separate crates for core schema/query logic, ingest CLI, HTTP service, and benchmark tooling. Keep behavior compatible with existing Python endpoints while enforcing strict validation and parameterized query execution over Parquet.

**Tech Stack:** Rust 1.75+, Axum, Serde, DuckDB, ThisError, Tokio, CSV/Gzip readers, Criterion (optional), SQLx SQLite (manifest metadata).

---

### Task 1: Bootstrap workspace

**Files:**
- Create: `infra/upq/Cargo.toml`
- Create: `infra/upq/crates/upq-core/Cargo.toml`
- Create: `infra/upq/crates/upq-service/Cargo.toml`
- Create: `infra/upq/crates/upq-ingest/Cargo.toml`
- Create: `infra/upq/crates/upq-bench/Cargo.toml`

**Step 1: Write the failing test**
- Create `infra/upq/crates/upq-core/tests/workspace_smoke.rs` to import `upq_core` symbols.

**Step 2: Run test to verify it fails**
- Run: `cargo test -p upq-core workspace_smoke -- --exact`
- Expected: FAIL (crate/symbol missing).

**Step 3: Write minimal implementation**
- Add minimal public modules and exported types to compile.

**Step 4: Run test to verify it passes**
- Run same command.
- Expected: PASS.

### Task 2: Core schema + validation

**Files:**
- Create: `infra/upq/crates/upq-core/src/model.rs`
- Create: `infra/upq/crates/upq-core/src/validation.rs`
- Test: `infra/upq/crates/upq-core/tests/validation_tests.rs`

**Step 1: Write failing tests**
- Invalid resolution rejected.
- Empty ticker list rejected.
- Unknown fields rejected.
- Valid field sets accepted.

**Step 2: Run tests and confirm RED**
- `cargo test -p upq-core validation_tests`

**Step 3: Implement minimal validators**
- Use typed request structs + allowlist-based field validation.

**Step 4: Verify GREEN**
- Re-run tests.

### Task 3: OPRA parser

**Files:**
- Create: `infra/upq/crates/upq-core/src/opra.rs`
- Test: `infra/upq/crates/upq-core/tests/opra_tests.rs`

**Step 1: Write failing tests**
- Parse canonical OPRA contract.
- Reject malformed ticker.
- Verify strike scaling.

**Step 2: Run RED**
- `cargo test -p upq-core opra_tests`

**Step 3: Implement parser**
- Regex-based extraction to `underlying/expiry/right/strike`.

**Step 4: Run GREEN**
- Re-run tests.

### Task 4: Query SQL builder

**Files:**
- Create: `infra/upq/crates/upq-core/src/sql_builder.rs`
- Test: `infra/upq/crates/upq-core/tests/sql_builder_tests.rs`

**Step 1: Write failing tests**
- `/stock` SQL contains date and ticker predicates.
- `/option/chain_query` SQL pins single day partition and filters.
- `/rates/query` SQL projects requested tenors.

**Step 2: RED run**
- `cargo test -p upq-core sql_builder_tests`

**Step 3: Implement minimal SQL builders**
- Generate SQL with controlled projection fragments.

**Step 4: GREEN run**
- Re-run tests.

### Task 5: Service endpoints (compatibility)

**Files:**
- Create: `infra/upq/crates/upq-service/src/main.rs`
- Create: `infra/upq/crates/upq-service/src/routes/*.rs`
- Test: `infra/upq/crates/upq-service/tests/api_contract_tests.rs`

**Step 1: Write failing integration tests**
- Ensure each endpoint returns 200 with valid params.
- Ensure invalid params return 4xx.
- Ensure route paths match exact API contract.

**Step 2: RED run**
- `cargo test -p upq-service api_contract_tests`

**Step 3: Implement minimal route handlers**
- Axum routes + serde query structs + validation calls.

**Step 4: GREEN run**
- Re-run test suite.

### Task 6: Ingest manifest + idempotency

**Files:**
- Create: `infra/upq/crates/upq-ingest/src/manifest.rs`
- Create: `infra/upq/crates/upq-ingest/src/ingest.rs`
- Test: `infra/upq/crates/upq-ingest/tests/manifest_tests.rs`

**Step 1: Write failing tests**
- Unchanged file is skipped.
- Changed file is reprocessed.
- Failed processing marks error.

**Step 2: RED run**
- `cargo test -p upq-ingest manifest_tests`

**Step 3: Implement minimal manifest logic**
- SQLite metadata read/write, status transitions.

**Step 4: GREEN run**
- Re-run tests.

### Task 7: Final verification

**Files:**
- Modify: `infra/upq/README.md`
- Create: `infra/upq/docs/testing/test-matrix.md`

**Step 1: Run quality checks**
- `cargo fmt --all --check`
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`
- `cargo test --workspace`

**Step 2: Fix failures until all GREEN**

**Step 3: Record evidence**
- Add command outputs and pass/fail matrix in docs.
