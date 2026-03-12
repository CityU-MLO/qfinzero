# Dividend-Adjusted Greeks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add discrete dividend adjustment to BSM Greeks so that `S_adj = S - Σ PV(D_i)` is used instead of raw spot price.

**Architecture:** New `DividendCalendar` struct loaded from Parquet at service startup, queried per-row during enrichment. Ingest pipeline extended to convert SQLite → Parquet. All existing BSM math unchanged; only the spot price input is adjusted.

**Tech Stack:** Rust, DuckDB (with sqlite_scanner for ingest), Parquet, Axum

---

### Task 1: DividendCalendar — Core Struct and PV Query (upq-service)

**Files:**
- Create: `infra/upq/crates/upq-service/src/dividends.rs`
- Modify: `infra/upq/crates/upq-service/src/lib.rs:1-3`
- Test: `infra/upq/crates/upq-service/tests/dividends_tests.rs`

**Step 1: Write the failing tests**

Create `infra/upq/crates/upq-service/tests/dividends_tests.rs`:

```rust
use upq_service::dividends::{DividendCalendar, DividendEvent};

#[test]
fn empty_calendar_returns_zero_pv() {
    let cal = DividendCalendar::empty();
    let (pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    assert_eq!(pv, 0.0);
    assert_eq!(count, 0);
}

#[test]
fn unknown_ticker_returns_zero_pv() {
    let cal = DividendCalendar::from_events(vec![
        ("AAPL".to_string(), DividendEvent { ex_date_days: 19050, amount: 0.25 }),
    ]);
    let (pv, count) = cal.pv_dividends("TSLA", 19000, 19100, 0.05);
    assert_eq!(pv, 0.0);
    assert_eq!(count, 0);
}

#[test]
fn single_dividend_in_range() {
    // obs_date=19000, ex_date=19050 (50 days later), expiry=19100, r=0.05
    let cal = DividendCalendar::from_events(vec![
        ("AAPL".to_string(), DividendEvent { ex_date_days: 19050, amount: 0.25 }),
    ]);
    let (pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    assert_eq!(count, 1);
    let t_i = 50.0 / 365.0;
    let expected = 0.25 * (-0.05 * t_i).exp();
    assert!((pv - expected).abs() < 1e-10, "pv={pv}, expected={expected}");
}

#[test]
fn multiple_dividends_sum_correctly() {
    let cal = DividendCalendar::from_events(vec![
        ("AAPL".to_string(), DividendEvent { ex_date_days: 19030, amount: 0.25 }),
        ("AAPL".to_string(), DividendEvent { ex_date_days: 19060, amount: 0.26 }),
    ]);
    let (pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    assert_eq!(count, 2);
    let pv1 = 0.25 * (-0.05 * 30.0 / 365.0).exp();
    let pv2 = 0.26 * (-0.05 * 60.0 / 365.0).exp();
    assert!((pv - (pv1 + pv2)).abs() < 1e-10);
}

#[test]
fn excludes_dividend_on_obs_date() {
    // ex_date == obs_date should be excluded (open interval on left)
    let cal = DividendCalendar::from_events(vec![
        ("AAPL".to_string(), DividendEvent { ex_date_days: 19000, amount: 0.25 }),
    ]);
    let (pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    assert_eq!(count, 0);
    assert_eq!(pv, 0.0);
}

#[test]
fn includes_dividend_on_expiry_date() {
    // ex_date == expiry should be included (closed interval on right)
    let cal = DividendCalendar::from_events(vec![
        ("AAPL".to_string(), DividendEvent { ex_date_days: 19100, amount: 0.25 }),
    ]);
    let (pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    assert_eq!(count, 1);
}

#[test]
fn excludes_dividends_outside_range() {
    let cal = DividendCalendar::from_events(vec![
        ("AAPL".to_string(), DividendEvent { ex_date_days: 18990, amount: 0.10 }), // before obs
        ("AAPL".to_string(), DividendEvent { ex_date_days: 19050, amount: 0.25 }), // in range
        ("AAPL".to_string(), DividendEvent { ex_date_days: 19200, amount: 0.30 }), // after expiry
    ]);
    let (pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    assert_eq!(count, 1);
    let expected = 0.25 * (-0.05 * 50.0 / 365.0).exp();
    assert!((pv - expected).abs() < 1e-10);
}

#[test]
fn zero_rate_means_no_discounting() {
    let cal = DividendCalendar::from_events(vec![
        ("AAPL".to_string(), DividendEvent { ex_date_days: 19050, amount: 1.00 }),
    ]);
    let (pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.0);
    assert_eq!(count, 1);
    assert!((pv - 1.0).abs() < 1e-10, "at r=0, PV should equal face value");
}

#[test]
fn multiple_tickers_are_independent() {
    let cal = DividendCalendar::from_events(vec![
        ("AAPL".to_string(), DividendEvent { ex_date_days: 19050, amount: 0.25 }),
        ("MSFT".to_string(), DividendEvent { ex_date_days: 19050, amount: 0.75 }),
    ]);
    let (pv_aapl, _) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    let (pv_msft, _) = cal.pv_dividends("MSFT", 19000, 19100, 0.05);
    assert!(pv_msft > pv_aapl, "MSFT dividend is larger");
}
```

