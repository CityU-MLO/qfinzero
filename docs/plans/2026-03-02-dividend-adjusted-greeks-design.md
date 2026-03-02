# Dividend-Adjusted Greeks Design

**Date:** 2026-03-02
**Branch:** feat/realtime-greeks
**Status:** Approved

## Background

The current BSM Greeks implementation hardcodes `q = 0.0` (no dividend yield). This is explicitly labeled as a V1 simplification (`dividend_assumption: "q0"`). For stocks that pay dividends (AAPL, MSFT, etc.), ignoring dividends introduces meaningful pricing errors, especially for longer-dated options.

## Data Source

A comprehensive dividend dataset exists on the qlib server:

| Property | Value |
|----------|-------|
| Location | `qlib:/home/qlib/news/massive_dividends.sqlite` |
| Records | 264,324 |
| Tickers | 18,215 |
| Date range | 2010-01-05 to 2026-02-28 |
| Data quality | Zero NULL/missing values |
| Key fields | `ticker`, `ex_dividend_date`, `split_adjusted_cash_amount`, `frequency`, `distribution_type` |

## Approach: Discrete Dividend Adjustment

Use the **spot price adjustment** method:

```
S_adj = S - Σ PV(D_i)
      = S - Σ D_i * exp(-r * t_i)

where:
  D_i = split-adjusted dividend amount
  t_i = (ex_div_date_i - obs_date) / 365
  range: ex_div_date ∈ (obs_date, expiry]
```

Then call BSM with `S_adj` instead of `S`, keeping `q = 0.0`. This is more accurate than a continuous yield approximation because it preserves the timing of individual dividend events.

### Why not continuous yield?

- The data is naturally discrete (per-event records), not annualized yields
- Continuous yield loses timing information, causing large errors for short-dated options near ex-dates
- Converting discrete → continuous → back to pricing adds unnecessary approximation

## Design

### 1. Data Pipeline (upq-ingest)

Add **dividends** as the 6th data source alongside stock_daily, stock_minute, option_day, option_minute, and rates.

**Sync:** rsync the SQLite file from qlib to `raw_sample/dividends/massive_dividends.sqlite`

**Ingest:** Use DuckDB's sqlite_scanner extension to read SQLite → write Parquet:

```sql
INSTALL sqlite_scanner;
LOAD sqlite_scanner;

COPY (
    SELECT
        ticker,
        CAST(ex_dividend_date AS DATE) AS ex_dividend_date,
        split_adjusted_cash_amount AS amount
    FROM sqlite_scan('<path>', 'dividends')
    WHERE currency = 'USD'
    ORDER BY ticker, ex_dividend_date
) TO '<output>' (FORMAT PARQUET, COMPRESSION ZSTD);
```

**Output:** `storage/dividends/dividends.parquet`

| Column | Type | Description |
|--------|------|-------------|
| `ticker` | Utf8 | Stock symbol |
| `ex_dividend_date` | Date32 | Ex-dividend date |
| `amount` | Float64 | Split-adjusted cash dividend (USD) |

Filter: only `currency = 'USD'` records are included (209K of 264K).

### 2. Service Layer (upq-service)

New module: `dividends.rs`

```rust
pub struct DividendEvent {
    pub ex_date_days: i32,   // epoch days since 1970-01-01
    pub amount: f64,         // split-adjusted cash amount (USD)
}

pub struct DividendCalendar {
    /// ticker → events sorted by ex_date_days ascending
    events: HashMap<String, Vec<DividendEvent>>,
}

impl DividendCalendar {
    /// Load from Parquet file at startup
    pub fn load(path: &Path) -> Result<Self>;

    /// Empty calendar (fallback when no data file exists)
    pub fn empty() -> Self;

    /// Sum of present values of dividends in (obs_date, expiry]
    /// Returns (pv_sum, dividend_count)
    pub fn pv_dividends(
        &self,
        ticker: &str,
        obs_date_days: i32,
        expiry_days: i32,
        r: f64,
    ) -> (f64, usize);
}
```

**Query algorithm:**
1. Look up ticker in HashMap → O(1)
2. Binary search for first event where `ex_date > obs_date` → O(log n)
3. Binary search for last event where `ex_date <= expiry` → O(log n)
4. Sum PV over the slice → O(k), where k is typically 0–4

**Memory:** ~30–40 MB for 209K USD records.

### 3. Enrichment Integration (app.rs)

In the per-row enrichment loop:

```
Before (V1):
    compute_greeks(close, S, K, T, r, q=0.0, is_call)

After (V1.1):
    (pv_sum, div_count) = calendar.pv_dividends(ticker, obs_days, expiry_days, r)
    S_adj = max(S - pv_sum, 0.01)   // floor to prevent S_adj ≤ 0
    compute_greeks(close, S_adj, K, T, r, q=0.0, is_call)
```

**greeks.rs is unchanged** — the BSM math layer receives `S_adj` as its spot price input.

### 4. API Metadata Update

```json
{
  "greek_meta": {
    "dividend_assumption": "discrete",  // was "q0"
    // ... other fields unchanged
  }
}
```

When a ticker has no dividend data, keep `"dividend_assumption": "q0"`.

### 5. Edge Cases

| Case | Handling |
|------|----------|
| Ticker has no dividend data (e.g., TSLA) | `pv_sum = 0`, `S_adj = S`, `dividend_assumption = "q0"` |
| `S_adj ≤ 0` (extreme dividends) | Floor at `0.01`, set greek_status warning |
| Ex-date equals obs_date | Excluded (open interval on left: `ex_date > obs_date`) |
| Non-USD dividends | Filtered out at ingest stage |
| Dividends parquet file missing | `DividendCalendar::empty()`, service starts normally with q=0 behavior |
| All distribution_types included | recurring + special + irregular + supplemental |

## File Changes

### upq-ingest

| File | Change |
|------|--------|
| `sync_remote.rs` | Add SQLite file sync for dividends |
| `ingest.rs` | Add `ingest_dividends()`: SQLite → Parquet via DuckDB sqlite_scanner |
| `main.rs` | Call `ingest_dividends()` in ingest subcommand |
| `Cargo.toml` | Enable DuckDB sqlite feature if needed |

### upq-service

| File | Change |
|------|--------|
| `lib.rs` | Add `dividends` module |
| **new** `dividends.rs` | `DividendCalendar` struct, Parquet loader, PV query |
| `app.rs` | Load calendar at startup; use `S_adj` in enrichment |

### Tests

| File | Change |
|------|--------|
| **new** `dividends_tests.rs` | Unit tests for DividendCalendar (load, query, PV calc, edge cases) |
| `greeks_math_tests.rs` | Add S_adj scenario tests |
| `ingest_tests.rs` | Add SQLite → Parquet conversion test |
| `api_contract_tests.rs` | Verify `dividend_assumption` metadata field |

### Documentation

| File | Change |
|------|--------|
| `infra/upq/README.md` | Add dividends data source, sync and ingest examples |
| `infra/upq/docs/schemas.md` | Add dividends Parquet schema |
