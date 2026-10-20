//! Stores read in place from raw files (raw-data index views) vs converted partitions.
//!
//! One test function: `UPQ_IN_PLACE` is process-wide, so the modes run in turn.

use std::convert::Infallible;
use std::fs;
use std::path::Path;

use axum::body::{to_bytes, Body};
use axum::http::{Request, StatusCode};
use duckdb::Connection;
use serde_json::{json, Value};
use tempfile::TempDir;
use tower::util::ServiceExt;

type TestResult = Result<(), Box<dyn std::error::Error>>;

fn unwrap_infallible<T>(result: Result<T, Infallible>) -> T {
    match result {
        Ok(value) => value,
        Err(never) => match never {},
    }
}

fn copy(path: &Path, select: &str) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir)?;
    }
    let conn = Connection::open_in_memory()?;
    conn.execute_batch(&format!(
        "COPY ({select}) TO '{}' (FORMAT PARQUET)",
        path.to_string_lossy().replace('\'', "''")
    ))?;
    Ok(())
}

async fn get(root: &Path, uri: &str) -> Result<(StatusCode, Value), Box<dyn std::error::Error>> {
    let app = upq_service::app::build_router_with_storage_root(root);
    let response = unwrap_infallible(app.oneshot(Request::builder().uri(uri).body(Body::empty())?).await);
    let status = response.status();
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    Ok((status, serde_json::from_slice(&bytes).unwrap_or(Value::Null)))
}

// 2025-01-06 is EST: 09:30 ET = 14:30 UTC
const T0930: i64 = 1_736_173_800_000_000_000;
const MIN: i64 = 60_000_000_000;
const OPRA: &str = "^O:([A-Z]+)[0-9]{0,2}([0-9]{6})([CP])([0-9]{8})$";

/// The converter's option projection (what `qfinzero.index.views` writes as the template).
fn option_template() -> String {
    format!(
        "SELECT CAST(ticker AS VARCHAR) AS ticker, CAST(ticker AS VARCHAR) AS contract, \
         regexp_extract(ticker, '{OPRA}', 1) AS underlying, \
         strptime('20' || regexp_extract(ticker, '{OPRA}', 2), '%Y%m%d')::DATE AS expiry, \
         CAST(regexp_extract(ticker, '{OPRA}', 4) AS DOUBLE) / 1000.0 AS strike, \
         regexp_extract(ticker, '{OPRA}', 3) AS right, CAST(window_start AS BIGINT) AS window_start, \
         CAST(open AS DOUBLE) AS open, CAST(high AS DOUBLE) AS high, CAST(low AS DOUBLE) AS low, \
         CAST(close AS DOUBLE) AS close, CAST(volume AS BIGINT) AS volume, \
         CAST(transactions AS BIGINT) AS transactions, {{trade_date}} AS trade_date \
         FROM {{src}} WHERE regexp_matches(ticker, '{OPRA}')"
    )
}

const STOCK_TEMPLATE: &str = "SELECT CAST(ticker AS VARCHAR) AS ticker, {trade_date} AS trade_date, \
     CAST(open AS DOUBLE) AS open, CAST(high AS DOUBLE) AS high, CAST(low AS DOUBLE) AS low, \
     CAST(close AS DOUBLE) AS close, CAST(volume AS BIGINT) AS volume, \
     CAST(transactions AS BIGINT) AS transactions FROM {src}";
const DATE_EXPR: &str = r"CAST(regexp_extract(filename, '(\d{4}-\d{2}-\d{2})\.parquet$', 1) AS DATE)";

fn option_row(ticker: &str, ws: i64, close: f64, vol: i64) -> String {
    format!(
        "SELECT '{ticker}' AS ticker, '{ticker}' AS contract, 'SPY' AS underlying, DATE '2025-01-17' AS expiry, \
         600.0::DOUBLE AS strike, '{r}' AS \"right\", {ws}::BIGINT AS window_start, {close}::DOUBLE AS open, \
         {close}::DOUBLE AS high, {close}::DOUBLE AS low, {close}::DOUBLE AS close, {vol}::BIGINT AS volume, \
         1::BIGINT AS transactions, \
         DATE '2025-01-06' AS trade_date",
        r = if ticker.contains('C') { "C" } else { "P" }
    )
}