**Step 2: Run tests to verify they fail**

Run: `cd infra/upq && cargo test -p upq-service --test dividends_tests 2>&1 | head -20`
Expected: Compilation error — `dividends` module doesn't exist yet.

**Step 3: Write minimal implementation**

Add `pub mod dividends;` to `infra/upq/crates/upq-service/src/lib.rs`.

Create `infra/upq/crates/upq-service/src/dividends.rs`:

```rust
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct DividendEvent {
    pub ex_date_days: i32,
    pub amount: f64,
}

pub struct DividendCalendar {
    events: HashMap<String, Vec<DividendEvent>>,
}

impl DividendCalendar {
    pub fn empty() -> Self {
        Self {
            events: HashMap::new(),
        }
    }

    /// Build from a flat list of (ticker, event) pairs. Sorts internally.
    pub fn from_events(mut items: Vec<(String, DividendEvent)>) -> Self {
        let mut events: HashMap<String, Vec<DividendEvent>> = HashMap::new();
        for (ticker, event) in items.drain(..) {
            events.entry(ticker).or_default().push(event);
        }
        for v in events.values_mut() {
            v.sort_by_key(|e| e.ex_date_days);
        }
        Self { events }
    }

    /// Sum of present values of dividends where ex_date ∈ (obs_date_days, expiry_days].
    /// Returns (pv_sum, dividend_count).
    pub fn pv_dividends(
        &self,
        ticker: &str,
        obs_date_days: i32,
        expiry_days: i32,
        r: f64,
    ) -> (f64, usize) {
        let events = match self.events.get(ticker) {
            Some(e) => e,
            None => return (0.0, 0),
        };
        // First index where ex_date > obs_date_days
        let start = events.partition_point(|e| e.ex_date_days <= obs_date_days);
        // First index where ex_date > expiry_days
        let end = events.partition_point(|e| e.ex_date_days <= expiry_days);

        let slice = &events[start..end];
        let mut pv_sum = 0.0;
        for e in slice {
            let t_i = (e.ex_date_days - obs_date_days) as f64 / 365.0;
            pv_sum += e.amount * (-r * t_i).exp();
        }
        (pv_sum, slice.len())
    }
}
```

**Step 4: Run tests to verify they pass**

Run: `cd infra/upq && cargo test -p upq-service --test dividends_tests -- --nocapture`
Expected: All 9 tests PASS.

**Step 5: Commit**

```bash
git add infra/upq/crates/upq-service/src/dividends.rs \
       infra/upq/crates/upq-service/src/lib.rs \
       infra/upq/crates/upq-service/tests/dividends_tests.rs
git commit -m "feat(upq): add DividendCalendar with PV query and unit tests"
```

---

### Task 2: DividendCalendar — Parquet Loader (upq-service)

**Files:**
- Modify: `infra/upq/crates/upq-service/src/dividends.rs`
- Test: `infra/upq/crates/upq-service/tests/dividends_tests.rs` (append)

**Step 1: Write the failing test**

Append to `dividends_tests.rs`:

