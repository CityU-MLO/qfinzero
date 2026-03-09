# UPQ Technical Indicators (MA/EMA/MACD) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add inline technical indicators (MA, EMA, MACD) to the existing UPQ `/stock/daily` endpoint via an optional `indicators` query parameter, plus update the Python client and MCP server.

**Architecture:** New `indicators` param on `/stock/daily` is parsed in the handler, which fetches extra lookback rows before `start` date, computes indicators in a new `indicators.rs` module using post-query JSON mutation (same pattern as `apply_split_adjustment`), then trims rows to the requested date range before returning. All indicators computed from split-adjusted `close` price.

**Tech Stack:** Rust (Axum, DuckDB, serde_json), Python (UPQ client, MCP server)

---

## Task 1: Indicator computation module — `indicators.rs`

**Files:**
- Create: `infra/upq/crates/upq-service/src/indicators.rs`
- Modify: `infra/upq/crates/upq-service/src/lib.rs`
- Test: `infra/upq/crates/upq-service/tests/indicators_tests.rs`

### Step 1: Create `indicators.rs` with parsing + computation functions

The module provides:
- `parse_indicators()` — validates and deduplicates the `indicators` CSV param
- `max_lookback()` — returns how many extra rows are needed before `start`
- `compute_indicators()` — takes `&mut Vec<Value>` rows (already split-adjusted, sorted by ticker+date) and appends indicator columns in-place

