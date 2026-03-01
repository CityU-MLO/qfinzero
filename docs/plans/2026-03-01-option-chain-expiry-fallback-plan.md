# Option Chain Expiry Fallback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When `/option/chain_query` receives an exact expiry filter with no rows, automatically fallback to the nearest available expiry and return that chain.

**Architecture:** Keep API shape unchanged and implement fallback in `upq-service` request handling so all callers benefit uniformly. Execute normal exact-filter query first; if empty and exact expiry is requested, run a bounded candidate-expiry lookup and rerun row query with selected fallback expiry.

**Tech Stack:** Rust (Axum + DuckDB), UPQ `option_day` parquet dataset, API contract tests.

---

### Task 1: Lock behavior with failing tests (TDD)

**Files:**
- Modify: `infra/upq/crates/upq-service/tests/api_contract_tests.rs`

**Step 1: Add failing test for exact-expiry fallback to nearest available expiry**
- Build fixture with a trade date containing NVDA options at nearby expiries but missing requested expiry.
- Query with `expiry_min=expiry_max=<missing_expiry>`.
- Assert response is non-empty and returned rows all have selected nearest expiry.

**Step 2: Add failing test for secondary month-range fallback**
- Build fixture where no expiry exists within ±7 days, but one exists in same month.
- Assert fallback returns same-month nearest expiry.

**Step 3: Run focused tests and confirm red**
- Run: `cargo test -p upq-service --test api_contract_tests option_chain_query_falls_back -- --nocapture`
- Expected: FAIL before implementation.

---

### Task 2: Implement service-side fallback logic

**Files:**
- Modify: `infra/upq/crates/upq-service/src/app.rs`

**Step 1: Extract reusable SQL helpers**
- Build helper to execute chain row query from projection + filters.
- Build helper to lookup distinct expiry candidates under base filters and window range.

**Step 2: Implement nearest-expiry selector**
- Parse target expiry and candidate expiries as `NaiveDate`.
- Select candidate with smallest absolute day difference.
- Tie-break: earlier expiry first (stable deterministic behavior).

**Step 3: Wire fallback flow in `option_chain_query`**
- Execute existing exact query first.
- If rows empty and `expiry_min == expiry_max`, try:
- Window 1: `target±7 days`.
- Window 2: calendar month containing target expiry.
- If candidate found, rerun chain query with that expiry and return rows.
- Otherwise keep existing empty response.

**Step 4: Keep all existing filters intact**
- Apply underlying/strike/type filters to fallback candidate scan and final row fetch.

---

### Task 3: Verify and document

**Files:**
- Modify: `infra/upq/docs/api-usage.md`
- Modify: `infra/upq/docs/openapi.yaml`
- Modify: `docs/upq/openapi.yaml`

**Step 1: Run focused and related option-chain tests**
- `cargo test -p upq-service --test api_contract_tests option_chain_query_falls_back -- --nocapture`
- `cargo test -p upq-service --test api_contract_tests option_chain_query -- --nocapture`

**Step 2: Update API docs behavior note**
- Describe exact-expiry empty-result fallback and window policy.
- Clarify that if both windows find no candidates, endpoint still returns `[]`.

**Step 3: Final verification**
- Re-run the above tests and ensure green.
