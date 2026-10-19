//! Crypto and FX endpoints: UTC-day partitions, pair spellings, the 00:00 UTC daily close.

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


// 2025-01-02 23:30 UTC: still UTC day 2025-01-02 (it is 18:30 ET)
const LATE: i64 = 1_735_860_600_000_000_000;
// 2025-01-03 00:10 UTC: UTC day 2025-01-03
const NEXT: i64 = 1_735_863_000_000_000_000;

fn fixture() -> Result<TempDir, Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    for (d, ts) in [("2025-01-02", LATE), ("2025-01-03", NEXT)] {
        write(
            &tmp.path().join(format!("crypto_minute/trade_date={d}")),
            &format!(
                "SELECT * FROM (VALUES ('BTC-USD', 'BTC', 'USD', {ts}::BIGINT, 97000.0::DOUBLE, 97010.0::DOUBLE, 96990.0::DOUBLE, 97005.0::DOUBLE, \
                 1.25::DOUBLE, 40::BIGINT, DATE '{d}')) \
                 t(ticker, base, quote, window_start, open, high, low, close, volume, transactions, trade_date)"
            ),
        )?;
        write(
            &tmp.path().join(format!("fx_quote_minute/trade_date={d}")),
            &format!(
                "SELECT * FROM (VALUES ('EUR-USD', 'EUR', 'USD', {ts}::BIGINT, 1.0350::DOUBLE, 1.0352::DOUBLE, DATE '{d}')) \
                 t(ticker, base, quote, window_start, bid_price, ask_price, trade_date)"
            ),
        )?;
        write(
            &tmp.path().join(format!("fx_daily/trade_date={d}")),
            &format!(
                "SELECT * FROM (VALUES ('EUR-USD', 'EUR', 'USD', DATE '{d}', 1.03::DOUBLE, 1.04::DOUBLE, 1.02::DOUBLE, 1.035::DOUBLE, 900.0::DOUBLE, 900::BIGINT)) \
                 t(ticker, base, quote, trade_date, open, high, low, close, volume, transactions)"
            ),
        )?;
    }
    Ok(tmp)
}

#[tokio::test]
async fn partitions_are_utc_days_and_pairs_accept_any_spelling() -> TestResult {
    let tmp = fixture()?;
    for spelling in ["BTC-USD", "btcusd", "X:BTC-USD", "BTC/USD"] {
        let (s, v) = get(tmp.path(), &format!(
            "/crypto?tickers={spelling}&start=2025-01-02T23:00:00&end=2025-01-03T01:00:00")).await?;
        assert_eq!(s, StatusCode::OK);
        assert_eq!(v.as_array().map(|a| a.len()), Some(2), "{spelling}: {v}");
    }
    // a window inside UTC day 2025-01-02 only reads that partition's bar
    let (_, v) = get(tmp.path(), "/crypto?tickers=BTC-USD&start=2025-01-02T23:00:00&end=2025-01-02T23:59:59").await?;
    assert_eq!(tickers(&v), vec!["BTC-USD"]);
    assert_eq!(v[0]["volume"], 1.25);
    Ok(())
}

#[tokio::test]
async fn fx_quotes_and_the_daily_close_at_midnight_utc() -> TestResult {
    let tmp = fixture()?;
    let (s, v) = get(tmp.path(), "/fx/quote?tickers=EURUSD,C:EUR-USD&start=2025-01-02T00:00:00&end=2025-01-03T23:59:59").await?;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(v.as_array().map(|a| a.len()), Some(2));
    assert_eq!(v[0]["bid_price"], 1.035);
    // at 2025-01-03 12:00 UTC only day 2025-01-02 is final
    let (_, v) = get(tmp.path(), "/fx/daily?tickers=EUR-USD&start=2025-01-01&end=2025-01-05&as_of=2025-01-03T12:00:00Z").await?;
    assert_eq!(v.as_array().map(|a| a.len()), Some(1), "{v}");
    assert_eq!(v[0]["date"], "2025-01-02");
    // minute bars follow as_of too: the 00:10 bar is closed at 00:11
    let (_, v) = get(tmp.path(), "/crypto?tickers=BTC-USD&start=2025-01-02T00:00:00&end=2025-01-03T23:00:00&as_of=2025-01-03T00:10:30Z").await?;
    assert_eq!(v.as_array().map(|a| a.len()), Some(1));
    let (s, _) = get(tmp.path(), "/fx?tickers=&start=2025-01-02T00:00:00&end=2025-01-03T00:00:00").await?;
    assert_eq!(s, StatusCode::BAD_REQUEST);
    Ok(())
}