```rust
// infra/upq/crates/upq-service/src/indicators.rs

use serde_json::Value;

/// A parsed indicator request.
#[derive(Debug, Clone, PartialEq)]
pub enum Indicator {
    Ma(usize),          // Simple Moving Average with window N
    Ema(usize),         // Exponential Moving Average with window N
    Macd,               // MACD(12, 26, 9) — always returns macd, macd_signal, macd_histogram
}

/// Parse the `indicators` query param CSV string into validated Indicator list.
/// Returns Err with message on invalid indicator names.
///
/// Rules:
/// - Lowercased, deduplicated
/// - `ma_N` where N > 0
/// - `ema_N` where N > 0
/// - `macd` (fixed 12/26/9)
pub fn parse_indicators(csv: &str) -> Result<Vec<Indicator>, String> {
    let mut seen = std::collections::HashSet::new();
    let mut result = Vec::new();

    for raw in csv.split(',') {
        let token = raw.trim().to_lowercase();
        if token.is_empty() {
            continue;
        }
        if !seen.insert(token.clone()) {
            continue; // deduplicate
        }

        if token == "macd" {
            result.push(Indicator::Macd);
        } else if let Some(suffix) = token.strip_prefix("ma_") {
            let n: usize = suffix
                .parse()
                .map_err(|_| format!("invalid indicator: '{raw}' — expected ma_N where N is a positive integer"))?;
            if n == 0 {
                return Err(format!("invalid indicator: '{raw}' — window must be > 0"));
            }
            result.push(Indicator::Ma(n));
        } else if let Some(suffix) = token.strip_prefix("ema_") {
            let n: usize = suffix
                .parse()
                .map_err(|_| format!("invalid indicator: '{raw}' — expected ema_N where N is a positive integer"))?;
            if n == 0 {
                return Err(format!("invalid indicator: '{raw}' — window must be > 0"));
            }
            result.push(Indicator::Ema(n));
        } else {
            return Err(format!(
                "unknown indicator: '{raw}'. Supported: ma_N, ema_N, macd"
            ));
        }
    }

    Ok(result)
}

/// Compute the maximum lookback (number of extra trading days) needed
/// to warm up all requested indicators by `start` date.
///
/// - MA(N): needs N-1 extra rows
/// - EMA(N): needs ~2*N extra rows for convergence
/// - MACD(12,26,9): slow EMA(26) + signal EMA(9) = ~2*26 + 2*9 = 70 rows
pub fn max_lookback(indicators: &[Indicator]) -> usize {
    let mut max = 0usize;
    for ind in indicators {
        let need = match ind {
            Indicator::Ma(n) => *n - 1,
            Indicator::Ema(n) => *n * 2,
            Indicator::Macd => 70,
        };
        if need > max {
            max = need;
        }
    }
    max
}

/// Compute all requested indicators on the rows in-place.
///
/// Rows must be sorted by (ticker, date) and have `close` and `ticker` fields.
/// Indicator columns are appended as `ma_N`, `ema_N`, `macd`, `macd_signal`,
/// `macd_histogram` with null for rows where the window is insufficient.
///
/// Processes each ticker group independently.
pub fn compute_indicators(rows: &mut [Value], indicators: &[Indicator]) {
    if indicators.is_empty() || rows.is_empty() {
        return;
    }

    // Group row indices by ticker
    let groups = group_by_ticker(rows);

    for (_ticker, indices) in &groups {
        // Extract close prices for this ticker
        let closes: Vec<Option<f64>> = indices
            .iter()
            .map(|&i| rows[i].get("close").and_then(|v| v.as_f64()))
            .collect();

        for ind in indicators {
            match ind {
                Indicator::Ma(n) => {
                    let values = compute_sma(&closes, *n);
                    let key = format!("ma_{n}");
                    for (j, &idx) in indices.iter().enumerate() {
                        if let Some(obj) = rows[idx].as_object_mut() {
                            obj.insert(
                                key.clone(),
                                match values[j] {
                                    Some(v) => Value::from(round6(v)),
                                    None => Value::Null,
                                },
                            );
                        }
                    }
                }
                Indicator::Ema(n) => {
                    let values = compute_ema(&closes, *n);
                    let key = format!("ema_{n}");
                    for (j, &idx) in indices.iter().enumerate() {
                        if let Some(obj) = rows[idx].as_object_mut() {
                            obj.insert(
                                key.clone(),
                                match values[j] {
                                    Some(v) => Value::from(round6(v)),
                                    None => Value::Null,
                                },
                            );
                        }
                    }
                }
                Indicator::Macd => {
                    let (macd_line, signal, histogram) = compute_macd(&closes);
                    for (j, &idx) in indices.iter().enumerate() {
                        if let Some(obj) = rows[idx].as_object_mut() {
                            obj.insert(
                                "macd".to_string(),
                                opt_f64_value(macd_line[j]),
                            );
                            obj.insert(
                                "macd_signal".to_string(),
                                opt_f64_value(signal[j]),
                            );
                            obj.insert(
                                "macd_histogram".to_string(),
                                opt_f64_value(histogram[j]),
                            );
                        }
                    }
                }
            }
        }
    }
}

// ── Internal helpers ─────────────────────────────────────────

fn round6(v: f64) -> f64 {
    (v * 1_000_000.0).round() / 1_000_000.0
}

fn opt_f64_value(v: Option<f64>) -> Value {
    match v {
        Some(x) => Value::from(round6(x)),
        None => Value::Null,
    }
}

fn group_by_ticker(rows: &[Value]) -> Vec<(String, Vec<usize>)> {
    let mut groups: Vec<(String, Vec<usize>)> = Vec::new();
    for (i, row) in rows.iter().enumerate() {
        let ticker = row
            .get("ticker")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if let Some(last) = groups.last_mut() {
            if last.0 == ticker {
                last.1.push(i);
                continue;
            }
        }
        groups.push((ticker, vec![i]));
    }
    groups
}

/// Simple Moving Average: average of last N close prices.
fn compute_sma(closes: &[Option<f64>], window: usize) -> Vec<Option<f64>> {
    let n = closes.len();
    let mut result = vec![None; n];

    for i in (window - 1)..n {
        let mut sum = 0.0;
        let mut valid = true;
        for j in (i + 1 - window)..=i {
            match closes[j] {
                Some(v) => sum += v,
                None => {
                    valid = false;
                    break;
                }
            }
        }
        if valid {
            result[i] = Some(sum / window as f64);
        }
    }
    result
}

/// Exponential Moving Average: seed with SMA(N), then apply multiplier 2/(N+1).
fn compute_ema(closes: &[Option<f64>], window: usize) -> Vec<Option<f64>> {
    let n = closes.len();
    let mut result = vec![None; n];
    let multiplier = 2.0 / (window as f64 + 1.0);

    // Find the first valid SMA to seed the EMA
    let seed_sma = compute_sma(closes, window);

    let mut ema_prev: Option<f64> = None;
    for i in 0..n {
        if ema_prev.is_none() {
            // Use SMA as seed
            if let Some(sma) = seed_sma[i] {
                ema_prev = Some(sma);
                result[i] = ema_prev;
            }
        } else if let Some(close) = closes[i] {
            let prev = ema_prev.unwrap();
            let ema = close * multiplier + prev * (1.0 - multiplier);
            ema_prev = Some(ema);
            result[i] = Some(ema);
        }
        // If close is None, keep ema_prev unchanged but output None
    }
    result
}

/// MACD(12, 26, 9): macd_line = EMA(12) - EMA(26), signal = EMA(9) of macd_line,
/// histogram = macd_line - signal.
fn compute_macd(closes: &[Option<f64>]) -> (Vec<Option<f64>>, Vec<Option<f64>>, Vec<Option<f64>>) {
    let n = closes.len();
    let ema_fast = compute_ema(closes, 12);
    let ema_slow = compute_ema(closes, 26);

    // MACD line = EMA(12) - EMA(26)
    let mut macd_line: Vec<Option<f64>> = vec![None; n];
    for i in 0..n {
        if let (Some(fast), Some(slow)) = (ema_fast[i], ema_slow[i]) {
            macd_line[i] = Some(fast - slow);
        }
    }

    // Signal line = EMA(9) of MACD line
    let signal = compute_ema(&macd_line, 9);

    // Histogram = MACD - Signal
    let mut histogram: Vec<Option<f64>> = vec![None; n];
    for i in 0..n {
        if let (Some(m), Some(s)) = (macd_line[i], signal[i]) {
            histogram[i] = Some(m - s);
        }
    }

    (macd_line, signal, histogram)
}
```

