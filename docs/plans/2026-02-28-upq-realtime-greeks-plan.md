# UPQ Realtime Greeks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add realtime, on-request Greeks computation for UPQ options endpoints with explicit model semantics, robust fallback behavior, and day/minute-specific time handling.

**Architecture:** Keep raw storage unchanged (`option_day`, `option_minute`, `rates`, `stock_*`). Compute Greeks at query time in `upq-service` after fetching option rows, then enrich response rows. Use BSM (European assumption) for IV inversion + Greeks, with strict metadata and per-row status fields to prevent silent data corruption.

**Tech Stack:** Rust (Axum + DuckDB), existing UPQ datasets, API contract tests, Python MCP wrapper/client docs sync.

---

## Scope and Non-Goals

- In scope (V1):
- `include_greeks` optional query parameter for `/option/chain_query` and `/option/ticker_query`.
- Realtime BSM-European IV + Greeks (`delta`, `gamma`, `theta`, `vega`, `rho`) with explicit units.
- Day/minute-specific `T` calculation.
- Per-row status and metadata fields.
- Out of scope (V1):
- American option pricing model.
- Full dividend term-structure model.
- Cross-request distributed cache.

## API Contract Decisions (Must Freeze Before Coding)

- Model semantics:
- `model = "bsm_european"`.
- `style_assumption = "European"`.
- Dividend semantics:
- `dividend_assumption = "q0"` (V1).
- Bad inversion behavior:
- Do not emit `iv=0` when inversion is invalid.
- Emit `iv=null` and `greek_status` from controlled enum.
- Units:
- `theta_unit = "per_day"`.
- `vega_unit = "per_1pct_vol"`.
- `rho_unit = "per_1pct_rate"`.

---

### Task 1: Define API Surface and Status Enums

**Files:**
- Modify: `infra/upq/crates/upq-service/src/app.rs`
- Modify: `infra/upq/docs/openapi.yaml`
- Modify: `infra/upq/docs/api-usage.md`
- Modify: `docs/upq/README.md`

**Step 1: Extend request params**

- Add optional query params:
- `include_greeks: bool` (default `false`)
- `greek_price_field: close|mid` (V1 accept `close`, reject unsupported)
- `greek_model: bsm` (default `bsm`)

**Step 2: Define response enrich fields**

- For each option row, append:
- `iv`, `delta`, `gamma`, `theta`, `vega`, `rho` (nullable float)
- `greek_status` (string enum)
- `greek_meta` (object: model/style_assumption/dividend_assumption/theta_unit/vega_unit/rho_unit/spot_source/rate_source/t_convention/expiry_anchor)

**Step 3: Define status enum**

- Enum candidates:
- `ok`
- `below_intrinsic`
- `no_bracket`
- `non_finite_input`
- `near_expiry_approx`
- `missing_spot`
- `missing_rate`
- `model_error`

**Step 4: Update OpenAPI and docs**

- Add query params and output schema fields for both endpoints.
- Add explicit warning that BSM here is European-style approximation.
- Freeze unit and time conventions at schema level:
- `theta_unit=per_day`, `vega_unit=per_1pct_vol`, `rho_unit=per_1pct_rate`
- `t_convention=calendar_days_over_365` (V1)
- `expiry_anchor=expiry_date_16_00_ET` (for minute path; day path records day-level anchor)

**Step 5: Commit**

```bash
git add infra/upq/crates/upq-service/src/app.rs infra/upq/docs/openapi.yaml infra/upq/docs/api-usage.md docs/upq/README.md
git commit -m "spec: define realtime greeks API contract and status semantics"
```

---

### Task 2: Implement Core BSM + IV Engine (Pure Function Layer)

**Files:**
- Create: `infra/upq/crates/upq-service/src/greeks.rs`
- Modify: `infra/upq/crates/upq-service/src/app.rs`
- Modify: `infra/upq/crates/upq-service/src/lib.rs` (if module export needed)
- Test: `infra/upq/crates/upq-service/tests/greeks_math_tests.rs`

**Step 1: Write failing math tests (expanded matrix)**

