//! Point-in-time (`as_of`) caps, ET partition pruning, and same-minute spot.

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
    let path = dir.join("part-0000.parquet");
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

fn rows(v: &Value) -> usize {
    v.as_array().map_or(0, Vec::len)
}

// 2025-01-06 is EST: 09:30 ET = 14:30 UTC = 1736173800 s
const T0930: i64 = 1_736_173_800_000_000_000;
const MIN: i64 = 60_000_000_000;

fn stock_minute_fixture() -> Result<TempDir, Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let bars: Vec<String> = [0, 1, 2, 600] // 09:30, 09:31, 09:32, 19:30 ET
        .iter()
        .map(|m| format!("('AAPL', {}::BIGINT, 1.0, 1.0, 1.0, 1.0, 1::BIGINT, 1::BIGINT, DATE '2025-01-06')", T0930 + m * MIN))
        .collect();
    write(
        &tmp.path().join("stock_minute/trade_date=2025-01-06"),
        &format!(
            "SELECT * FROM (VALUES {}) t(ticker, window_start, open, high, low, close, volume, transactions, trade_date)",
            bars.join(", ")
        ),
    )?;
    Ok(tmp)
}

#[tokio::test]
async fn minute_bars_are_visible_only_once_closed() -> TestResult {
    let tmp = stock_minute_fixture()?;
    let base = "/stock?tickers=AAPL&start=2025-01-06T14:00:00&end=2025-01-06T15:00:00";
    let (status, all) = get(tmp.path(), base).await?;
    assert_eq!((status, rows(&all)), (StatusCode::OK, 3));
    // at 09:32:00 ET the 09:30 and 09:31 bars are closed, the 09:32 bar is not
    let (_, capped) = get(tmp.path(), &format!("{base}&as_of=2025-01-06T14:32:00Z")).await?;
    assert_eq!(rows(&capped), 2);
    let (_, offset) = get(tmp.path(), &format!("{base}&as_of=2025-01-06T09:32:00-05:00")).await?;
    assert_eq!(rows(&offset), 2);
    let (status, _) = get(tmp.path(), &format!("{base}&as_of=soon")).await?;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    Ok(())
}

#[tokio::test]
async fn winter_post_market_bar_is_found_across_utc_midnight() -> TestResult {
    // 19:30 ET on 2025-01-06 is 00:30 UTC on 2025-01-07, stored under trade_date=2025-01-06
    let tmp = stock_minute_fixture()?;
    let (_, v) = get(tmp.path(), "/stock?tickers=AAPL&start=2025-01-07T00:00:00&end=2025-01-07T01:00:00").await?;
    assert_eq!(rows(&v), 1);
    Ok(())
}

#[tokio::test]
async fn daily_bar_is_visible_after_the_close() -> TestResult {
    let tmp = TempDir::new()?;
    for d in ["2025-01-06", "2025-01-07"] {
        write(
            &tmp.path().join(format!("stock_daily/trade_date={d}")),
            &format!("SELECT 'AAPL' AS ticker, DATE '{d}' AS trade_date, 1.0 AS open, 1.0 AS high, \
                      1.0 AS low, 1.0 AS close, 1::BIGINT AS volume, 1::BIGINT AS transactions"),
        )?;
    }
    let base = "/stock/daily?tickers=AAPL&start=2025-01-06&end=2025-01-07";
    let (_, before) = get(tmp.path(), &format!("{base}&as_of=2025-01-07T20:00:00Z")).await?; // 15:00 ET
    assert_eq!(rows(&before), 1);
    let (_, after) = get(tmp.path(), &format!("{base}&as_of=2025-01-07T21:00:00Z")).await?; // 16:00 ET
    assert_eq!(rows(&after), 2);
    Ok(())
}