### Step 2: Register module in `lib.rs`

Add `pub mod indicators;` to `infra/upq/crates/upq-service/src/lib.rs`.

### Step 3: Write unit tests

```rust
// infra/upq/crates/upq-service/tests/indicators_tests.rs

use upq_service::indicators::{parse_indicators, Indicator, max_lookback, compute_indicators};
use serde_json::json;

#[test]
fn test_parse_valid_indicators() {
    let result = parse_indicators("ma_5, EMA_12, macd").unwrap();
    assert_eq!(result, vec![
        Indicator::Ma(5),
        Indicator::Ema(12),
        Indicator::Macd,
    ]);
}

#[test]
fn test_parse_deduplicates() {
    let result = parse_indicators("ma_5,ma_5,MA_5").unwrap();
    assert_eq!(result, vec![Indicator::Ma(5)]);
}

#[test]
fn test_parse_invalid_indicator() {
    assert!(parse_indicators("rsi_14").is_err());
    assert!(parse_indicators("ma_0").is_err());
    assert!(parse_indicators("ma_abc").is_err());
}

#[test]
fn test_max_lookback() {
    let inds = vec![Indicator::Ma(20), Indicator::Ema(12), Indicator::Macd];
    assert_eq!(max_lookback(&inds), 70); // MACD dominates
}

#[test]
fn test_max_lookback_ma_only() {
    let inds = vec![Indicator::Ma(60)];
    assert_eq!(max_lookback(&inds), 59);
}

#[test]
fn test_compute_sma_basic() {
    // 5 rows, MA(3): first 2 null, then averages
    let mut rows: Vec<serde_json::Value> = (1..=5)
        .map(|i| json!({"ticker": "TEST", "close": i as f64 * 10.0}))
        .collect();

    compute_indicators(&mut rows, &[Indicator::Ma(3)]);

    assert!(rows[0]["ma_3"].is_null());
    assert!(rows[1]["ma_3"].is_null());
    // (10+20+30)/3 = 20.0
    assert_eq!(rows[2]["ma_3"].as_f64().unwrap(), 20.0);
    // (20+30+40)/3 = 30.0
    assert_eq!(rows[3]["ma_3"].as_f64().unwrap(), 30.0);
    // (30+40+50)/3 = 40.0
    assert_eq!(rows[4]["ma_3"].as_f64().unwrap(), 40.0);
}

#[test]
fn test_compute_ema_basic() {
    // EMA(3) on 5 rows: seed with SMA(3) at row 2, then EMA from row 3+
    let mut rows: Vec<serde_json::Value> = (1..=5)
        .map(|i| json!({"ticker": "TEST", "close": i as f64 * 10.0}))
        .collect();

    compute_indicators(&mut rows, &[Indicator::Ema(3)]);

    assert!(rows[0]["ema_3"].is_null());
    assert!(rows[1]["ema_3"].is_null());
    // Seed: SMA(3) of [10,20,30] = 20.0
    assert_eq!(rows[2]["ema_3"].as_f64().unwrap(), 20.0);
    // EMA: 40 * 0.5 + 20 * 0.5 = 30.0
    assert_eq!(rows[3]["ema_3"].as_f64().unwrap(), 30.0);
    // EMA: 50 * 0.5 + 30 * 0.5 = 40.0
    assert_eq!(rows[4]["ema_3"].as_f64().unwrap(), 40.0);
}

#[test]
fn test_compute_macd_returns_three_columns() {
    // Need at least 26 + 9 = 35 rows for MACD signal to appear
    let mut rows: Vec<serde_json::Value> = (1..=50)
        .map(|i| json!({"ticker": "TEST", "close": 100.0 + i as f64}))
        .collect();

    compute_indicators(&mut rows, &[Indicator::Macd]);

    // First ~25 rows: macd should be null (need EMA(26))
    assert!(rows[0]["macd"].is_null());
    assert!(rows[20]["macd"].is_null());

    // Row 25 (index 25): EMA(26) has seeded, macd should be Some
    assert!(rows[25]["macd"].as_f64().is_some());

    // Row 35+: signal should also appear
    assert!(rows[35]["macd_signal"].as_f64().is_some());
    assert!(rows[35]["macd_histogram"].as_f64().is_some());

    // All rows should have all 3 keys (even if null)
    for row in &rows {
        assert!(row.get("macd").is_some());
        assert!(row.get("macd_signal").is_some());
        assert!(row.get("macd_histogram").is_some());
    }
}

#[test]
fn test_compute_multi_ticker() {
    // Two tickers should be computed independently
    let mut rows = vec![
        json!({"ticker": "A", "close": 10.0}),
        json!({"ticker": "A", "close": 20.0}),
        json!({"ticker": "A", "close": 30.0}),
        json!({"ticker": "B", "close": 100.0}),
        json!({"ticker": "B", "close": 200.0}),
        json!({"ticker": "B", "close": 300.0}),
    ];

    compute_indicators(&mut rows, &[Indicator::Ma(3)]);

    // A: (10+20+30)/3 = 20
    assert_eq!(rows[2]["ma_3"].as_f64().unwrap(), 20.0);
    // B: (100+200+300)/3 = 200
    assert_eq!(rows[5]["ma_3"].as_f64().unwrap(), 200.0);
}

#[test]
fn test_empty_rows_no_panic() {
    let mut rows: Vec<serde_json::Value> = vec![];
    compute_indicators(&mut rows, &[Indicator::Ma(5), Indicator::Macd]);
    assert!(rows.is_empty());
}
```

