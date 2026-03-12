# Option Tools & Greeks Audit

**Date:** 2026-03-03
**Status:** Open
**Affected components:** `mcp/server.py`, `clients/upq/client.py`, `infra/upq/crates/upq-service/`

## Context

During agent tool testing, an option trading prompt resulted in 0 trades
(order ACCEPTED but never FILLED). Investigation revealed that **PMB option
simulation is an unfinished feature** — the data prefetch pipeline was never
wired end-to-end. This is a known limitation, not a new bug.

This document focuses on the **option data query tools themselves** and
whether they work correctly, independent of PMB simulation.

---

## Scope

Audit the following tools for correctness:

| Tool | Layer | Function |
|------|-------|----------|
| `upq_option_chain` | MCP → UPQ Client → UPQ Rust | Query full option chain for an underlying on a date |
| `upq_option_contract` | MCP → UPQ Client → UPQ Rust | Query price history for a specific OPRA contract |
| `upq_make_opra` | MCP → UPQ Client (pure) | Build OPRA contract string from components |
| `include_greeks=True` | UPQ Rust (greeks.rs + app.rs enrichment) | BSM IV inversion + Greeks computation |

---

## Tool-by-Tool Analysis

### 1. `upq_make_opra` — OK

**Implementation:** `clients/upq/client.py:272-286` (pure function, no I/O)

```python
@staticmethod
def make_opra(underlying, expiry, right, strike):
    yy, mm, dd = expiry[2:4], expiry[5:7], expiry[8:10]
    strike_int = int(round(strike * 1000))
    return f"O:{underlying}{yy}{mm}{dd}{right}{strike_int:08d}"
```

**Test coverage:** `tests/test_pure_utils.py:17-41` — 6 test cases covering
basic call/put, fractional strike, small/large strike, single-char underlying.

**Verdict:** Working correctly. No issues found.

---

### 2. `upq_option_chain` — OK (tool layer)

**Flow:** `mcp/server.py:124-179` → `clients/upq/client.py:188-244` → UPQ
`GET /option/chain_query`

**MCP tool parameters:**
- `underlying`, `date` (required)
- `expiry_min`, `expiry_max`, `strike_min`, `strike_max`, `option_type` (optional filters)
- `include_greeks`, `greek_model`, `greek_price_field` (optional Greeks)

**Test coverage:**
- `tests/test_mcp_tools.py:76-88` — happy path + Greeks params forwarded
- `tests/test_upq_client.py:133-174` — happy path, all filters, optional params
  omission, Greeks params

**Potential issues:**
- None at the tool/client layer. Parameters are correctly forwarded.
- Correctness of the **Rust query** (SQL, partition pruning) and **Greeks
  enrichment** depends on the UPQ service — see section 5 below.

---

### 3. `upq_option_contract` — OK (tool layer)

**Flow:** `mcp/server.py:182-226` → `clients/upq/client.py:142-186` → UPQ
`GET /option/ticker_query`

**MCP tool parameters:**
- `contract`, `start`, `end` (required)
- `resolution` (default "day")
- `include_greeks`, `greek_model`, `greek_price_field` (optional Greeks)

**Test coverage:**
- `tests/test_mcp_tools.py:90-95` — happy path
- `tests/test_upq_client.py:182-209` — happy path, minute resolution, Greeks params

**Potential issues:**
- None at the tool/client layer.

---

### 4. `include_greeks` — Requires live verification

**Implementation:** `infra/upq/crates/upq-service/src/greeks.rs` (pure math)
+ `app.rs` (enrichment functions)

**Math layer** (`greeks.rs`):
- BSM price: put-call parity verified
- IV inversion: Brent's method with Brenner-Subrahmanyam initial guess
- Greeks: delta, gamma, theta (per day), vega (per 1% vol), rho (per 1% rate)
- Edge cases: near-expiry guard, below-intrinsic, NaN/Inf input
- Test coverage: 22 Rust unit tests covering norm_cdf, BSM price, IV round-trip,
  Greeks ranges, parity relations, edge cases

**Enrichment layer** (`app.rs`):
- `enrich_chain_rows_day()` — for `/option/chain_query` with `include_greeks`
- `enrich_ticker_rows()` → `enrich_ticker_rows_day()` / `enrich_ticker_rows_minute()` —
  for `/option/ticker_query` with `include_greeks`
- Each enrichment function:
  1. Parses the OPRA contract to extract underlying, expiry, strike, right
  2. Looks up spot price from `stock_daily` parquet data
  3. Looks up risk-free rate from `rates` parquet data
  4. Computes T (time to expiry) — calendar days / 365 for day, precise minutes
     for minute resolution
  5. Calls `compute_greeks(market_price, spot, strike, T, r, q=0, is_call)`
  6. Attaches `iv`, `delta`, `gamma`, `theta`, `vega`, `rho`, `greek_status`,
     `greek_meta` to each row