```rust
use std::fs;
use duckdb::Connection;
use tempfile::TempDir;

#[test]
fn load_from_parquet_round_trips() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let parquet_path = tmp.path().join("dividends.parquet");

    // Create a test parquet with DuckDB
    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (
            SELECT * FROM (VALUES
                ('AAPL', DATE '2024-02-09', 0.24),
                ('AAPL', DATE '2024-05-10', 0.25),
                ('MSFT', DATE '2024-03-14', 0.75)
            ) AS t(ticker, ex_dividend_date, amount)
        ) TO '{}' (FORMAT PARQUET, COMPRESSION ZSTD)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let cal = DividendCalendar::load(&parquet_path)?;

    // AAPL should have 2 events
    // 2024-02-09 = epoch day 19762, 2024-05-10 = epoch day 19853
    let (pv, count) = cal.pv_dividends("AAPL", 19700, 19900, 0.0);
    assert_eq!(count, 2);
    assert!((pv - 0.49).abs() < 1e-6, "sum of 0.24+0.25=0.49 at r=0, got {pv}");

    // MSFT should have 1 event
    let (_, count) = cal.pv_dividends("MSFT", 19700, 19900, 0.0);
    assert_eq!(count, 1);

    Ok(())
}

#[test]
fn load_missing_file_returns_error() {
    let result = DividendCalendar::load(std::path::Path::new("/nonexistent/dividends.parquet"));
    assert!(result.is_err());
}
```

**Step 2: Run test to verify it fails**

Run: `cd infra/upq && cargo test -p upq-service --test dividends_tests load_from_parquet 2>&1 | head -20`
Expected: Compilation error — `load` method doesn't exist.

**Step 3: Write minimal implementation**

Add to `dividends.rs`:

```rust
use std::path::Path;
use duckdb::Connection;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum DividendError {
    #[error("duckdb error: {0}")]
    Duckdb(#[from] duckdb::Error),
}
```

Add `load` method to `impl DividendCalendar`:

```rust
    /// Load from a Parquet file with columns: ticker (Utf8), ex_dividend_date (Date32), amount (Float64).
    pub fn load(path: &Path) -> Result<Self, DividendError> {
        let conn = Connection::open_in_memory()?;
        let path_literal = path.to_string_lossy().replace('\'', "''");
        let sql = format!(
            "SELECT ticker, \
                    epoch(ex_dividend_date::TIMESTAMP) / 86400 AS ex_date_days, \
                    amount \
             FROM read_parquet('{}') \
             ORDER BY ticker, ex_dividend_date",
            path_literal
        );

        let mut stmt = conn.prepare(&sql)?;
        let mut events: HashMap<String, Vec<DividendEvent>> = HashMap::new();

        let rows = stmt.query_map([], |row| {
            let ticker: String = row.get(0)?;
            let ex_date_days: i64 = row.get(1)?;
            let amount: f64 = row.get(2)?;
            Ok((ticker, ex_date_days as i32, amount))
        })?;

        for row in rows {
            let (ticker, ex_date_days, amount) = row?;
            events
                .entry(ticker)
                .or_default()
                .push(DividendEvent { ex_date_days, amount });
        }

        Ok(Self { events })
    }
```

Add `duckdb` and `thiserror` to `upq-service/Cargo.toml` if not already present (they are already workspace deps).

**Step 4: Run tests to verify they pass**

Run: `cd infra/upq && cargo test -p upq-service --test dividends_tests -- --nocapture`
Expected: All 11 tests PASS.

**Step 5: Commit**

```bash
git add infra/upq/crates/upq-service/src/dividends.rs \
       infra/upq/crates/upq-service/tests/dividends_tests.rs
git commit -m "feat(upq): add DividendCalendar::load from Parquet"
```

---

### Task 3: Integrate DividendCalendar into Enrichment (upq-service)

**Files:**
- Modify: `infra/upq/crates/upq-service/src/app.rs:38-41` (AppState)
- Modify: `infra/upq/crates/upq-service/src/app.rs:137-141` (build_router)
- Modify: `infra/upq/crates/upq-service/src/app.rs:143-164` (build_router_with_storage_root)
- Modify: `infra/upq/crates/upq-service/src/app.rs:1695-1791` (enrich_row_with_greeks)
- Modify: `infra/upq/crates/upq-service/src/app.rs:1666-1693` (null_greek_result)
- Modify: `infra/upq/crates/upq-service/src/app.rs:1072` (enrich_chain_rows_day)
- Modify: `infra/upq/crates/upq-service/src/app.rs:1298` (enrich_ticker_rows_day)
- Modify: `infra/upq/crates/upq-service/src/app.rs:1408` (enrich_ticker_rows_minute)

