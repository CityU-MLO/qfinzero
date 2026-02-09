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

#[tokio::test]
async fn rates_endpoint_reads_projected_tenors_from_parquet(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let parquet_path = rates_dir.join("rates.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                (DATE '2025-01-02', 1.53::DOUBLE, 1.54::DOUBLE, 1.56::DOUBLE, 1.58::DOUBLE, 1.67::DOUBLE, 1.88::DOUBLE, 2.33::DOUBLE),\
                (DATE '2025-01-03', 1.52::DOUBLE, 1.52::DOUBLE, 1.55::DOUBLE, 1.53::DOUBLE, 1.59::DOUBLE, 1.80::DOUBLE, 2.26::DOUBLE)\
            ) AS t(date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year)\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/rates/query?start=2025-01-01&end=2025-01-31&tenors=1M,10Y")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);

    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("payload should be array"))?;
    assert_eq!(array.len(), 2);
    assert_eq!(array[0].get("yield_1_month"), Some(&Value::from(1.53_f64)));
    assert_eq!(array[0].get("yield_10_year"), Some(&Value::from(1.88_f64)));
    assert_eq!(array[0].get("yield_5_year"), None);

    Ok(())
}

#[tokio::test]
async fn stock_endpoint_ignores_rows_outside_trade_date_partitions(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp
        .path()
        .join("stock_minute")
        .join("trade_date=2024-01-01");
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
                10::BIGINT AS transactions\
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
    assert!(array.is_empty());

    Ok(())
}

#[tokio::test]
async fn option_ticker_query_ignores_rows_outside_trade_date_partitions(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp.path().join("option_day").join("trade_date=2024-01-01");
    fs::create_dir_all(&partition_dir)?;
    let parquet_path = partition_dir.join("sample.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT \
                'O:NVDA250117C00136000' AS ticker, \
                1736496000000000000::BIGINT AS window_start, \
                3.0::DOUBLE AS open, \
                3.5::DOUBLE AS high, \
                2.8::DOUBLE AS low, \
                3.2::DOUBLE AS close, \
                100::BIGINT AS volume, \
                5::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/ticker_query?contract=O:NVDA250117C00136000&start=2025-01-10&end=2025-01-10&resolution=day&fields=ticker,window_start,close")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("payload should be array"))?;
    assert!(array.is_empty());

    Ok(())
}

#[tokio::test]
async fn option_ticker_query_reads_rows_from_parquet() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp.path().join("option_day").join("trade_date=2025-01-10");
    fs::create_dir_all(&partition_dir)?;
    let parquet_path = partition_dir.join("sample.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT \
                'O:NVDA250117C00136000' AS ticker, \
                'NVDA' AS underlying, \
                DATE '2025-01-17' AS expiry, \
                136.0::DOUBLE AS strike, \
                'C' AS right, \
                1736496000000000000::BIGINT AS window_start, \
                3.0::DOUBLE AS open, \
                3.5::DOUBLE AS high, \
                2.8::DOUBLE AS low, \
                3.2::DOUBLE AS close, \
                100::BIGINT AS volume, \
                5::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/ticker_query?contract=O:NVDA250117C00136000&start=2025-01-10&end=2025-01-10&resolution=day&fields=ticker,window_start,close")
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
        Some(&Value::String("O:NVDA250117C00136000".to_string()))
    );

    Ok(())
}

#[tokio::test]
async fn option_ticker_query_supports_contract_field_alias(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp.path().join("option_day").join("trade_date=2025-01-10");
    fs::create_dir_all(&partition_dir)?;
    let parquet_path = partition_dir.join("sample.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT \
                'O:NVDA250117C00136000' AS ticker, \
                'NVDA' AS underlying, \
                DATE '2025-01-17' AS expiry, \
                136.0::DOUBLE AS strike, \
                'C' AS right, \
                1736496000000000000::BIGINT AS window_start, \
                3.2::DOUBLE AS close, \
                100::BIGINT AS volume, \
                5::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/ticker_query?contract=O:NVDA250117C00136000&start=2025-01-10&end=2025-01-10&resolution=day&fields=contract,close")
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
        array[0].get("contract"),
        Some(&Value::String("O:NVDA250117C00136000".to_string()))
    );
    assert_eq!(array[0].get("ticker"), None);

    Ok(())
}

#[tokio::test]
async fn option_chain_query_reads_filtered_rows_from_parquet(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
    fs::create_dir_all(&partition_dir)?;
    let parquet_path = partition_dir.join("sample.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                ('O:NVDA250117C00136000', 'NVDA', DATE '2025-01-17', 136.0::DOUBLE, 'C', 1736899200000000000::BIGINT, 3.2::DOUBLE, 100::BIGINT),\
                ('O:NVDA250117P00130000', 'NVDA', DATE '2025-01-17', 130.0::DOUBLE, 'P', 1736899200000000000::BIGINT, 1.8::DOUBLE, 80::BIGINT)\
            ) AS t(ticker, underlying, expiry, strike, \"right\", window_start, close, volume)\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&expiry_min=2025-01-17&expiry_max=2025-01-17&strike_min=135&strike_max=137&type=C&fields=ticker,expiry,strike,type,close")
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
        Some(&Value::String("O:NVDA250117C00136000".to_string()))
    );
    assert_eq!(array[0].get("type"), Some(&Value::String("C".to_string())));

    Ok(())
}