#[tokio::test]
async fn overnight_session_bar_is_final_at_four_am() -> TestResult {
    let tmp = TempDir::new()?;
    for (d, close) in [("2025-01-06", 100.0), ("2025-01-07", 101.0)] {
        write(
            &tmp.path().join(format!("stock_overnight_daily/trade_date={d}")),
            &format!(
                "SELECT 'AAPL' AS ticker, DATE '{d}' AS trade_date, {close} AS open, {close} AS high, \
                 {close} AS low, {close} AS close, 10::BIGINT AS volume, 2::BIGINT AS transactions, \
                 0::BIGINT AS first_window_start, 0::BIGINT AS last_window_start"
            ),
        )?;
    }
    let base = "/stock/daily?tickers=AAPL&start=2025-01-06&end=2025-01-07&session=overnight";
    // 2025-01-07 03:59 ET (08:59 UTC): Tuesday's session is still trading
    let (status, v) = get(tmp.path(), &format!("{base}&as_of=2025-01-07T08:59:00Z")).await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(rows(&v), 1);
    // 04:00 ET: it is final
    let (_, v) = get(tmp.path(), &format!("{base}&as_of=2025-01-07T09:00:00Z")).await?;
    assert_eq!(rows(&v), 2);
    assert_eq!(v[1]["close"], 101.0);
    // the regular store is a different series
    let (_, v) = get(tmp.path(), "/stock/daily?tickers=AAPL&start=2025-01-06&end=2025-01-07").await?;
    assert_eq!(rows(&v), 0);
    let (status, _) = get(tmp.path(), "/stock/daily?tickers=AAPL&start=2025-01-06&end=2025-01-07&session=weekend").await?;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    Ok(())
}

#[tokio::test]
async fn end_of_day_chain_is_refused_before_it_is_final() -> TestResult {
    let tmp = TempDir::new()?;
    write(
        &tmp.path().join("option_day/trade_date=2025-01-06"),
        "SELECT 'O:AAPL250117C00100000' AS ticker, 'O:AAPL250117C00100000' AS contract, 'AAPL' AS underlying, \
         DATE '2025-01-17' AS expiry, 100.0 AS strike, 'C' AS \"right\", 1736139600000000000::BIGINT AS window_start, \
         1.0 AS open, 1.0 AS high, 1.0 AS low, 1.0 AS close, 1::BIGINT AS volume, 1::BIGINT AS transactions, \
         DATE '2025-01-06' AS trade_date",
    )?;
    let base = "/option/chain_query?underlying=AAPL&date=2025-01-06";
    let (status, _) = get(tmp.path(), &format!("{base}&as_of=2025-01-06T21:00:00Z")).await?; // 16:00 ET
    assert_eq!(status, StatusCode::BAD_REQUEST);
    let (status, v) = get(tmp.path(), &format!("{base}&as_of=2025-01-06T21:15:00Z")).await?; // 16:15 ET
    assert_eq!((status, rows(&v)), (StatusCode::OK, 1));
    Ok(())
}