This is a larger integration task. The key changes are:

**Step 1: Write/update the failing test**

In `infra/upq/crates/upq-service/tests/api_contract_tests.rs`, add a test that verifies `dividend_assumption` can be `"discrete"`. The exact test depends on the existing test structure — check what's there and add a test asserting the metadata field changes when dividend data is present.

For now, write a focused unit test in `dividends_tests.rs`:

```rust
#[test]
fn s_adj_floor_prevents_negative() {
    // If PV of dividends > spot, S_adj should be floored
    let cal = DividendCalendar::from_events(vec![
        ("BIG".to_string(), DividendEvent { ex_date_days: 19050, amount: 50.0 }),
        ("BIG".to_string(), DividendEvent { ex_date_days: 19060, amount: 50.0 }),
    ]);
    let (pv, count) = cal.pv_dividends("BIG", 19000, 19100, 0.0);
    assert_eq!(count, 2);
    // PV = 100 at r=0. If spot=80, then S_adj = max(80-100, 0.01) = 0.01
    let spot = 80.0;
    let s_adj = (spot - pv).max(0.01);
    assert!((s_adj - 0.01).abs() < 1e-10);
}
```

**Step 2: Run test to verify it passes** (this one tests the logic, not integration)

**Step 3: Integrate into app.rs**

The changes to `app.rs` are:

a) Add `DividendCalendar` to `AppState` (line 38):
```rust
use crate::dividends::DividendCalendar;
// ...
pub struct AppState {
    storage_root: PathBuf,
    rates_cache: Arc<RwLock<RatesCache>>,
    dividend_calendar: Arc<DividendCalendar>,
}
```

b) Load calendar in `build_router_with_storage_root` (line 143):
```rust
pub fn build_router_with_storage_root(storage_root: impl Into<PathBuf>) -> Router {
    let storage_root: PathBuf = storage_root.into();
    let dividend_path = storage_root.join("dividends/dividends.parquet");
    let dividend_calendar = if dividend_path.is_file() {
        match DividendCalendar::load(&dividend_path) {
            Ok(cal) => {
                eprintln!("loaded dividend calendar from {}", dividend_path.display());
                Arc::new(cal)
            }
            Err(e) => {
                eprintln!("warning: failed to load dividends: {e}, using empty calendar");
                Arc::new(DividendCalendar::empty())
            }
        }
    } else {
        eprintln!("no dividends parquet found, using empty calendar");
        Arc::new(DividendCalendar::empty())
    };

    let state = AppState {
        storage_root,
        rates_cache: Arc::new(RwLock::new(RatesCache::default())),
        dividend_calendar,
    };
    // ... rest unchanged
}
```

c) Thread `&DividendCalendar` through the enrichment call chain:
- `enrich_chain_rows_day` → receives `&DividendCalendar`, passes `underlying` + `obs_date` + `expiry_date` to `enrich_row_with_greeks`
- `enrich_ticker_rows_day` → same pattern
- `enrich_ticker_rows_minute` → same pattern

d) Update `enrich_row_with_greeks` signature to accept `&DividendCalendar`, `underlying: &str`, `obs_date_days: i32`, `expiry_days: i32`:
```rust
fn enrich_row_with_greeks(
    row: &mut Map<String, Value>,
    spot: f64,
    curve: &RatesCurve,
    t_years: f64,
    is_call: bool,
    dividend_calendar: &DividendCalendar,
    underlying: &str,
    obs_date_days: i32,
    expiry_days: i32,
    spot_source: &'static str,
    t_convention: &'static str,
    expiry_anchor: &'static str,
) {
    // ... existing close/strike/r extraction ...

    let (pv_sum, div_count) = dividend_calendar.pv_dividends(underlying, obs_date_days, expiry_days, r);
    let s_adj = (spot - pv_sum).max(0.01);
    let dividend_assumption = if div_count > 0 { "discrete" } else { "q0" };

    let q = 0.0;
    let (iv_result, greeks_opt) = compute_greeks(close, s_adj, strike, t_years, r, q, is_call);

    let meta = GreekMeta {
        // ...
        dividend_assumption,
        // ...
    };
    // ... rest unchanged
}
```