### Step 4: Run tests

```bash
cd infra/upq && cargo test -p upq-service --test indicators_tests -- --nocapture
```

Expected: all 8 tests pass.

### Step 5: Commit

```bash
git add infra/upq/crates/upq-service/src/indicators.rs infra/upq/crates/upq-service/src/lib.rs infra/upq/crates/upq-service/tests/indicators_tests.rs
git commit -m "feat(upq): add indicators module with MA/EMA/MACD computation"
```

---

## Task 2: Wire indicators into `/stock/daily` handler

**Files:**
- Modify: `infra/upq/crates/upq-service/src/app.rs`
- Test: `infra/upq/crates/upq-service/tests/api_contract_tests.rs`

### Step 1: Update `StockQuery` and `stock_daily` handler

In `app.rs`, make these changes:

1. Add `indicators` field to `StockQuery`:

```rust
#[derive(Debug, Deserialize)]
struct StockQuery {
    tickers: String,
    start: String,
    end: String,
    fields: Option<String>,
    limit: Option<usize>,
    indicators: Option<String>,  // NEW: e.g. "ma_5,ema_12,macd"
}
```

2. Add import at top of `app.rs`:

```rust
use crate::indicators::{parse_indicators, max_lookback, compute_indicators};
```

3. Modify the `stock_daily` handler to:
   - Parse `indicators` param (if present)
   - Extend the SQL start date backwards by `max_lookback` trading days
   - After split adjustment, call `compute_indicators`
   - Trim rows to the original `[start, end]` date range