- Cases:
- BSM price forward tests:
- ATM/deep ITM/deep OTM for both call and put (use stable reference vectors).
- Greeks field-by-field assertions:
- `delta/gamma/theta/vega/rho` each with dedicated tolerance (not shared tolerance).
- IV inversion accuracy:
- inversion recovers sigma from synthetic BSM price.
- IV inversion convergence:
- assert convergence iteration count below threshold for normal inputs.
- below-intrinsic returns `iv=null` + `below_intrinsic`.
- near-expiry branch returns finite fields + `near_expiry_approx`.

**Step 2: Implement pure math functions**

- `d1/d2`, price, Greeks, inversion (Brent or bisection fallback).
- Add initial sigma guess (Brenner-Subrahmanyam) for faster solve.
- Ensure theta output is per-day and vega/rho are per-1% units.

**Step 3: Implement guardrails**

- Finite checks on all numeric inputs.
- Bracketing failure returns `no_bracket`.
- No panic path for per-row failures.

**Step 4: Run targeted tests**

```bash
cargo test -p upq-service --test greeks_math_tests -- --nocapture
```

**Step 5: Commit**

```bash
git add infra/upq/crates/upq-service/src/greeks.rs infra/upq/crates/upq-service/tests/greeks_math_tests.rs infra/upq/crates/upq-service/src/app.rs
git commit -m "feat: add BSM European IV and greeks computation core"
```

---

### Task 3: Rates Retrieval and Interpolation TDD (Before Endpoint Integration)

**Files:**
- Create: `infra/upq/crates/upq-service/src/rates_curve.rs` (or equivalent module)
- Modify: `infra/upq/crates/upq-service/src/app.rs`
- Test: `infra/upq/crates/upq-service/tests/rates_curve_tests.rs`

**Step 1: Add failing rates tests with mocked rows**

- Same-date curve load test.
- Interpolation test by `T` (short/mid/long tenor points).
- Clamp test when `T` below min tenor and above max tenor.
- Missing-date behavior test (`missing_rate` status path).

**Step 2: Implement curve loader + interpolator**

- Parse UPQ rates row into tenor curve.
- Implement deterministic interpolation policy (linear in V1).
- Implement clamp and missing-data signaling.

**Step 3: Run targeted tests**

```bash
cargo test -p upq-service --test rates_curve_tests -- --nocapture
```

**Step 4: Commit**

```bash
git add infra/upq/crates/upq-service/src/rates_curve.rs infra/upq/crates/upq-service/tests/rates_curve_tests.rs infra/upq/crates/upq-service/src/app.rs
git commit -m "feat: add rates curve interpolation module for greeks"
```

---

### Task 4: Integrate Day-Level Greeks in `/option/chain_query`

**Files:**
- Modify: `infra/upq/crates/upq-service/src/app.rs`
- Test: `infra/upq/crates/upq-service/tests/api_contract_tests.rs`

**Step 1: Add failing API tests**

- `include_greeks=false` keeps legacy fields unchanged.
- `include_greeks=true` returns greek fields + meta + status.
- invalid model/value returns 400.
- `greek_meta` includes frozen units and time convention fields.

**Step 2: Add data join logic**

- For each option row from chain query:
- Fetch spot from `stock_daily` on same `trade_date`.
- Fetch rates curve from `rates.parquet` on same date.
- Compute `T` from observation date to expiry with day-level convention.

**Step 3: Add per-request caches**

- `HashMap<(ticker,date), spot>`
- `HashMap<date, curve>`
- Avoid repeated DB scans within one request.

**Step 4: Wire row enrichment**

- Keep original fields.
- Append computed fields and status/meta.

**Step 5: Run API tests**

```bash
cargo test -p upq-service --test api_contract_tests option_chain -- --nocapture
```

**Step 6: Commit**

```bash
git add infra/upq/crates/upq-service/src/app.rs infra/upq/crates/upq-service/tests/api_contract_tests.rs
git commit -m "feat: enrich option chain with realtime greeks (day resolution)"
```

---

### Task 5: Integrate Minute-Level Greeks in `/option/ticker_query?resolution=minute`

**Files:**
- Modify: `infra/upq/crates/upq-service/src/app.rs`
- Test: `infra/upq/crates/upq-service/tests/api_contract_tests.rs`

**Step 1: Add failing minute-specific tests**