**What is NOT tested at the Python tool layer:**
- The enrichment integration (spot lookup, rates lookup, T calculation) has
  no Python-level HTTP mock tests — only Rust unit tests exist for the math
- The `greek_status` / `greek_meta` fields are not validated in any Python test
- No end-to-end test confirms that the tool returns correct Greeks values for
  known contracts

**Known design limitations (documented in greeks plan):**
- V1 uses `q = 0` (no dividend yield) — documented as `dividend_assumption: "q0"`
- European-style BSM applied to American-style options — documented as approximation
- Dividend-adjusted Greeks (S_adj = S - Σ PV(D_i)) designed but implementation
  status depends on `feat/realtime-greeks` branch

---

## 5. PMB Option Simulation — Unfinished Feature

**This section documents why PMB option trading doesn't work, for reference.
It is NOT a bug in the option query tools.**

### Status

PMB's README (`infra/pmb/README.md:40`) lists "Assets: Stocks + Options (OPRA
contracts)" as a feature. The code skeleton exists:

- `pmb_buy_option` / `pmb_sell_option` MCP tools exist and accept orders
- `execution_engine._get_bar_for_order()` has an OPTION branch
- `Instrument.instrument_id()` returns `OPTION:{contract}` format
- Order manager accepts and tracks option orders

However, the **data pipeline is broken**:

1. `pmb_create_session(option_universe=["NVDA"])` — docstring says to pass
   underlying symbols
2. `session_service.py:89-101` treats each `option_universe` entry as a full
   OPRA contract string and passes it to `upq.get_option_daily_bars(contract, ...)`
3. UPQ queries `WHERE ticker = 'NVDA'` — returns 0 rows (option tickers are
   OPRA format)
4. Cache is empty → execution engine finds no bars → orders never fill

The `covered_call.py` demo (`infra/pmb/demos/covered_call.py`) acknowledges
this limitation with a fallback to simulated premiums (line 332-343) and a
comment (line 15): `If actual option data is unavailable from UPQ, it will
track stock only.`

### What's needed to complete option simulation

This requires architectural design work, not a simple fix:
- Options have a many-to-one relationship with underlyings (one stock →
  hundreds of contracts)
- Agent workflow is inherently dynamic: observe price → query chain → select
  contract → trade
- PMB's static prefetch model assumes all instruments are known at session
  creation
- A mechanism for dynamic contract registration or lazy loading is needed

---

## 6. Live Verification Results

All 5 tests were executed against the live UPQ service on qlib. Results below.

### Test 1 & 3: Option chain (with and without Greeks) — PASS

- Returned 25 contracts for NVDA calls, strike 170-190, expiry 2026-01-16
- Close prices monotonically decrease with strike ($19.40 at 170 → $4.95 at 190)
- Round-number strikes (175, 180, 185, 190) show highest volume — consistent
  with real market behavior
- All 25 rows returned `greek_status: "ok"`
- Greeks sanity checks (NVDA close on 2025-12-29 = $188.22):
  - ATM (strike 188): delta=0.531, near 0.5 — correct
  - Delta monotonically decreasing with strike (0.893 → 0.474) — correct
  - Gamma peaks near ATM (0.028 at 188-189) — correct
  - Theta negative for all contracts (-0.099 to -0.169) — correct
  - Vega positive, peaks near ATM (0.167 at 189) — correct
  - Rho positive for calls (0.042 to 0.073) — correct
  - IV range 0.336-0.390 (33-39%), reasonable for NVDA — correct
  - Slight IV skew: higher IV for lower strikes — consistent with equity skew

### Test 4: Contract history with Greeks — PASS

Contract `O:NVDA260116C00179000` from 2025-12-26 to 2025-12-31:

| Date (actual) | Close | IV | Delta | Theta | Status |
|---------------|-------|----|-------|-------|--------|
| 2025-12-26 (Fri) | 14.17 | 0.372 | 0.779 | -0.134 | ok |
| 2025-12-29 (Mon) | 11.75 | 0.355 | 0.758 | -0.142 | ok |
| 2025-12-30 (Tue) | 11.24 | 0.366 | 0.742 | -0.154 | ok |
| 2025-12-31 (Wed) | 10.39 | 0.371 | 0.722 | -0.165 | ok |

- 4 rows returned, all trading days (no weekends) — correct
- Delta decreasing as NVDA drops further from strike — correct
- Theta magnitude increasing as expiry approaches — correct