e) Update `null_greek_result` to accept `dividend_assumption` parameter instead of hardcoding `"q0"`.

f) Convert `NaiveDate` to epoch days helper:
```rust
fn date_to_epoch_days(d: &NaiveDate) -> i32 {
    d.num_days_from_ce() - 719_163 // days from 1970-01-01
}
```

g) Update `GreekMeta.dividend_assumption` from `&'static str` to `&str` with a lifetime, or use `String`. Simplest: keep `&'static str` since `"discrete"` and `"q0"` are both static.

**Step 4: Run full test suite**

Run: `cd infra/upq && cargo test --workspace`
Expected: All existing + new tests PASS.

**Step 5: Commit**

```bash
git add infra/upq/crates/upq-service/src/app.rs \
       infra/upq/crates/upq-service/tests/dividends_tests.rs
git commit -m "feat(upq): integrate DividendCalendar into Greeks enrichment pipeline"
```

---

### Task 4: Ingest Dividends — SQLite to Parquet (upq-ingest)

**Files:**
- Modify: `infra/upq/crates/upq-ingest/src/ingest.rs:39-46` (DatasetKind enum)
- Modify: `infra/upq/crates/upq-ingest/src/ingest.rs:57-127` (run_ingest)
- Modify: `infra/upq/crates/upq-ingest/src/ingest.rs:129-163` (discover_input_files)
- Modify: `infra/upq/crates/upq-ingest/src/ingest.rs:193-205` (ingest_file)
- Test: `infra/upq/crates/upq-ingest/tests/ingest_tests.rs` (append)

**Step 1: Write the failing test**

Append to `infra/upq/crates/upq-ingest/tests/ingest_tests.rs`:

```rust
#[test]
fn ingest_dividends_sqlite_to_parquet() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let raw_root = tmp.path().join("raw_sample");
    let storage_root = tmp.path().join("storage");
    let manifest_path = tmp.path().join("state").join("manifest.sqlite");

    // Create a minimal SQLite dividends database
    let div_dir = raw_root.join("dividends");
    fs::create_dir_all(&div_dir)?;
    let sqlite_path = div_dir.join("massive_dividends.sqlite");

    let sqlite_conn = rusqlite::Connection::open(&sqlite_path)?;
    sqlite_conn.execute_batch(
        "CREATE TABLE dividends (
            ticker TEXT,
            ex_dividend_date TEXT,
            split_adjusted_cash_amount REAL,
            currency TEXT
        );
        INSERT INTO dividends VALUES ('AAPL', '2024-02-09', 0.24, 'USD');
        INSERT INTO dividends VALUES ('AAPL', '2024-05-10', 0.25, 'USD');
        INSERT INTO dividends VALUES ('MSFT', '2024-03-14', 0.75, 'USD');
        INSERT INTO dividends VALUES ('SONY', '2024-06-01', 50.0, 'JPY');",
    )?;
    drop(sqlite_conn);

    let report = run_ingest(&IngestOptions {
        raw_root: raw_root.clone(),
        storage_root: storage_root.clone(),
        manifest_path: manifest_path.clone(),
    })?;
    assert_eq!(report.processed_files, 1); // just the dividends sqlite

    // Verify the output parquet
    let conn = Connection::open_in_memory()?;
    let parquet_path = storage_root.join("dividends/dividends.parquet");
    assert!(parquet_path.is_file(), "dividends parquet should exist");

    let sql = format!(
        "SELECT ticker, CAST(ex_dividend_date AS VARCHAR), amount \
         FROM read_parquet('{}') ORDER BY ticker, ex_dividend_date",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    let mut stmt = conn.prepare(&sql)?;
    let rows: Vec<(String, String, f64)> = stmt
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)))?
        .collect::<Result<_, _>>()?;

    // Should only have USD rows (3), not JPY (1)
    assert_eq!(rows.len(), 3);
    assert_eq!(rows[0].0, "AAPL");
    assert_eq!(rows[0].1, "2024-02-09");
    assert!((rows[0].2 - 0.24).abs() < 1e-6);
    assert_eq!(rows[2].0, "MSFT");

    // Second run should skip (manifest idempotency)
    let second = run_ingest(&IngestOptions {
        raw_root,
        storage_root,
        manifest_path,
    })?;
    assert_eq!(second.processed_files, 0);
    assert_eq!(second.skipped_files, 1);

    Ok(())
}
```