#[tokio::test]
async fn intraday_greeks_use_the_same_minute_spot() -> TestResult {
    let tmp = TempDir::new()?;
    let d = "2025-01-06";
    write(
        &tmp.path().join(format!("option_minute/trade_date={d}")),
        &format!("SELECT 'O:NVDA250221C00140000' AS ticker, {}::BIGINT AS window_start, 5.5::DOUBLE AS open, \
                  5.5::DOUBLE AS high, 5.5::DOUBLE AS low, 5.5::DOUBLE AS close, 10::BIGINT AS volume, \
                  1::BIGINT AS transactions, DATE '{d}' AS trade_date", T0930 + MIN),
    )?;
    // the daily close (known only after 16:00) differs from the 09:30 minute close
    write(
        &tmp.path().join(format!("stock_daily/trade_date={d}")),
        &format!("SELECT 'NVDA' AS ticker, DATE '{d}' AS trade_date, 1.0 AS open, 1.0 AS high, 1.0 AS low, \
                  200.0::DOUBLE AS close, 1::BIGINT AS volume, 1::BIGINT AS transactions"),
    )?;
    write(
        &tmp.path().join(format!("stock_minute/trade_date={d}")),
        &format!("SELECT 'NVDA' AS ticker, {T0930}::BIGINT AS window_start, 1.0 AS open, 1.0 AS high, \
                  1.0 AS low, 136.0::DOUBLE AS close, 1::BIGINT AS volume, 1::BIGINT AS transactions, DATE '{d}' AS trade_date"),
    )?;
    write(
        &tmp.path().join("rates"),
        &format!("SELECT DATE '{d}' AS date, 4.5::DOUBLE AS yield_1_month, 4.4::DOUBLE AS yield_3_month, \
                  4.2::DOUBLE AS yield_1_year, 4.3::DOUBLE AS yield_2_year, 4.4::DOUBLE AS yield_5_year, \
                  4.6::DOUBLE AS yield_10_year, 4.8::DOUBLE AS yield_30_year"),
    )?;
    fs::rename(tmp.path().join("rates/part-0000.parquet"), tmp.path().join("rates/rates.parquet"))?;
    let (status, v) = get(
        tmp.path(),
        "/option/ticker_query?contract=O:NVDA250221C00140000&start=2025-01-06T14:00:00&end=2025-01-06T15:00:00&resolution=minute&include_greeks=true",
    )
    .await?;
    assert_eq!((status, rows(&v)), (StatusCode::OK, 1));
    let row = &v[0];
    assert_eq!(row["greek_meta"]["spot_source"], "stock_minute", "row: {row}");
    assert_eq!(row["greek_status"], "ok", "row: {row}");
    Ok(())
}

// ── quotes + intraday chain snapshot ─────────────────────────────────────

const OPT: &str = "O:NVDA250221C00140000";

fn snapshot_fixture() -> Result<TempDir, Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let d = "2025-01-06";
    let cols = "'NVDA' AS underlying, DATE '2025-02-21' AS expiry, 140.0::DOUBLE AS strike, 'C' AS \"right\"";
    // trades at 09:31 (5.5 x10) and 09:40 (6.0 x3)
    write(
        &tmp.path().join(format!("option_minute/trade_date={d}")),
        &format!(
            "SELECT * FROM (VALUES ('{OPT}', {}::BIGINT, 5.5::DOUBLE, 10::BIGINT), ('{OPT}', {}::BIGINT, 6.0::DOUBLE, 3::BIGINT)) \
             t(ticker, window_start, close, volume)",
            T0930 + MIN,
            T0930 + 10 * MIN
        )
        .replace(
            "SELECT * FROM",
            &format!("SELECT ticker, ticker AS contract, {cols}, window_start, close AS open, close AS high, \
                      close AS low, close, volume, 1::BIGINT AS transactions, DATE '{d}' AS trade_date FROM"),
        ),
    )?;
    // quotes at 09:30 and 09:35 (minutes with no update carry the last quote)
    write(
        &tmp.path().join(format!("option_quote_minute/trade_date={d}")),
        &format!(
            "SELECT ticker, ticker AS contract, {cols}, window_start, bid_price, ask_price, 5::BIGINT AS bid_size, \
             7::BIGINT AS ask_size, DATE '{d}' AS trade_date FROM (VALUES \
             ('{OPT}', {}::BIGINT, 5.4::DOUBLE, 5.6::DOUBLE), ('{OPT}', {}::BIGINT, 5.8::DOUBLE, 6.2::DOUBLE)) \
             t(ticker, window_start, bid_price, ask_price)",
            T0930,
            T0930 + 5 * MIN
        ),
    )?;
    write(
        &tmp.path().join(format!("stock_minute/trade_date={d}")),
        &format!("SELECT 'NVDA' AS ticker, {T0930}::BIGINT AS window_start, 1.0::DOUBLE AS open, 1.0::DOUBLE AS high, \
                  1.0::DOUBLE AS low, 138.0::DOUBLE AS close, 1::BIGINT AS volume, 1::BIGINT AS transactions, \
                  DATE '{d}' AS trade_date"),
    )?;
    write(
        &tmp.path().join("rates"),
        &format!("SELECT DATE '{d}' AS date, 4.5::DOUBLE AS yield_1_month, 4.4::DOUBLE AS yield_3_month, \
                  4.2::DOUBLE AS yield_1_year, 4.3::DOUBLE AS yield_2_year, 4.4::DOUBLE AS yield_5_year, \
                  4.6::DOUBLE AS yield_10_year, 4.8::DOUBLE AS yield_30_year"),
    )?;
    fs::rename(tmp.path().join("rates/part-0000.parquet"), tmp.path().join("rates/rates.parquet"))?;
    Ok(tmp)
}

