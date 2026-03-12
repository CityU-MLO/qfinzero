# Greeks Validation Report

Date: 2026-03-01
Branch: `feat/realtime-greeks`

## Summary

All 86 tests pass across `upq-service` (71) and `upq-core` (15).

| Test Suite | Tests | Status |
|---|---|---|
| `greeks_math_tests.rs` | 26 | PASS |
| `rates_curve_tests.rs` | 12 | PASS |
| `api_contract_tests.rs` | 33 (7 new Greeks) | PASS |
| `upq-core` (all) | 15 | PASS |

## Correctness Checks

### BSM Pricing Accuracy

- ATM call (S=100, K=100, T=1, r=5%, sigma=20%): price=10.4506, matches reference within 0.01
- Put-call parity: C - P = S*exp(-qT) - K*exp(-rT), verified within 1e-8
- Deep ITM/OTM prices are bounded correctly

### IV Round-Trip Accuracy

- Call: sigma=0.25, recovered within 1e-8
- Put: sigma=0.35, recovered within 1e-8
- Convergence verified for 4 diverse parameter sets (ATM/OTM call/put, various T/r/sigma)

### Greeks Sign/Magnitude

| Greek | Call | Put | Verified |
|---|---|---|---|
| Delta | (0, 1) | (-1, 0) | ATM call ~0.637 |
| Gamma | > 0 | > 0 | Call = Put within 1e-10 |
| Theta | < 0 | varies | Per-day units |
| Vega | > 0 | > 0 | Call = Put within 1e-10 |
| Rho | > 0 | < 0 | Per 1% rate |

### Error Status Paths

| Status | Trigger | Test Coverage |
|---|---|---|
| `ok` | Normal computation | Multiple tests |
| `below_intrinsic` | Price < intrinsic | Dedicated test |
| `no_bracket` | No IV solution in [0.001, 10] | Integration logic |
| `non_finite_input` | NaN/Inf/negative price/spot/strike | 2 dedicated tests |
| `near_expiry_approx` | T < 1 minute | Dedicated test |
| `missing_spot` | No stock_daily data for date | API integration test |
| `missing_rate` | No rates data for date | API integration test |
| `model_error` | OPRA parse failure | Handler logic |

## Rates Curve Validation

- 7 tenors parsed from JSON row (1M, 3M, 1Y, 2Y, 5Y, 10Y, 30Y)
- Linear interpolation verified at midpoints and near endpoints
- Boundary clamping at min/max tenor verified
- Null/missing tenor values gracefully skipped
- Percentage-to-decimal conversion (4.53 -> 0.0453) verified

## API Integration Validation

### No Regression When Greeks Disabled

- `include_greeks=false` (default): response contains no `iv`, `delta`, `greek_status` fields
- All 26 pre-existing API tests continue to pass unmodified

### No Server 500 on Malformed Rows

- Missing spot: returns 200 with `greek_status=missing_spot`, `iv=null`
- Missing rates: returns 200 with `greek_status=missing_rate`, `iv=null`
- Invalid model: returns 400 with `invalid_argument`
- Invalid price field: returns 400 with `invalid_argument`

### Response Schema Completeness (include_greeks=true)

Verified fields present in enriched rows:
- `iv`, `delta`, `gamma`, `theta`, `vega`, `rho` (nullable float)
- `greek_status` (string enum)
- `greek_meta.model` = `bsm_european`
- `greek_meta.style_assumption` = `European`
- `greek_meta.dividend_assumption` = `q0`
- `greek_meta.theta_unit` = `per_day`
- `greek_meta.vega_unit` = `per_1pct_vol`
- `greek_meta.rho_unit` = `per_1pct_rate`

## Performance Notes

- Greeks computation is on-request only (`include_greeks=false` by default)
- Baseline query path is unaffected when flag is false (no extra DB lookups)
- Per-request caches for spot and rates avoid redundant DuckDB queries
- BSM computation is pure math (no I/O), ~microseconds per row
- IV inversion via Brent's method typically converges in <20 iterations

## Launch Guardrails

- `include_greeks` defaults to `false` — opt-in only
- Invalid `greek_model` or `greek_price_field` values rejected with 400
- `greek_meta` embedded in every enriched row documents exact model and conventions
- `greek_status` never lies — `iv=null` whenever inversion fails, no fake zeros
- European-style BSM warning documented in README, agent-guide, and OpenAPI spec

## Quantitative Gates (Test Fixture)

For the test fixture data (synthetic parquet with known prices):
- `greek_status=ok` rate: 100% for rows with valid spot + rates data
- IV values: positive and < 10.0 for all `ok` rows
- Delta: within expected bounds for calls (0,1) and puts (-1,0)
