# UPQ Greeks Test Expansion Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand UPQ Realtime Greeks verification from single-sample numeric checks into a robust unit/regression/smoke suite that covers model correctness, API contracts, edge-case stability, and production smoke checks.

**Architecture:** Keep layered verification. Layer 1 validates pure math (`greeks.rs`, `rates_curve.rs`) with deterministic test vectors and finite-difference sanity. Layer 2 validates API behavior with synthetic parquet fixtures in `api_contract_tests.rs`. Layer 3 validates deployed service with smoke checks against a live endpoint.

**Tech Stack:** Rust (`cargo test`, Axum + DuckDB test fixtures), Python smoke script (`urllib` only), existing UPQ test harness under `infra/upq/crates/upq-service/tests`.

---

## Coverage Matrix (Expanded)

- Instruments:
- High-liquidity equities (`AAPL`, `NVDA`)
- Index ETF (`SPY`)
- High-dividend proxy symbol (for future `q != 0` readiness checks)

- Time buckets:
- 0DTE, 1-7D, 8-30D, 31-180D, 180D+
- Day and minute paths
- DST transition windows (March/November)
- UTC day-boundary minute bars (regression-critical)

- Moneyness buckets:
- Deep ITM, ITM, ATM, OTM, deep OTM

- Failure/guardrail buckets:
- `below_intrinsic`
- `no_bracket`
- `non_finite_input`
- `near_expiry_approx`
- `missing_spot`
- `missing_rate`
- `model_error`

- Contract/API semantics:
- `include_greeks=true/false`
- `greek_meta` fields and unit conventions
- projection behavior with `fields` param

---

## Task 1: Unit Test Expansion (Math + Curve)

**Files:**
- Modify: `infra/upq/crates/upq-service/tests/greeks_math_tests.rs`
- Modify: `infra/upq/crates/upq-service/tests/rates_curve_tests.rs`

**Step 1: Add failing tests for finite-difference Greek sanity**

- Add central-difference checks for:
- `delta ~= dPrice/dS`
- `gamma ~= d2Price/dS2`
- `vega ~= dPrice/dSigma * 0.01`

**Step 2: Add failing tests for IV round-trip matrix**

- Multiple tuples across moneyness/tenor (call + put)
- Assert `price(sigma_true) -> implied_volatility(price) ~= sigma_true`

**Step 3: Add failing tests for near-expiry branch consistency**

- near-expiry with tiny time value returns finite IV and `NearExpiryApprox`
- near-expiry below intrinsic returns `BelowIntrinsic`

**Step 4: Run and verify**

Run:
```bash
cargo test -p upq-service --test greeks_math_tests -- --nocapture
cargo test -p upq-service --test rates_curve_tests -- --nocapture
```

Expected:
- All new tests pass
- No status mapping regressions

---

## Task 2: Regression Test Expansion (API Contract)

**Files:**
- Modify: `infra/upq/crates/upq-service/tests/api_contract_tests.rs`
- Modify: `infra/upq/crates/upq-service/src/app.rs` (only if regression test reveals bug)

**Step 1: Add UTC day-boundary regression (minute path)**

- Fixture:
- `option_minute/trade_date=2025-01-15` row at `2025-01-16 00:10:00 UTC`
- only `stock_daily/rates` for `2025-01-15`

- Assert:
- `include_greeks=true` returns `greek_status=ok`
- `greek_meta.spot_source=stock_daily`
- no `missing_spot` due to UTC-date drift

**Step 2: Add meta-contract assertions**

- Verify minute rows expose:
- `t_convention=minute_precise`
- `expiry_anchor=expiry_date_16_00_ET`

**Step 3: Run and verify**

Run:
```bash
cargo test -p upq-service --test api_contract_tests option_ticker_query_minute -- --nocapture
```

Expected:
- Regression test fails before fix (RED), passes after fix (GREEN)

---

## Task 3: Smoke Test Suite (Live Endpoint)

**Files:**
- Create: `infra/upq/tests/smoke_greeks_api.py`

**Step 1: Implement smoke script (no third-party deps)**

Checks:
- `/health` returns `status=ok`
- chain query with `include_greeks=true` returns non-empty, all rows include `greek_status`
- minute ticker query returns rows with `greek_meta` and finite `iv/delta` for `ok` rows
- aggregate and print status distribution

**Step 2: Add CLI options**

- `--host` default `127.0.0.1`
- `--port` default `19705`
- `--underlying`, `--date`, `--contract` optional overrides

**Step 3: Run against deployed service**

Run (via qlib):
```bash
python3 infra/upq/tests/smoke_greeks_api.py --host 127.0.0.1 --port 19705
```

Expected:
- exit code 0
- printed summary with row counts and status histogram

---

## Acceptance Criteria

- Unit: Extended math suite passes locally.
- Regression: UTC day-boundary minute test prevents trade-date lookup drift.
- Smoke: Live endpoint smoke suite passes on port 19705.
- Documentation: This plan is versioned under `docs/plans` and referenced by future greeks changes.
