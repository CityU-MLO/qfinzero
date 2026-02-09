use std::convert::Infallible;
use std::fs;

use axum::body::{to_bytes, Body};
use axum::http::{Request, StatusCode};
use duckdb::Connection;
use serde_json::Value;
use tempfile::TempDir;
use tower::util::ServiceExt;

fn unwrap_infallible<T>(result: Result<T, Infallible>) -> T {
    match result {
        Ok(value) => value,
        Err(never) => match never {},
    }
}

#[tokio::test]
async fn stock_endpoint_accepts_valid_request() -> Result<(), Box<dyn std::error::Error>> {
    let app = upq_service::app::build_router();
    let request = Request::builder()
        .uri("/stock?tickers=AAPL,MSFT&start=2025-01-06T09:30:00&end=2025-01-06T16:00:00")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    Ok(())
}

#[tokio::test]
async fn option_ticker_query_rejects_invalid_resolution() -> Result<(), Box<dyn std::error::Error>>
{
    let app = upq_service::app::build_router();
    let request = Request::builder()
        .uri("/option/ticker_query?contract=O:NVDA250117C00136000&start=2025-01-02&end=2025-01-31&resolution=hour")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    Ok(())
}

#[tokio::test]
async fn rates_endpoint_requires_date_range() -> Result<(), Box<dyn std::error::Error>> {
    let app = upq_service::app::build_router();
    let request = Request::builder()
        .uri("/rates/query?start=2025-01-01")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    Ok(())
}

#[tokio::test]
async fn stock_endpoint_rejects_invalid_datetime_format() -> Result<(), Box<dyn std::error::Error>>
{
    let app = upq_service::app::build_router();
    let request = Request::builder()
        .uri("/stock?tickers=AAPL&start=2025-01-06%2009:30:00&end=2025-01-06T16:00:00")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    Ok(())
}

#[tokio::test]
async fn stock_daily_rejects_invalid_date_format() -> Result<(), Box<dyn std::error::Error>> {
    let app = upq_service::app::build_router();
    let request = Request::builder()
        .uri("/stock/daily?tickers=AAPL&start=2025/01/06&end=2025-01-10")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    Ok(())
}

#[tokio::test]
async fn stock_endpoint_reads_rows_from_parquet() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp
        .path()
        .join("stock_minute")
        .join("trade_date=2025-01-06");
    fs::create_dir_all(&partition_dir)?;
    let parquet_path = partition_dir.join("sample.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT \
                'AAPL' AS ticker, \
                1736155800000000000::BIGINT AS window_start, \
                100.0::DOUBLE AS open, \
                101.0::DOUBLE AS high, \
                99.0::DOUBLE AS low, \
                100.5::DOUBLE AS close, \
                1000::BIGINT AS volume, \
                10::BIGINT AS transactions, \
                DATE '2025-01-06' AS trade_date\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/stock?tickers=AAPL&start=2025-01-06T09:30:00&end=2025-01-06T10:30:00&fields=ticker,window_start,close")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);

    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("payload should be array"))?;
    assert_eq!(array.len(), 1);
    assert_eq!(
        array[0].get("ticker"),
        Some(&Value::String("AAPL".to_string()))
    );

    Ok(())
}
