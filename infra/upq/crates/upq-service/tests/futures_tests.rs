//! Futures endpoints: CME session partitions, `roots=`, the 17:00 ET daily close.

use std::convert::Infallible;
use std::fs;
use std::path::Path;

use axum::body::{to_bytes, Body};
use axum::http::{Request, StatusCode};
use duckdb::Connection;
use serde_json::Value;
use tempfile::TempDir;
use tower::util::ServiceExt;

type TestResult = Result<(), Box<dyn std::error::Error>>;

fn unwrap_infallible<T>(result: Result<T, Infallible>) -> T {
    match result {
        Ok(value) => value,
        Err(never) => match never {},
    }
}

fn write(dir: &Path, select: &str) -> Result<(), Box<dyn std::error::Error>> {
    fs::create_dir_all(dir)?;
    let path = dir.join("part-databento-0000.parquet");
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

fn tickers(v: &Value) -> Vec<String> {
    v.as_array()
        .map(|a| a.iter().filter_map(|r| r["ticker"].as_str().map(String::from)).collect())
        .unwrap_or_default()
}

// 2025-01-02 (EST): 23:30 UTC on 01-01 = 18:30 ET, the first hour of session 2025-01-02
const EVE: i64 = 1_735_774_200_000_000_000;
// 14:30 UTC = 09:30 ET on 2025-01-02
const T0930: i64 = 1_735_828_200_000_000_000;

fn fixture() -> Result<TempDir, Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let m = tmp.path().join("future_minute/trade_date=2025-01-02");
    write(
        &m,
        &format!(
            "SELECT * FROM (VALUES \
             ('ZN', 'ZN', {EVE}::BIGINT, 110.0, 110.0, 110.0, 110.0, 5::BIGINT, 1::BIGINT, DATE '2025-01-02'), \
             ('ZN', 'ZN', {T0930}::BIGINT, 110.5, 110.5, 110.5, 110.5, 7::BIGINT, 2::BIGINT, DATE '2025-01-02'), \
             ('ZNH5', 'ZN', {T0930}::BIGINT, 110.4, 110.4, 110.4, 110.4, 3::BIGINT, 1::BIGINT, DATE '2025-01-02'), \
             ('CL', 'CL', {T0930}::BIGINT, 72.0, 72.0, 72.0, 72.0, 9::BIGINT, 3::BIGINT, DATE '2025-01-02')) \
             t(ticker, root, window_start, open, high, low, close, volume, transactions, trade_date)"
        ),
    )?;
    write(
        &tmp.path().join("future_daily/trade_date=2025-01-02"),
        "SELECT ticker, root, trade_date, open::DOUBLE AS open, high::DOUBLE AS high, low::DOUBLE AS low, \
         close::DOUBLE AS close, settle::DOUBLE AS settle, volume, transactions FROM (VALUES \
         ('ZN', 'ZN', DATE '2025-01-02', 110.0, 110.6, 109.9, 110.5, 110.5, 12::BIGINT, 3::BIGINT)) \
         t(ticker, root, trade_date, open, high, low, close, settle, volume, transactions)",
    )?;
    write(
        &tmp.path().join("future_quote_minute/trade_date=2025-01-02"),
        &format!(
            "SELECT ticker, root, window_start, bid_price::DOUBLE AS bid_price, ask_price::DOUBLE AS ask_price, \
             bid_size, ask_size, trade_date FROM (VALUES \
             ('ZN', 'ZN', {T0930}::BIGINT, 110.484375, 110.5, 40::BIGINT, 31::BIGINT, DATE '2025-01-02')) \
             t(ticker, root, window_start, bid_price, ask_price, bid_size, ask_size, trade_date)"
        ),
    )?;
    Ok(tmp)
}

#[tokio::test]
async fn evening_bars_belong_to_the_next_session() -> TestResult {
    let tmp = fixture()?;
    // The window is the evening of 01-01 (UTC 23:00-23:59): ET-date pruning would look at 01-01
    let (status, v) = get(tmp.path(), "/future?tickers=ZN&start=2025-01-01T23:00:00&end=2025-01-01T23:59:00").await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(tickers(&v), vec!["ZN"]);
    assert_eq!(v[0]["window_start"].as_i64(), Some(EVE));
    assert_eq!(v[0]["root"].as_str(), Some("ZN"));
    Ok(())
}

#[tokio::test]
async fn roots_select_every_series_of_a_product() -> TestResult {
    let tmp = fixture()?;
    let (_, v) = get(tmp.path(), "/future?roots=ZN&start=2025-01-02T14:00:00&end=2025-01-02T15:00:00").await?;
    assert_eq!(tickers(&v), vec!["ZN", "ZNH5"]);
    let (status, _) = get(tmp.path(), "/future?start=2025-01-02T14:00:00&end=2025-01-02T15:00:00").await?;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    let (_, q) = get(tmp.path(), "/future/quote?tickers=ZN&start=2025-01-02T14:00:00&end=2025-01-02T15:00:00").await?;
    assert_eq!(q[0]["bid_price"].as_f64(), Some(110.484375));
    Ok(())
}

#[tokio::test]
async fn daily_settle_is_final_at_17_et() -> TestResult {
    let tmp = fixture()?;
    let (_, v) = get(tmp.path(), "/future/daily?tickers=ZN&start=2025-01-01&end=2025-01-03").await?;
    assert_eq!(v[0]["date"].as_str(), Some("2025-01-02"));
    assert_eq!(v[0]["settle"].as_f64(), Some(110.5));
    // 16:59 ET: session 01-02 is not closed yet
    let (_, early) =
        get(tmp.path(), "/future/daily?tickers=ZN&start=2025-01-01&end=2025-01-03&as_of=2025-01-02T21:59:00Z").await?;
    assert_eq!(early.as_array().map_or(0, Vec::len), 0);
    let (_, late) =
        get(tmp.path(), "/future/daily?tickers=ZN&start=2025-01-01&end=2025-01-03&as_of=2025-01-02T22:00:00Z").await?;
    assert_eq!(late.as_array().map_or(0, Vec::len), 1);
    // minute bars are capped too: at 09:31 ET only the 09:30 bar has closed
    let (_, m) =
        get(tmp.path(), "/future?tickers=ZN&start=2025-01-01T00:00:00&end=2025-01-03T00:00:00&as_of=2025-01-02T14:30:59Z").await?;
    assert_eq!(m.as_array().map_or(0, Vec::len), 1);
    Ok(())
}