Note: add `rusqlite` to `[dev-dependencies]` of `upq-ingest/Cargo.toml`:
```toml
[dev-dependencies]
flate2 = "1.0"
tempfile.workspace = true
rusqlite.workspace = true
```

**Step 2: Run test to verify it fails**

Run: `cd infra/upq && cargo test -p upq-ingest --test ingest_tests ingest_dividends 2>&1 | head -20`
Expected: FAIL — `Dividends` variant doesn't exist in `DatasetKind`, no `ingest_dividends` function.

**Step 3: Write minimal implementation**

a) Add `Dividends` to `DatasetKind` enum (line 39):
```rust
enum DatasetKind {
    StockDaily,
    StockMinute,
    OptionDay,
    OptionMinute,
    Rates,
    Dividends,
}
```

b) Add dividends discovery in `discover_input_files` (after rates, ~line 153):
```rust
    let dividends_sqlite = raw_root.join("dividends/massive_dividends.sqlite");
    if dividends_sqlite.is_file() {
        out.push(SourceFile {
            dataset: DatasetKind::Dividends,
            path: dividends_sqlite,
        });
    }
```

c) Add match arm in `ingest_file` (line 193):
```rust
    DatasetKind::Dividends => ingest_dividends(conn, storage_root, source),
```

d) Add `ingest_dividends` function:
```rust
fn ingest_dividends(
    conn: &Connection,
    storage_root: &Path,
    source: &SourceFile,
) -> Result<i64, IngestError> {
    let source_literal = sql_escape_literal(source.path.to_string_lossy().as_ref());
    let output_dir = storage_root.join("dividends");
    fs::create_dir_all(&output_dir)?;
    let output = output_dir.join("dividends.parquet");
    let output_literal = sql_escape_literal(output.to_string_lossy().as_ref());

    conn.execute_batch("INSTALL sqlite_scanner; LOAD sqlite_scanner;")?;

    let select_sql = format!(
        "SELECT \
            ticker, \
            CAST(ex_dividend_date AS DATE) AS ex_dividend_date, \
            split_adjusted_cash_amount AS amount \
         FROM sqlite_scan('{source}', 'dividends') \
         WHERE currency = 'USD' \
         ORDER BY ticker, ex_dividend_date",
        source = source_literal,
    );

    write_parquet(conn, &select_sql, &output_literal, &output)?;
    row_count(conn, &output)
}
```

**Step 4: Run tests to verify they pass**

Run: `cd infra/upq && cargo test -p upq-ingest --test ingest_tests -- --nocapture`
Expected: All tests PASS (both old and new).

**Step 5: Commit**

```bash
git add infra/upq/crates/upq-ingest/src/ingest.rs \
       infra/upq/crates/upq-ingest/tests/ingest_tests.rs \
       infra/upq/crates/upq-ingest/Cargo.toml
git commit -m "feat(upq-ingest): add dividends SQLite-to-Parquet ingest pipeline"
```

---

### Task 5: Sync Dividends from Remote (upq-ingest)

**Files:**
- Modify: `infra/upq/crates/upq-ingest/src/sync_remote.rs:21-59` (collect_remote_files)
- Modify: `infra/upq/crates/upq-ingest/src/sync_plan.rs:8-14` (DatasetFileLists)
- Modify: `infra/upq/crates/upq-ingest/src/sync_plan.rs:30-79` (build_sample_sync_plan)

**Step 1: Write the failing test**

Add to `sync_plan_tests.rs` (or create inline in `sync_remote.rs` test module):