The key change in `stock_daily`:

```rust
async fn stock_daily(
    State(state): State<AppState>,
    Query(params): Query<StockQuery>,
) -> axum::response::Response {
    if validate_date(&params.start).is_err() || validate_date(&params.end).is_err() {
        return invalid_argument("start/end must be date: YYYY-MM-DD");
    }

    let tickers = parse_csv_list(&params.tickers);
    if tickers.is_empty() {
        return invalid_argument("tickers must not be empty");
    }

    // Parse indicators (if any)
    let indicator_list = match params.indicators.as_deref() {
        Some(csv) => match parse_indicators(csv) {
            Ok(list) => list,
            Err(msg) => return invalid_argument(&msg),
        },
        None => vec![],
    };

    // When indicators are requested, ensure close is in projection
    // and extend the query start date for lookback warmup.
    let projection = match parse_stock_daily_projection(params.fields.as_deref()) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };

    let lookback_days = max_lookback(&indicator_list);
    let query_start = if lookback_days > 0 {
        // Extend start backwards by lookback_days calendar days (×1.5 for weekends/holidays)
        let extended_days = (lookback_days as f64 * 1.5).ceil() as i64 + 5;
        extend_date_backwards(&params.start, extended_days)
    } else {
        params.start.clone()
    };

    let dataset_dir = state.storage_root.join("stock_daily");
    if !has_any_parquet_file(&dataset_dir) {
        return (StatusCode::OK, Json(json!([]))).into_response();
    }

    let path_pattern = dataset_dir
        .join("trade_date=*")
        .join("*.parquet")
        .to_string_lossy()
        .to_string();

    let ticker_sql = tickers
        .iter()
        .map(|ticker| sql_quote(ticker))
        .collect::<Vec<String>>()
        .join(", ");

    // If indicators are requested, always include close and ticker in the SQL
    // even if the user's `fields` param didn't ask for them
    let sql_projection = if !indicator_list.is_empty() {
        ensure_fields_for_indicators(&projection)
    } else {
        projection.clone()
    };

    let sql = format!(
        "SELECT {projection} FROM read_parquet('{path}') \
         WHERE ticker IN ({tickers}) AND trade_date >= DATE '{start}' AND trade_date <= DATE '{end}' \
         ORDER BY ticker, trade_date",
        projection = sql_projection,
        path = sql_escape_literal(&path_pattern),
        tickers = ticker_sql,
        start = sql_escape_literal(&query_start),
        end = sql_escape_literal(&params.end),
    );

    match run_sql_json_async(sql).await {
        Ok(mut rows) => {
            apply_split_adjustment(&state.split_calendar, &mut rows);

            if !indicator_list.is_empty() {
                compute_indicators(&mut rows, &indicator_list);
                // Trim lookback rows: only return rows where date >= original start
                rows.retain(|row| {
                    row.get("date")
                        .and_then(|v| v.as_str())
                        .map(|d| d >= params.start.as_str())
                        .unwrap_or(true)
                });
            }

            (StatusCode::OK, Json(Value::Array(rows))).into_response()
        }
        Err(error) => internal_error(error),
    }
}
```

4. Add helper functions:

```rust
/// Extend a YYYY-MM-DD date string backwards by N calendar days.
fn extend_date_backwards(date_str: &str, days: i64) -> String {
    use chrono::NaiveDate;
    let date = NaiveDate::parse_from_str(date_str, "%Y-%m-%d")
        .unwrap_or_else(|_| NaiveDate::from_ymd_opt(2020, 1, 1).unwrap());
    let extended = date - chrono::Duration::days(days);
    extended.format("%Y-%m-%d").to_string()
}

/// Ensure the SQL projection includes `close` and `ticker` fields when indicators are requested.
/// If the projection already has them (or uses *), return as-is.
fn ensure_fields_for_indicators(projection: &str) -> String {
    let lower = projection.to_lowercase();
    let mut result = projection.to_string();

    // Always need close for indicator computation
    if !lower.contains("close") {
        result = format!("{result}, close");
    }
    // Always need ticker for grouping
    if !lower.contains("ticker") {
        result = format!("{result}, ticker");
    }
    // Always need date for trimming lookback rows
    if !lower.contains("date") && !lower.contains("trade_date") {
        result = format!("{result}, trade_date AS date");
    }
    result
}
```