**Note:** The playground LLM agent displayed these 4 rows with incorrect dates
(12/26, 12/27, 12/28, 12/29 instead of 12/26, 12/29, 12/30, 12/31). This is
an **LLM presentation error**, not a data issue — see section 7.

### Test 5: make_opra round-trip — PASS (verified via Test 4)

`upq_make_opra("NVDA", "2026-01-16", "C", 179.0)` produces
`"O:NVDA260116C00179000"`, which was successfully used in Test 4 to query data.

---

## 7. Playground Agent Date Display Bug

**Severity:** Low — cosmetic presentation issue in LLM output, no data corruption
**Affected component:** Playground LLM agent (presentation layer)

### Symptoms

When the playground agent displays `upq_option_contract` results, it assigns
**consecutive calendar dates** instead of converting the `window_start`
nanosecond timestamps to actual dates.

Example for contract `O:NVDA260116C00179000`, 2025-12-26 to 2025-12-31:

| Row | Agent displayed | Actual date | window_start (ns) |
|-----|----------------|-------------|-------------------|
| 1 | 2025-12-26 | 2025-12-26 (Fri) | 1766725200000000000 |
| 2 | **2025-12-27** | **2025-12-29 (Mon)** | 1766984400000000000 |
| 3 | **2025-12-28** | **2025-12-30 (Tue)** | 1767070800000000000 |
| 4 | **2025-12-29** | **2025-12-31 (Wed)** | 1767157200000000000 |

The agent assumed rows are consecutive days and filled in 12/27 (Sat) and
12/28 (Sun), which are non-trading days. The underlying data is correct —
verified by querying UPQ directly and converting `window_start` timestamps.

### Root cause

The `option_day` response rows contain `window_start` (nanosecond epoch) but
no human-readable `date` field. The stock daily endpoint returns a `date`
string field, but the option daily endpoint does not — the date is only
available via `window_start` conversion or the `trade_date` partition column
(which is not included in query results by default).

The LLM agent does not call `upq_ns_to_iso` to convert timestamps, and
instead guesses dates based on the query range.

### Possible fixes (for a future branch)

1. **Add a `date` field to option day responses** — similar to how
   `/stock/daily` returns a `date` string. This would make the data
   self-documenting and eliminate the need for timestamp conversion.
2. **Include `trade_date` in default fields** — the partition column exists
   in the parquet data but is not projected by default.
3. **Improve system prompt** — instruct the agent to use `upq_ns_to_iso()`
   for any `window_start` values before displaying dates.

---

## Recommended Verification

To verify the option query tools and Greeks work correctly end-to-end, run
the following manual checks against the live UPQ service:

### Test 1: Option chain query

```
upq_option_chain(
    underlying="NVDA",
    date="2025-12-29",
    expiry_min="2026-01-16",
    expiry_max="2026-01-16",
    strike_min=170,
    strike_max=190,
    option_type="C"
)
```

**Verify:** Returns non-empty list of contracts with ticker, close, strike,
expiry, volume fields.

### Test 2: Option contract price history

```
upq_option_contract(
    contract="O:NVDA260116C00179000",
    start="2025-12-26",
    end="2025-12-31",
    resolution="day"
)
```

**Verify:** Returns daily bars with close, open, high, low, volume.

### Test 3: Option chain with Greeks

```
upq_option_chain(
    underlying="NVDA",
    date="2025-12-29",
    expiry_min="2026-01-16",
    expiry_max="2026-01-16",
    strike_min=170,
    strike_max=190,
    option_type="C",
    include_greeks=True,
    greek_model="bsm",
    greek_price_field="close"
)
```

**Verify:**
- Each row has `iv`, `delta`, `gamma`, `theta`, `vega`, `rho` fields
- `greek_status` is `"ok"` for liquid contracts
- `greek_meta` includes `model`, `dividend_assumption`, `spot_source`, etc.
- Delta values for ATM calls are near 0.5
- IV values are in a reasonable range (0.2 - 1.0 for typical equities)
- Theta is negative
- Vega and gamma are positive

### Test 4: Contract history with Greeks

```
upq_option_contract(
    contract="O:NVDA260116C00179000",
    start="2025-12-26",
    end="2025-12-31",
    resolution="day",
    include_greeks=True,
    greek_model="bsm"
)
```

**Verify:** Each bar has Greeks attached, values change day-to-day as T
decreases and spot moves.

### Test 5: make_opra round-trip

```
opra = upq_make_opra("NVDA", "2026-01-16", "C", 179.0)
# Should return "O:NVDA260116C00179000"

bars = upq_option_contract(opra, "2025-12-26", "2025-12-31")
# Should return non-empty if data exists
```

**Verify:** The OPRA string produced by `make_opra` is accepted by
`option_contract` and returns data.