#[tokio::test]
async fn chain_snapshot_shows_only_what_was_known_at_the_time() -> TestResult {
    let tmp = snapshot_fixture()?;
    // 09:33 ET: the 09:31 trade is final, the 09:30 quote is the latest
    let (status, v) = get(tmp.path(), "/option/chain_snapshot?underlying=NVDA&at=2025-01-06T14:33:00").await?;
    assert_eq!((status, rows(&v)), (StatusCode::OK, 1));
    let r = &v[0];
    assert_eq!((r["last"].as_f64(), r["volume"].as_i64()), (Some(5.5), Some(10)));
    assert_eq!((r["bid"].as_f64(), r["ask"].as_f64(), r["mid"].as_f64()), (Some(5.4), Some(5.6), Some(5.5)));
    assert_eq!(r["expiry"], "2025-02-21");
    // 09:45 ET: both trades, the 09:35 quote carried forward
    let (_, v) = get(tmp.path(), "/option/chain_snapshot?underlying=NVDA&at=2025-01-06T14:45:00").await?;
    assert_eq!((v[0]["last"].as_f64(), v[0]["volume"].as_i64(), v[0]["bid"].as_f64()), (Some(6.0), Some(13), Some(5.8)));
    // as_of caps `at`
    let (_, v) = get(tmp.path(), "/option/chain_snapshot?underlying=NVDA&at=2025-01-06T14:45:00&as_of=2025-01-06T14:33:00Z").await?;
    assert_eq!(v[0]["volume"].as_i64(), Some(10));
    // before anything printed or quoted
    let (_, v) = get(tmp.path(), "/option/chain_snapshot?underlying=NVDA&at=2025-01-06T14:30:30").await?;
    assert_eq!(rows(&v), 0);
    Ok(())
}

#[tokio::test]
async fn chain_snapshot_greeks_price_off_the_mid_with_minute_spot() -> TestResult {
    let tmp = snapshot_fixture()?;
    let (_, v) = get(tmp.path(), "/option/chain_snapshot?underlying=NVDA&at=2025-01-06T14:33:00&include_greeks=true").await?;
    let r = &v[0];
    assert_eq!(r["greek_status"], "ok");
    assert_eq!(r["greek_meta"]["spot_source"], "stock_minute");
    assert_eq!(r["iv_price"].as_f64(), Some(5.5));
    assert!(r.get("close").is_none());
    Ok(())
}

#[tokio::test]
async fn option_quote_series_respects_as_of() -> TestResult {
    let tmp = snapshot_fixture()?;
    let base = format!("/option/quote?contract={OPT}&start=2025-01-06T14:00:00&end=2025-01-06T15:00:00");
    let (_, all) = get(tmp.path(), &base).await?;
    assert_eq!(rows(&all), 2);
    let (_, capped) = get(tmp.path(), &format!("{base}&as_of=2025-01-06T14:35:30Z")).await?;
    assert_eq!(rows(&capped), 1);   // the 09:35 quote is final only at 09:36
    Ok(())
}