Note: Add `chrono` to `Cargo.toml` if not already present:

```toml
chrono = "0.4"
```

### Step 2: Write API contract tests

Add to `api_contract_tests.rs`:

```rust
#[tokio::test]
async fn test_stock_daily_with_ma_indicator() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;

    // Create 10 days of AAPL data: close = 100, 102, 104, ..., 118
    for i in 0..10 {
        let date = format!("2024-01-{:02}", i + 2); // 2024-01-02 through 2024-01-11
        let close = 100.0 + (i as f64) * 2.0;
        let daily_dir = tmp.path().join("stock_daily").join(format!("trade_date={date}"));
        std::fs::create_dir_all(&daily_dir)?;
        let conn = Connection::open_in_memory()?;
        conn.execute_batch(&format!(
            "COPY (SELECT 'AAPL' AS ticker, {close}::DOUBLE AS open, {close}::DOUBLE AS high, \
             {close}::DOUBLE AS low, {close}::DOUBLE AS close, BIGINT '1000' AS volume, \
             BIGINT '10' AS transactions, DATE '{date}' AS trade_date) \
             TO '{}' (FORMAT PARQUET)",
            daily_dir.join("data.parquet").to_string_lossy().replace('\'', "''")
        ))?;
    }

    let app = upq_service::app::build_router_with_storage_root(tmp.path());

    let req = Request::builder()
        .uri("/stock/daily?tickers=AAPL&start=2024-01-02&end=2024-01-11&indicators=ma_3")
        .body(Body::empty())?;
    let resp = app.oneshot(req).await?;
    assert_eq!(resp.status(), StatusCode::OK);

    let body = axum::body::to_bytes(resp.into_body(), usize::MAX).await?;
    let arr: Vec<Value> = serde_json::from_slice(&body)?;
    assert_eq!(arr.len(), 10);

    // First 2 rows: ma_3 should be null
    assert!(arr[0]["ma_3"].is_null());
    assert!(arr[1]["ma_3"].is_null());

    // Row 2 (third day): MA(3) of [100, 102, 104] = 102.0
    let ma3 = arr[2]["ma_3"].as_f64().unwrap();
    assert!((ma3 - 102.0).abs() < 0.01, "expected 102.0, got {ma3}");

    Ok(())
}

#[tokio::test]
async fn test_stock_daily_with_macd_indicator() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;

    // Create 50 days of linear data
    for i in 0..50 {
        let day = i + 2;
        let date = if day <= 31 {
            format!("2024-01-{day:02}")
        } else {
            format!("2024-02-{:02}", day - 31)
        };
        let close = 100.0 + (i as f64);
        let daily_dir = tmp.path().join("stock_daily").join(format!("trade_date={date}"));
        std::fs::create_dir_all(&daily_dir)?;
        let conn = Connection::open_in_memory()?;
        conn.execute_batch(&format!(
            "COPY (SELECT 'TEST' AS ticker, {close}::DOUBLE AS open, {close}::DOUBLE AS high, \
             {close}::DOUBLE AS low, {close}::DOUBLE AS close, BIGINT '1000' AS volume, \
             BIGINT '10' AS transactions, DATE '{date}' AS trade_date) \
             TO '{}' (FORMAT PARQUET)",
            daily_dir.join("data.parquet").to_string_lossy().replace('\'', "''")
        ))?;
    }

    let app = upq_service::app::build_router_with_storage_root(tmp.path());

    let req = Request::builder()
        .uri("/stock/daily?tickers=TEST&start=2024-01-02&end=2024-02-20&indicators=macd")
        .body(Body::empty())?;
    let resp = app.oneshot(req).await?;
    assert_eq!(resp.status(), StatusCode::OK);

    let body = axum::body::to_bytes(resp.into_body(), usize::MAX).await?;
    let arr: Vec<Value> = serde_json::from_slice(&body)?;
    assert_eq!(arr.len(), 50);

    // All rows should have macd, macd_signal, macd_histogram keys
    for row in &arr {
        assert!(row.get("macd").is_some(), "missing macd key");
        assert!(row.get("macd_signal").is_some(), "missing macd_signal key");
        assert!(row.get("macd_histogram").is_some(), "missing macd_histogram key");
    }

    // Later rows should have non-null values
    assert!(arr[40]["macd"].as_f64().is_some());
    assert!(arr[40]["macd_signal"].as_f64().is_some());

    Ok(())
}

#[tokio::test]
async fn test_stock_daily_invalid_indicator_returns_400() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let daily_dir = tmp.path().join("stock_daily").join("trade_date=2024-01-02");
    std::fs::create_dir_all(&daily_dir)?;
    let conn = Connection::open_in_memory()?;
    conn.execute_batch(&format!(
        "COPY (SELECT 'AAPL' AS ticker, 100.0::DOUBLE AS close, DATE '2024-01-02' AS trade_date) \
         TO '{}' (FORMAT PARQUET)",
        daily_dir.join("data.parquet").to_string_lossy().replace('\'', "''")
    ))?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());

    let req = Request::builder()
        .uri("/stock/daily?tickers=AAPL&start=2024-01-02&end=2024-01-02&indicators=rsi_14")
        .body(Body::empty())?;
    let resp = app.oneshot(req).await?;
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);

    Ok(())
}

#[tokio::test]
async fn test_stock_daily_no_indicators_unchanged() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let daily_dir = tmp.path().join("stock_daily").join("trade_date=2024-01-02");
    std::fs::create_dir_all(&daily_dir)?;
    let conn = Connection::open_in_memory()?;
    conn.execute_batch(&format!(
        "COPY (SELECT 'AAPL' AS ticker, 150.0::DOUBLE AS open, 155.0::DOUBLE AS high, \
         148.0::DOUBLE AS low, 152.0::DOUBLE AS close, BIGINT '5000' AS volume, \
         BIGINT '100' AS transactions, DATE '2024-01-02' AS trade_date) \
         TO '{}' (FORMAT PARQUET)",
        daily_dir.join("data.parquet").to_string_lossy().replace('\'', "''")
    ))?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());

    // Without indicators param — should return normal response
    let req = Request::builder()
        .uri("/stock/daily?tickers=AAPL&start=2024-01-02&end=2024-01-02")
        .body(Body::empty())?;
    let resp = app.oneshot(req).await?;
    assert_eq!(resp.status(), StatusCode::OK);

    let body = axum::body::to_bytes(resp.into_body(), usize::MAX).await?;
    let arr: Vec<Value> = serde_json::from_slice(&body)?;
    assert_eq!(arr.len(), 1);
    // Should NOT have indicator columns
    assert!(arr[0].get("ma_5").is_none());
    assert!(arr[0].get("macd").is_none());

    Ok(())
}
```