- minute rows include Greeks when enabled.
- `T` uses `window_start` to expiry `16:00 ET`.
- stock/option minute timestamp misalignment uses tolerance window (e.g., +/- 1 minute).
- missing minute spot fallback path marks `spot_source` and still returns stable output.

**Step 2: Implement minute `T` logic**

- Convert `window_start` ns to UTC instant.
- Resolve expiry anchor as `expiry_date 16:00 America/New_York`.
- `T_floor` set to practical minimum (>= 1 minute equivalent).

**Step 3: Implement spot fallback hierarchy**

- preferred: same timestamp stock minute.
- fallback1: nearest previous minute same day.
- fallback2: stock daily close.
- otherwise: `missing_spot`.

**Step 4: Run tests**

```bash
cargo test -p upq-service --test api_contract_tests option_ticker -- --nocapture
```

**Step 5: Commit**

```bash
git add infra/upq/crates/upq-service/src/app.rs infra/upq/crates/upq-service/tests/api_contract_tests.rs
git commit -m "feat: add realtime greeks for minute option query with ET expiry anchor"
```

---

### Task 6: Documentation and Client/MCP Consistency

**Files:**
- Modify: `clients/upq/client.py`
- Modify: `mcp/server.py`
- Modify: `mcp/README.md`
- Modify: `docs/upq/README.md`
- Modify: `docs/upq/agent-guide.md`

**Step 1: Expose new parameters in client**

- Add optional arguments for `include_greeks`, `greek_model`, `greek_price_field`.

**Step 2: Sync MCP tool signatures**

- Add parameters to `upq_option_chain` and `upq_option_contract` wrappers.
- Correct docstring claim: Greeks are conditional on `include_greeks=true`.

**Step 3: Add usage examples**

- day example with chain.
- minute example with contract query.
- show `greek_status` handling pattern.

**Step 4: Commit**

```bash
git add clients/upq/client.py mcp/server.py mcp/README.md docs/upq/README.md docs/upq/agent-guide.md
git commit -m "docs: expose greeks query parameters and response semantics"
```

---

### Task 7: Validation, Benchmarks, and Launch Guardrails

**Files:**
- Modify: `infra/upq/docs/testing/test-matrix.md`
- Create: `infra/upq/docs/testing/greeks-validation-report.md`

**Step 1: Add acceptance checks**

- Correctness:
- Numeric sanity checks for ITM/OTM/ATM.
- No server 500 on malformed rows.
- Coverage:
- Overall valid greek ratio by endpoint.
- Liquidity-stratified ratio (e.g. `volume > 0`).
- Quantitative gates:
- For liquid rows (`volume > 0`): `greek_status=ok` >= 99%.
- Overall rows: `greek_status=ok` >= 95%.
- Reference cross-check (where sample available): IV absolute error <= 0.01 or relative error <= 1%.

**Step 2: Add performance checks**

- Compare p50/p95 latency with and without `include_greeks`.
- Ensure baseline path unaffected when flag is false.

**Step 3: Run full verification**

```bash
cargo test -p upq-service
```

```bash
cargo test -p upq-core
```

**Step 4: Final commit**

```bash
git add infra/upq/docs/testing/test-matrix.md infra/upq/docs/testing/greeks-validation-report.md
git commit -m "test: add greeks validation matrix and launch guardrails"
```

---

## Risks and Mitigations

- Risk: Users misinterpret Greeks as American-style exact.
- Mitigation: hardcoded `model/style_assumption` metadata and docs warnings.
- Risk: dirty close prices break inversion.
- Mitigation: nullable IV + explicit `greek_status`, no fake zero IV.
- Risk: minute-level time convention drift.
- Mitigation: enforce ET expiry anchor and test fixtures around edge times.

## Rollout Strategy

- Phase 1: behind explicit flag `include_greeks=false` by default.
- Phase 2: dogfood on selected symbols and compare with reference script outputs.
- Phase 3: announce contract as stable and include in MCP examples.

## Open Questions for Leader Sign-Off

- Should V1 include discrete dividend adjustment (`S_adj`) or defer to V1.1?
- Do we need optional `rho` computation toggle for performance?
- Is `theta per_day` the mandatory default for all downstream consumers?