In `sync_plan.rs` tests:
```rust
#[test]
fn sync_plan_includes_dividends_file() {
    let lists = DatasetFileLists {
        stock_day: vec!["/data/stock/us_stocks_sip_day_aggs_v1_2025-12-31.csv.gz".into()],
        stock_minute: vec!["/data/stock/us_stocks_sip_minute_aggs_v1_2025-12-31.csv.gz".into()],
        option_day: vec!["/data/us_options_opra/day_aggs_v1/2025/12/2025-12-31.csv.gz".into()],
        option_minute: vec!["/data/us_options_opra/minute_aggs_v1/2025/12/2025-12-31.csv.gz".into()],
        rates_file: Some("/data/assets/treasury_yields.csv".into()),
        dividends_file: Some("/home/qlib/news/massive_dividends.sqlite".into()),
    };

    let plan = build_sample_sync_plan(&lists, 1, "./raw").unwrap();
    let div_items: Vec<_> = plan.iter().filter(|i| i.remote_path.contains("dividends")).collect();
    assert_eq!(div_items.len(), 1);
    assert_eq!(div_items[0].local_dir, "./raw/dividends");
}
```

**Step 2: Run test to verify it fails**

Expected: Compilation error — `dividends_file` field doesn't exist on `DatasetFileLists`.

**Step 3: Write minimal implementation**

a) Add `dividends_file` to `DatasetFileLists` (sync_plan.rs line 8):
```rust
pub struct DatasetFileLists {
    pub stock_day: Vec<String>,
    pub stock_minute: Vec<String>,
    pub option_day: Vec<String>,
    pub option_minute: Vec<String>,
    pub rates_file: Option<String>,
    pub dividends_file: Option<String>,
}
```

b) Add dividends sync item in `build_sample_sync_plan` (after rates, ~line 71):
```rust
    if let Some(div) = lists.dividends_file.as_deref() {
        items.push(SyncItem {
            remote_path: div.to_string(),
            local_dir: format!("{local_root}/dividends"),
        });
    }
```

c) Add dividends file check in `collect_remote_files` (sync_remote.rs, after rates ~line 45):
```rust
    let dividends_path = "/home/qlib/news/massive_dividends.sqlite";
    let dividends_file = if ssh_file_exists(host, dividends_path)? {
        Some(dividends_path.to_string())
    } else {
        None
    };

    Ok(DatasetFileLists {
        // ... existing fields ...
        dividends_file,
    })
```

d) Fix any existing tests that construct `DatasetFileLists` without the new field.

**Step 4: Run tests to verify they pass**

Run: `cd infra/upq && cargo test --workspace`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add infra/upq/crates/upq-ingest/src/sync_remote.rs \
       infra/upq/crates/upq-ingest/src/sync_plan.rs \
       infra/upq/crates/upq-ingest/tests/sync_plan_tests.rs
git commit -m "feat(upq-ingest): add dividends SQLite sync from remote"
```

---

### Task 6: Update Documentation

**Files:**
- Modify: `infra/upq/README.md`
- Modify: `infra/upq/docs/schemas.md`

**Step 1: Update README.md**

In the "Ingest Sample Data" section (~line 173), add:
```markdown
- `raw_sample/dividends/massive_dividends.sqlite`
```

In the "Sync Data from qlib Server" expected output (~line 93), add:
```markdown
- Dividends SQLite: 1
```

**Step 2: Update schemas.md**

Append a new section:

```markdown
### Dividends (`storage/dividends/dividends.parquet`)

Source: `qlib:/home/qlib/news/massive_dividends.sqlite`

Columns:
- `ticker` (Utf8) — Stock symbol
- `ex_dividend_date` (Date32) — Ex-dividend date
- `amount` (Float64) — Split-adjusted cash dividend amount (USD only)

Stored as a single Parquet file. Filtered to `currency = 'USD'` during ingest.
Used by `DividendCalendar` in upq-service for discrete dividend adjustment in Greeks calculations.
```

**Step 3: Commit**

```bash
git add infra/upq/README.md infra/upq/docs/schemas.md
git commit -m "docs(upq): add dividends data source to README and schemas"
```

---

### Task 7: Full Workspace Verification

**Step 1: Run all checks**

```bash
cd infra/upq
cargo fmt --all
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

**Step 2: Fix any issues found**

Address clippy warnings, formatting issues, or test failures.

**Step 3: Final commit (if needed)**

```bash
git add -A
git commit -m "chore(upq): fix clippy warnings and formatting"
```