### Step 3: Run all tests

```bash
cd infra/upq && cargo test -p upq-service -- --nocapture
```

Expected: all existing tests + 4 new tests pass.

### Step 4: Commit

```bash
git add infra/upq/crates/upq-service/src/app.rs infra/upq/crates/upq-service/tests/api_contract_tests.rs
git commit -m "feat(upq): wire indicators param into /stock/daily endpoint"
```

---

## Task 3: Update Python client and MCP server

**Files:**
- Modify: `clients/upq/client.py`
- Modify: `mcp/server.py`

### Step 1: Add `indicators` param to `UPQClient.stock_daily()`

In `clients/upq/client.py`, update the `stock_daily` method:

```python
def stock_daily(
    self,
    tickers: list[str],
    start: str,
    end: str,
    fields: str = None,
    indicators: str = None,
) -> list[dict]:
    """Query stock daily bars with optional technical indicators.

    Args:
        tickers: List of symbols, e.g. ["AAPL", "MSFT"]
        start: Date string, e.g. "2025-01-06"
        end: Date string, e.g. "2025-01-31"
        fields: Comma-separated fields to return (default: all)
        indicators: Comma-separated indicators, e.g. "ma_5,ema_12,macd"
                    Supported: ma_N (SMA), ema_N (EMA), macd (MACD 12/26/9).
                    All computed from split-adjusted close price.

    Returns:
        List of dicts with ticker, date, OHLCV fields, plus indicator columns
        (e.g. ma_5, ema_12, macd, macd_signal, macd_histogram) when requested.
    """
    params = {
        "tickers": ",".join(tickers),
        "start": start,
        "end": end,
    }
    if fields:
        params["fields"] = fields
    if indicators:
        params["indicators"] = indicators
    return self._get("/stock/daily", params)
```