fn fixture() -> Result<TempDir, Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let root = tmp.path();
    let call = "O:SPY250117C00600000";
    let put = "O:SPY250117P00600000";
    let fill = "O:SPY250117C00610000";
    // raw massive minute file: the truth
    copy(
        &root.join("raw/us_options_opra/minute_aggs_v1/2025/01/2025-01-06.parquet"),
        &format!(
            "SELECT * FROM (VALUES ('{call}', 10::BIGINT, 1.5, 1.5, 1.5, 1.5, {t0}::BIGINT, 1::BIGINT), \
             ('{call}', 20, 1.6, 1.6, 1.6, 1.6, {t1}, 2), ('{put}', 5, 2.0, 2.0, 2.0, 2.0, {t0}, 1)) \
             t(ticker, volume, open, close, high, low, window_start, transactions) ORDER BY ticker, window_start",
            t0 = T0930,
            t1 = T0930 + MIN
        ),
    )?;
    let part = root.join("option_minute/trade_date=2025-01-06");
    // a stale converted part (close 9.9) that the raw file replaces, and a Databento fill that stays
    copy(&part.join("part-0000.parquet"), &option_row(call, T0930, 9.9, 1))?;
    copy(&part.join("part-databento-0000.parquet"), &option_row(fill, T0930, 3.0, 7))?;
    let views = root.join("_state/index/views");
    fs::create_dir_all(&views)?;
    fs::write(
        views.join("option_minute.json"),
        json!({"version": 1, "store": "option_minute", "replaces": "part-0000.parquet",
               "template": option_template(), "date_expr": DATE_EXPR,
               "files": {"2025-01-06": root.join("raw/us_options_opra/minute_aggs_v1/2025/01/2025-01-06.parquet")}})
        .to_string(),
    )?;
    // stock daily: raw file only (nothing converted for that date)
    copy(
        &root.join("raw/us_stocks_sip/day_aggs_v1/2025/01/2025-01-06.parquet"),
        "SELECT 'SPY' AS ticker, 100::BIGINT AS volume, 590.0 AS open, 595.0 AS close, 596.0 AS high, \
         589.0 AS low, 1736139600000000000::BIGINT AS window_start, 10::BIGINT AS transactions",
    )?;
    fs::write(
        views.join("stock_daily.json"),
        json!({"version": 1, "store": "stock_daily", "replaces": "part-0000.parquet", "template": STOCK_TEMPLATE,
               "date_expr": DATE_EXPR,
               "files": {"2025-01-06": root.join("raw/us_stocks_sip/day_aggs_v1/2025/01/2025-01-06.parquet")}})
        .to_string(),
    )?;
    Ok(tmp)
}

fn closes(v: &Value) -> Vec<f64> {
    v.as_array().map(|a| a.iter().filter_map(|r| r["close"].as_f64()).collect()).unwrap_or_default()
}

#[tokio::test]
async fn views_replace_the_converted_part_and_keep_other_vendors() -> TestResult {
    let tmp = fixture()?;
    let root = tmp.path();
    let bars = "/option/ticker_query?contract=O:SPY250117C00600000&start=2025-01-06T14:30:00Z&end=2025-01-06T14:40:00Z&resolution=minute";
    let fill = "/option/ticker_query?contract=O:SPY250117C00610000&start=2025-01-06T14:30:00Z&end=2025-01-06T14:40:00Z&resolution=minute";
    let snap = "/option/chain_snapshot?underlying=SPY&at=2025-01-06T15:00:00Z";
    let daily = "/stock/daily?tickers=SPY&start=2025-01-06&end=2025-01-06";

    // converted partitions (the switch is off)
    std::env::remove_var("UPQ_IN_PLACE");
    let (s, v) = get(root, bars).await?;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(closes(&v), vec![9.9], "{v}");
    let (_, v) = get(root, daily).await?;
    assert_eq!(v.as_array().map(Vec::len), Some(0));

    // raw files in place
    std::env::set_var("UPQ_IN_PLACE", "option_minute,stock_daily");
    let (s, v) = get(root, bars).await?;
    assert_eq!(s, StatusCode::OK, "{v}");
    assert_eq!(closes(&v), vec![1.5, 1.6]);
    let (_, v) = get(root, fill).await?;
    assert_eq!(closes(&v), vec![3.0], "the Databento fill part is still read");
    let (s, v) = get(root, snap).await?;
    assert_eq!(s, StatusCode::OK, "{v}");
    let mut chain: Vec<(String, f64, i64)> = v
        .as_array()
        .map(|a| {
            a.iter()
                .map(|r| (r["ticker"].as_str().unwrap_or("").to_string(), r["last"].as_f64().unwrap_or(0.0),
                          r["volume"].as_i64().unwrap_or(0)))
                .collect()
        })
        .unwrap_or_default();
    chain.sort_by(|a, b| a.0.cmp(&b.0));
    assert_eq!(chain, vec![("O:SPY250117C00600000".to_string(), 1.6, 30),
                           ("O:SPY250117C00610000".to_string(), 3.0, 7),
                           ("O:SPY250117P00600000".to_string(), 2.0, 5)]);
    let (_, v) = get(root, daily).await?;
    assert_eq!(closes(&v), vec![595.0]);
    assert_eq!(v[0]["date"], "2025-01-06");

    // a view of a store the switch does not name is ignored
    std::env::set_var("UPQ_IN_PLACE", "stock_daily");
    let (_, v) = get(root, bars).await?;
    assert_eq!(closes(&v), vec![9.9]);
    std::env::remove_var("UPQ_IN_PLACE");
    Ok(())
}