### Step 2: Update MCP `upq_stock_daily` tool

In `mcp/server.py`, add the `indicators` parameter:

```python
@mcp.tool()
def upq_stock_daily(
    tickers: list[str],
    start: str,
    end: str,
    fields: Optional[str] = None,
    indicators: Optional[str] = None,
) -> str:
    """Query daily OHLCV bars for one or more stocks, with optional technical indicators.

    Args:
        tickers: Stock symbols, e.g. ["AAPL", "NVDA", "SPY"]
        start: Start date "YYYY-MM-DD"
        end: End date "YYYY-MM-DD"
        fields: Comma-separated fields to return, e.g. "date,close,volume"
                Available: ticker, date, open, high, low, close, volume, transactions
        indicators: Comma-separated technical indicators to compute, e.g. "ma_20,ema_12,macd"
                    Supported: ma_N (Simple Moving Average), ema_N (Exponential Moving Average),
                    macd (MACD 12/26/9 — returns macd, macd_signal, macd_histogram columns).
                    All indicators computed from split-adjusted close price.

    Returns:
        JSON list of daily bar objects with indicator columns appended when requested.
    """
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.stock_daily(
            tickers=tickers, start=start, end=end,
            fields=fields, indicators=indicators,
        ))
```

### Step 3: Commit

```bash
git add clients/upq/client.py mcp/server.py
git commit -m "feat: add indicators param to UPQ Python client and MCP tool"
```

---

## Task 4: Update OpenAPI docs

**Files:**
- Modify: `infra/upq/docs/openapi.yaml`

### Step 1: Add `indicators` parameter to `/stock/daily` endpoint

Add the `indicators` query parameter to the existing `/stock/daily` path in `openapi.yaml`:

```yaml
      - name: indicators
        in: query
        required: false
        description: |
          Comma-separated technical indicators to compute on close price.
          Supported: ma_N (Simple Moving Average), ema_N (Exponential Moving Average),
          macd (MACD 12/26/9). Example: "ma_5,ma_20,ema_12,macd".
          All computed from split-adjusted close price. Early rows where window
          is insufficient return null for that indicator.
        schema:
          type: string
          example: "ma_20,ema_12,macd"
```

### Step 2: Commit

```bash
git add infra/upq/docs/openapi.yaml
git commit -m "docs(upq): add indicators param to openapi spec"
```

---

## Task 5: Smoke test on qlib

### Step 1: Push branch, restart UPQ

```bash
git push origin feat/overlay-strategy-backtest
./scripts/test-env.sh -b feat/overlay-strategy-backtest restart upq
```

### Step 2: Verify indicator endpoint

```bash
ssh qlib "curl -s 'http://127.0.0.1:19703/stock/daily?tickers=NVDA&start=2024-11-01&end=2024-12-31&fields=ticker,date,close&indicators=ma_5,ema_12,macd' | python3 -m json.tool | head -40"
```

Expected: JSON array with `close`, `ma_5`, `ema_12`, `macd`, `macd_signal`, `macd_histogram` columns. First few rows may have null for indicators with longer windows.

### Step 3: Verify invalid indicator returns 400

```bash
ssh qlib "curl -sv 'http://127.0.0.1:19703/stock/daily?tickers=NVDA&start=2024-12-01&end=2024-12-31&indicators=rsi_14' 2>&1 | grep '< HTTP'"
```

Expected: `< HTTP/1.1 400 Bad Request`

### Step 4: Verify no regression without indicators

```bash
ssh qlib "curl -s 'http://127.0.0.1:19703/stock/daily?tickers=NVDA&start=2024-12-01&end=2024-12-31&fields=ticker,date,close'"
```

Expected: normal response without any indicator columns.
