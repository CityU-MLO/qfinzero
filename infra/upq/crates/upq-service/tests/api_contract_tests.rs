use std::convert::Infallible;
use std::fs;

use axum::body::{to_bytes, Body};
use axum::http::{Request, StatusCode};
use duckdb::Connection;
use serde_json::Value;
use tempfile::TempDir;
use tower::util::ServiceExt;

#[tokio::test]
async fn freshness_endpoint_returns_sources_for_empty_storage(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/health/freshness")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    assert_eq!(
        payload.get("service"),
        Some(&Value::String("upq".to_string()))
    );
    assert!(payload.get("checked_at").is_some());
    assert!(payload.get("sources").is_some());
    assert!(payload["sources"].is_object());

    Ok(())
}

#[tokio::test]
async fn freshness_endpoint_detects_latest_partition_date() -> Result<(), Box<dyn std::error::Error>>
{
    let tmp = TempDir::new()?;

    // Create two stock_minute partitions with parquet files
    let older_dir = tmp
        .path()
        .join("stock_minute")
        .join("trade_date=2025-01-06");
    let newer_dir = tmp
        .path()
        .join("stock_minute")
        .join("trade_date=2025-01-10");
    fs::create_dir_all(&older_dir)?;
    fs::create_dir_all(&newer_dir)?;

    let conn = Connection::open_in_memory()?;

    let older_parquet = older_dir.join("data.parquet");
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
        older_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let newer_parquet = newer_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                ('AAPL', 1736496000000000000::BIGINT, 102.0::DOUBLE, 103.0::DOUBLE, 101.0::DOUBLE, 102.5::DOUBLE, 2000::BIGINT, 20::BIGINT, DATE '2025-01-10'),\
                ('MSFT', 1736496000000000000::BIGINT, 200.0::DOUBLE, 201.0::DOUBLE, 199.0::DOUBLE, 200.5::DOUBLE, 3000::BIGINT, 30::BIGINT, DATE '2025-01-10')\
            ) AS t(ticker, window_start, open, high, low, close, volume, transactions, trade_date)\
         ) TO '{}' (FORMAT PARQUET)",
        newer_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/health/freshness")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;

    let stock_minute = &payload["sources"]["stock_minute"];
    assert_eq!(
        stock_minute.get("latest_date"),
        Some(&Value::String("2025-01-10".to_string()))
    );
    assert_eq!(stock_minute.get("record_count"), Some(&Value::from(2)));
    assert_eq!(stock_minute.get("unique_keys"), Some(&Value::from(2)));
    assert_eq!(stock_minute.get("partition_count"), Some(&Value::from(2)));

    Ok(())
}

#[tokio::test]
async fn freshness_endpoint_includes_rates_source() -> Result<(), Box<dyn std::error::Error>> {
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
        .uri("/health/freshness")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;

    let rates = &payload["sources"]["rates"];
    assert_eq!(
        rates.get("latest_date"),
        Some(&Value::String("2025-01-03".to_string()))
    );
    assert_eq!(rates.get("unique_keys"), Some(&Value::from(7)));
    assert_eq!(
        rates.get("unique_key_label"),
        Some(&Value::String("tenors".to_string()))
    );

    Ok(())
}

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
async fn health_endpoint_returns_ok_status() -> Result<(), Box<dyn std::error::Error>> {
    let app = upq_service::app::build_router();
    let request = Request::builder().uri("/health").body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    assert_eq!(
        payload.get("status"),
        Some(&Value::String("ok".to_string()))
    );
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
async fn option_base_endpoint_returns_metadata() -> Result<(), Box<dyn std::error::Error>> {
    let app = upq_service::app::build_router();
    let request = Request::builder().uri("/option").body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    assert_eq!(
        payload.get("ticker_query_path"),
        Some(&Value::String("/option/ticker_query".to_string()))
    );
    assert_eq!(
        payload.get("chain_query_path"),
        Some(&Value::String("/option/chain_query".to_string()))
    );
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
async fn rates_endpoint_uses_cache_when_source_file_is_temporarily_missing(
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
    let response = unwrap_infallible(app.clone().oneshot(request).await);
    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let first_payload: Value = serde_json::from_slice(&bytes)?;

    fs::remove_file(&parquet_path)?;

    let second_request = Request::builder()
        .uri("/rates/query?start=2025-01-01&end=2025-01-31&tenors=1M,10Y")
        .body(Body::empty())?;
    let second_response = unwrap_infallible(app.oneshot(second_request).await);
    assert_eq!(second_response.status(), StatusCode::OK);
    let second_bytes = to_bytes(second_response.into_body(), usize::MAX).await?;
    let second_payload: Value = serde_json::from_slice(&second_bytes)?;

    assert_eq!(second_payload, first_payload);
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
async fn stock_endpoint_treats_blank_fields_as_default_projection(
) -> Result<(), Box<dyn std::error::Error>> {
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
        .uri("/stock?tickers=AAPL&start=2025-01-06T09:30:00&end=2025-01-06T10:30:00&fields=%20,%20")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("payload should be array"))?;
    assert_eq!(array.len(), 1);
    assert!(array[0].get("open").is_some());

    Ok(())
}

#[tokio::test]
async fn stock_daily_endpoint_treats_blank_fields_as_default_projection(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp.path().join("stock_daily").join("trade_date=2025-01-06");
    fs::create_dir_all(&partition_dir)?;
    let parquet_path = partition_dir.join("sample.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT \
                'AAPL' AS ticker, \
                DATE '2025-01-06' AS trade_date, \
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
        .uri("/stock/daily?tickers=AAPL&start=2025-01-06&end=2025-01-06&fields=%20,%20")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("payload should be array"))?;
    assert_eq!(array.len(), 1);
    assert!(array[0].get("date").is_some());

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
async fn option_ticker_query_treats_blank_fields_as_default_projection(
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
        .uri("/option/ticker_query?contract=O:NVDA250117C00136000&start=2025-01-10&end=2025-01-10&resolution=day&fields=%20,%20")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("payload should be array"))?;
    assert_eq!(array.len(), 1);
    assert!(array[0].get("close").is_some());

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
async fn option_chain_query_treats_blank_fields_as_default_projection(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
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
                'C' AS \"right\", \
                1736974800000000000::BIGINT AS window_start, \
                3.2::DOUBLE AS close, \
                100::BIGINT AS volume\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&fields=%20,%20")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("payload should be array"))?;
    assert_eq!(array.len(), 1);
    assert!(array[0].get("type").is_some());

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
                ('O:NVDA250117C00136000', 'NVDA', DATE '2025-01-17', 136.0::DOUBLE, 'C', 1736974800000000000::BIGINT, 3.2::DOUBLE, 100::BIGINT),\
                ('O:NVDA250117P00130000', 'NVDA', DATE '2025-01-17', 130.0::DOUBLE, 'P', 1736974800000000000::BIGINT, 1.8::DOUBLE, 80::BIGINT)\
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

#[tokio::test]
async fn option_chain_query_rejects_non_finite_strike_filters(
) -> Result<(), Box<dyn std::error::Error>> {
    let app = upq_service::app::build_router();
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&strike_min=NaN")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    Ok(())
}

#[tokio::test]
async fn option_chain_query_falls_back_to_nearest_expiry_when_exact_missing(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
    fs::create_dir_all(&partition_dir)?;
    let parquet_path = partition_dir.join("sample.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                ('O:NVDA250207C00136000', 'NVDA', DATE '2025-02-07', 136.0::DOUBLE, 'C', 1736974800000000000::BIGINT, 4.1::DOUBLE, 120::BIGINT),\
                ('O:NVDA250214C00136000', 'NVDA', DATE '2025-02-14', 136.0::DOUBLE, 'C', 1736974800000000000::BIGINT, 4.6::DOUBLE, 115::BIGINT)\
            ) AS t(ticker, underlying, expiry, strike, \"right\", window_start, close, volume)\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&expiry_min=2025-02-10&expiry_max=2025-02-10&type=C&fields=ticker,expiry,strike,type,close")
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
        array[0].get("expiry"),
        Some(&Value::String("2025-02-07".to_string()))
    );
    assert_eq!(array[0].get("type"), Some(&Value::String("C".to_string())));

    Ok(())
}

#[tokio::test]
async fn option_chain_query_falls_back_to_month_window_when_week_window_empty(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
    fs::create_dir_all(&partition_dir)?;
    let parquet_path = partition_dir.join("sample.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                ('O:NVDA250228C00136000', 'NVDA', DATE '2025-02-28', 136.0::DOUBLE, 'C', 1736974800000000000::BIGINT, 5.4::DOUBLE, 140::BIGINT),\
                ('O:NVDA250307C00136000', 'NVDA', DATE '2025-03-07', 136.0::DOUBLE, 'C', 1736974800000000000::BIGINT, 5.9::DOUBLE, 100::BIGINT)\
            ) AS t(ticker, underlying, expiry, strike, \"right\", window_start, close, volume)\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&expiry_min=2025-02-10&expiry_max=2025-02-10&type=C&fields=ticker,expiry,strike,type,close")
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
        array[0].get("expiry"),
        Some(&Value::String("2025-02-28".to_string()))
    );

    Ok(())
}

#[tokio::test]
async fn option_chain_query_fallback_tie_prefers_earlier_expiry(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
    fs::create_dir_all(&partition_dir)?;
    let parquet_path = partition_dir.join("sample.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                ('O:NVDA250207C00136000', 'NVDA', DATE '2025-02-07', 136.0::DOUBLE, 'C', 1736974800000000000::BIGINT, 4.1::DOUBLE, 120::BIGINT),\
                ('O:NVDA250213C00136000', 'NVDA', DATE '2025-02-13', 136.0::DOUBLE, 'C', 1736974800000000000::BIGINT, 4.3::DOUBLE, 100::BIGINT)\
            ) AS t(ticker, underlying, expiry, strike, \"right\", window_start, close, volume)\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&expiry_min=2025-02-10&expiry_max=2025-02-10&type=C&fields=ticker,expiry,strike,type,close")
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
        array[0].get("expiry"),
        Some(&Value::String("2025-02-07".to_string()))
    );

    Ok(())
}

#[tokio::test]
async fn option_chain_query_range_filters_do_not_trigger_nearest_fallback(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
    fs::create_dir_all(&partition_dir)?;
    let parquet_path = partition_dir.join("sample.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                ('O:NVDA250207C00136000', 'NVDA', DATE '2025-02-07', 136.0::DOUBLE, 'C', 1736974800000000000::BIGINT, 4.1::DOUBLE, 120::BIGINT),\
                ('O:NVDA250228C00136000', 'NVDA', DATE '2025-02-28', 136.0::DOUBLE, 'C', 1736974800000000000::BIGINT, 5.4::DOUBLE, 140::BIGINT)\
            ) AS t(ticker, underlying, expiry, strike, \"right\", window_start, close, volume)\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&expiry_min=2025-02-10&expiry_max=2025-02-20&type=C&fields=ticker,expiry,strike,type,close")
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
async fn option_chain_query_rejects_invalid_exact_expiry_date(
) -> Result<(), Box<dyn std::error::Error>> {
    let app = upq_service::app::build_router();
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&expiry_min=2025-02-30&expiry_max=2025-02-30")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    Ok(())
}

#[tokio::test]
async fn rates_endpoint_returns_all_tenor_columns_when_tenors_is_missing(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let parquet_path = rates_dir.join("rates.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                (DATE '2025-01-02', 1.53::DOUBLE, 1.54::DOUBLE, 1.56::DOUBLE, 1.58::DOUBLE, 1.67::DOUBLE, 1.88::DOUBLE, 2.33::DOUBLE)\
            ) AS t(date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year)\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/rates/query?start=2025-01-01&end=2025-01-31")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("payload should be array"))?;
    assert_eq!(array.len(), 1);
    assert!(array[0].get("yield_1_month").is_some());
    assert!(array[0].get("yield_30_year").is_some());

    Ok(())
}

#[tokio::test]
async fn rates_cache_retains_recent_entry_when_capacity_exceeded(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let parquet_path = rates_dir.join("rates.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                (DATE '2025-01-02', 1.53::DOUBLE, 1.54::DOUBLE, 1.56::DOUBLE, 1.58::DOUBLE, 1.67::DOUBLE, 1.88::DOUBLE, 2.33::DOUBLE)\
            ) AS t(date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year)\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let recent_uri = "/rates/query?start=2025-01-01&end=2025-01-31";

    let recent_response = unwrap_infallible(
        app.clone()
            .oneshot(Request::builder().uri(recent_uri).body(Body::empty())?)
            .await,
    );
    assert_eq!(recent_response.status(), StatusCode::OK);

    for idx in 0..511_u32 {
        let year = 2030_u32 + idx;
        let uri = format!("/rates/query?start={year}-01-01&end={year}-01-31");
        let response = unwrap_infallible(
            app.clone()
                .oneshot(Request::builder().uri(uri).body(Body::empty())?)
                .await,
        );
        assert_eq!(response.status(), StatusCode::OK);
    }

    let recent_again = unwrap_infallible(
        app.clone()
            .oneshot(Request::builder().uri(recent_uri).body(Body::empty())?)
            .await,
    );
    assert_eq!(recent_again.status(), StatusCode::OK);

    let overflow = unwrap_infallible(
        app.clone()
            .oneshot(
                Request::builder()
                    .uri("/rates/query?start=2600-01-01&end=2600-01-31")
                    .body(Body::empty())?,
            )
            .await,
    );
    assert_eq!(overflow.status(), StatusCode::OK);

    fs::remove_file(&parquet_path)?;

    let cached_response = unwrap_infallible(
        app.oneshot(Request::builder().uri(recent_uri).body(Body::empty())?)
            .await,
    );
    assert_eq!(cached_response.status(), StatusCode::OK);
    let bytes = to_bytes(cached_response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("payload should be array"))?;
    assert_eq!(array.len(), 1);

    Ok(())
}

#[tokio::test]
async fn rates_endpoint_treats_blank_tenors_as_all_columns(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let parquet_path = rates_dir.join("rates.parquet");

    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                (DATE '2025-01-02', 1.53::DOUBLE, 1.54::DOUBLE, 1.56::DOUBLE, 1.58::DOUBLE, 1.67::DOUBLE, 1.88::DOUBLE, 2.33::DOUBLE)\
            ) AS t(date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year)\
         ) TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/rates/query?start=2025-01-01&end=2025-01-31&tenors=%20,%20")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("payload should be array"))?;
    assert_eq!(array.len(), 1);
    assert!(array[0].get("yield_1_month").is_some());
    assert!(array[0].get("yield_30_year").is_some());

    Ok(())
}

// ============== Greeks Integration Tests ==============

/// Helper: create a full test environment with option_day, stock_daily, and rates data.
fn create_greeks_test_env() -> Result<TempDir, Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let conn = Connection::open_in_memory()?;

    // Create option_day partition
    let option_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
    fs::create_dir_all(&option_dir)?;
    let option_parquet = option_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                ('O:NVDA250221C00140000', 'NVDA', DATE '2025-02-21', 140.0::DOUBLE, 'C', 1736974800000000000::BIGINT, 5.40::DOUBLE, 5.70::DOUBLE, 5.30::DOUBLE, 5.50::DOUBLE, 200::BIGINT, 50::BIGINT),\
                ('O:NVDA250221P00130000', 'NVDA', DATE '2025-02-21', 130.0::DOUBLE, 'P', 1736974800000000000::BIGINT, 2.20::DOUBLE, 2.50::DOUBLE, 2.10::DOUBLE, 2.30::DOUBLE, 150::BIGINT, 30::BIGINT)\
            ) AS t(ticker, underlying, expiry, strike, \"right\", window_start, open, high, low, close, volume, transactions)\
         ) TO '{}' (FORMAT PARQUET)",
        option_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Create stock_daily partition
    let stock_dir = tmp.path().join("stock_daily").join("trade_date=2025-01-15");
    fs::create_dir_all(&stock_dir)?;
    let stock_parquet = stock_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT \
                'NVDA' AS ticker, \
                DATE '2025-01-15' AS trade_date, \
                135.0::DOUBLE AS open, \
                137.0::DOUBLE AS high, \
                133.0::DOUBLE AS low, \
                136.0::DOUBLE AS close, \
                5000::BIGINT AS volume, \
                50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        stock_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Create rates data
    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let rates_parquet = rates_dir.join("rates.parquet");
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                (DATE '2025-01-15', 4.53::DOUBLE, 4.35::DOUBLE, 4.22::DOUBLE, 4.28::DOUBLE, 4.43::DOUBLE, 4.60::DOUBLE, 4.82::DOUBLE)\
            ) AS t(date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year)\
         ) TO '{}' (FORMAT PARQUET)",
        rates_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    Ok(tmp)
}

#[tokio::test]
async fn option_chain_greeks_disabled_returns_legacy_fields(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = create_greeks_test_env()?;
    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=false")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 2);
    // Should NOT have greeks fields
    assert!(array[0].get("iv").is_none());
    assert!(array[0].get("greek_status").is_none());
    assert!(array[0].get("greek_meta").is_none());

    Ok(())
}

#[tokio::test]
async fn option_chain_greeks_enabled_returns_greek_fields() -> Result<(), Box<dyn std::error::Error>>
{
    let tmp = create_greeks_test_env()?;
    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 2);

    // First row: call option (expiry 2025-02-21 sorts first, strike 130 < 140 so put comes first by strike)
    // Actually ordering is by expiry then strike, so 130 comes before 140
    let put_row = &array[0];
    let call_row = &array[1];

    // Call row checks
    assert!(call_row.get("iv").is_some(), "should have iv field");
    assert!(call_row.get("delta").is_some(), "should have delta field");
    assert!(call_row.get("gamma").is_some(), "should have gamma field");
    assert!(call_row.get("theta").is_some(), "should have theta field");
    assert!(call_row.get("vega").is_some(), "should have vega field");
    assert!(call_row.get("rho").is_some(), "should have rho field");
    assert!(
        call_row.get("greek_status").is_some(),
        "should have greek_status"
    );
    assert!(
        call_row.get("greek_meta").is_some(),
        "should have greek_meta"
    );

    let status = call_row["greek_status"]
        .as_str()
        .ok_or_else(|| std::io::Error::other("expected string"))?;
    assert_eq!(status, "ok");

    // Check meta fields
    let meta = &call_row["greek_meta"];
    assert_eq!(meta["model"], "bsm_european");
    assert_eq!(meta["style_assumption"], "European");
    assert_eq!(meta["dividend_assumption"], "q0");
    assert_eq!(meta["theta_unit"], "per_day");
    assert_eq!(meta["vega_unit"], "per_1pct_vol");
    assert_eq!(meta["rho_unit"], "per_1pct_rate");

    // IV should be a positive number
    let iv = call_row["iv"]
        .as_f64()
        .ok_or_else(|| std::io::Error::other("iv should be a number"))?;
    assert!(iv > 0.0 && iv < 10.0, "iv={iv} should be reasonable");

    // Delta for a call should be positive
    let delta = call_row["delta"]
        .as_f64()
        .ok_or_else(|| std::io::Error::other("delta should be a number"))?;
    assert!(
        delta > 0.0 && delta < 1.0,
        "call delta={delta} should be in (0,1)"
    );

    // Put row checks
    let put_status = put_row["greek_status"]
        .as_str()
        .ok_or_else(|| std::io::Error::other("expected string"))?;
    assert_eq!(put_status, "ok");
    let put_delta = put_row["delta"]
        .as_f64()
        .ok_or_else(|| std::io::Error::other("delta should be a number"))?;
    assert!(
        put_delta > -1.0 && put_delta < 0.0,
        "put delta={put_delta} should be in (-1,0)"
    );

    Ok(())
}

#[tokio::test]
async fn option_chain_greeks_with_minimal_fields_still_computes(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = create_greeks_test_env()?;
    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&fields=contract,close&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 2);

    for row in array {
        assert!(
            row.get("contract").is_some(),
            "contract alias should be present"
        );
        assert!(
            row.get("ticker").is_none(),
            "ticker should stay aliased away"
        );
        assert!(row.get("close").is_some());
        assert_eq!(row["greek_status"], "ok");
        assert!(!row["iv"].is_null());
        assert_eq!(row["greek_meta"]["theta_unit"], "per_day");
    }

    Ok(())
}

#[tokio::test]
async fn option_chain_greeks_invalid_model_returns_400() -> Result<(), Box<dyn std::error::Error>> {
    let app = upq_service::app::build_router();
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true&greek_model=binomial")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    Ok(())
}

#[tokio::test]
async fn option_chain_greeks_missing_spot_returns_missing_spot_status(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let conn = Connection::open_in_memory()?;

    // Create option_day but NO stock_daily
    let option_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
    fs::create_dir_all(&option_dir)?;
    let option_parquet = option_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT 'O:NVDA250221C00140000' AS ticker, 'NVDA' AS underlying, DATE '2025-02-21' AS expiry, \
            140.0::DOUBLE AS strike, 'C' AS \"right\", 1736974800000000000::BIGINT AS window_start, \
            5.50::DOUBLE AS close, 200::BIGINT AS volume\
         ) TO '{}' (FORMAT PARQUET)",
        option_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Create rates but no stock
    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let rates_parquet = rates_dir.join("rates.parquet");
    let sql = format!(
        "COPY (\
            SELECT DATE '2025-01-15' AS date, 4.53::DOUBLE AS yield_1_month, 4.35::DOUBLE AS yield_3_month, \
            4.22::DOUBLE AS yield_1_year, 4.28::DOUBLE AS yield_2_year, 4.43::DOUBLE AS yield_5_year, \
            4.60::DOUBLE AS yield_10_year, 4.82::DOUBLE AS yield_30_year\
         ) TO '{}' (FORMAT PARQUET)",
        rates_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 1);
    assert_eq!(array[0]["greek_status"], "missing_spot");
    assert!(array[0]["iv"].is_null());

    Ok(())
}

#[tokio::test]
async fn option_chain_greeks_missing_rate_returns_missing_rate_status(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let conn = Connection::open_in_memory()?;

    // Create option_day and stock_daily but NO rates
    let option_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
    fs::create_dir_all(&option_dir)?;
    let option_parquet = option_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT 'O:NVDA250221C00140000' AS ticker, 'NVDA' AS underlying, DATE '2025-02-21' AS expiry, \
            140.0::DOUBLE AS strike, 'C' AS \"right\", 1736974800000000000::BIGINT AS window_start, \
            5.50::DOUBLE AS close, 200::BIGINT AS volume\
         ) TO '{}' (FORMAT PARQUET)",
        option_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let stock_dir = tmp.path().join("stock_daily").join("trade_date=2025-01-15");
    fs::create_dir_all(&stock_dir)?;
    let stock_parquet = stock_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT 'NVDA' AS ticker, DATE '2025-01-15' AS trade_date, \
            136.0::DOUBLE AS close, 136.0::DOUBLE AS open, 137.0::DOUBLE AS high, \
            133.0::DOUBLE AS low, 5000::BIGINT AS volume, 50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        stock_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 1);
    assert_eq!(array[0]["greek_status"], "missing_rate");
    assert!(array[0]["iv"].is_null());

    Ok(())
}

#[tokio::test]
async fn option_ticker_query_day_greeks_enabled() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = create_greeks_test_env()?;
    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/ticker_query?contract=O:NVDA250221C00140000&start=2025-01-15&end=2025-01-15&resolution=day&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 1);

    let row = &array[0];
    assert!(row.get("iv").is_some());
    assert!(row.get("greek_status").is_some());
    let status = row["greek_status"]
        .as_str()
        .ok_or_else(|| std::io::Error::other("expected string"))?;
    assert_eq!(status, "ok");

    // Call delta should be positive
    let delta = row["delta"]
        .as_f64()
        .ok_or_else(|| std::io::Error::other("delta should be a number"))?;
    assert!(delta > 0.0 && delta < 1.0, "call delta={delta}");

    Ok(())
}

#[tokio::test]
async fn option_ticker_query_greeks_invalid_price_field_returns_400(
) -> Result<(), Box<dyn std::error::Error>> {
    let app = upq_service::app::build_router();
    let request = Request::builder()
        .uri("/option/ticker_query?contract=O:NVDA250221C00140000&start=2025-01-15&end=2025-01-15&include_greeks=true&greek_price_field=mid")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    Ok(())
}

/// Helper: create a test env with option_minute parquet for minute-level Greeks tests.
fn create_greeks_minute_test_env() -> Result<TempDir, Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let conn = Connection::open_in_memory()?;

    // Create option_minute partition (minute data has no underlying/expiry/strike/right columns)
    let option_dir = tmp
        .path()
        .join("option_minute")
        .join("trade_date=2025-01-15");
    fs::create_dir_all(&option_dir)?;
    let option_parquet = option_dir.join("data.parquet");
    // window_start: 2025-01-15 14:30:00 UTC = 1736951400000000000 ns
    // window_start: 2025-01-15 15:00:00 UTC = 1736953200000000000 ns
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                ('O:NVDA250221C00140000', 1736951400000000000::BIGINT, 5.40::DOUBLE, 5.70::DOUBLE, 5.30::DOUBLE, 5.50::DOUBLE, 200::BIGINT, 50::BIGINT),\
                ('O:NVDA250221C00140000', 1736953200000000000::BIGINT, 5.55::DOUBLE, 5.80::DOUBLE, 5.45::DOUBLE, 5.60::DOUBLE, 180::BIGINT, 40::BIGINT)\
            ) AS t(ticker, window_start, open, high, low, close, volume, transactions)\
         ) TO '{}' (FORMAT PARQUET)",
        option_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Create stock_daily partition (spot source for minute Greeks)
    let stock_dir = tmp.path().join("stock_daily").join("trade_date=2025-01-15");
    fs::create_dir_all(&stock_dir)?;
    let stock_parquet = stock_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT \
                'NVDA' AS ticker, \
                DATE '2025-01-15' AS trade_date, \
                135.0::DOUBLE AS open, \
                137.0::DOUBLE AS high, \
                133.0::DOUBLE AS low, \
                136.0::DOUBLE AS close, \
                5000::BIGINT AS volume, \
                50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        stock_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Create rates data
    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let rates_parquet = rates_dir.join("rates.parquet");
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                (DATE '2025-01-15', 4.53::DOUBLE, 4.35::DOUBLE, 4.22::DOUBLE, 4.28::DOUBLE, 4.43::DOUBLE, 4.60::DOUBLE, 4.82::DOUBLE)\
            ) AS t(date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year)\
         ) TO '{}' (FORMAT PARQUET)",
        rates_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    Ok(tmp)
}

/// Regression fixture: minute row belongs to ET trade date 2025-01-15, but its
/// UTC timestamp crosses into 2025-01-16. Greeks lookup should still use the
/// row's trade_date (partition date), not UTC calendar date.
fn create_greeks_minute_utc_boundary_env() -> Result<TempDir, Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let conn = Connection::open_in_memory()?;

    let option_dir = tmp
        .path()
        .join("option_minute")
        .join("trade_date=2025-01-15");
    fs::create_dir_all(&option_dir)?;
    let option_parquet = option_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT \
                'O:NVDA250221C00140000' AS ticker, \
                1736986200000000000::BIGINT AS window_start, \
                5.40::DOUBLE AS open, \
                5.70::DOUBLE AS high, \
                5.30::DOUBLE AS low, \
                5.50::DOUBLE AS close, \
                200::BIGINT AS volume, \
                50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        option_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Only provide spot/rates for 2025-01-15. If minute enrichment incorrectly
    // derives date from UTC timestamp (2025-01-16), this test will fail.
    let stock_dir = tmp.path().join("stock_daily").join("trade_date=2025-01-15");
    fs::create_dir_all(&stock_dir)?;
    let stock_parquet = stock_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT \
                'NVDA' AS ticker, \
                DATE '2025-01-15' AS trade_date, \
                135.0::DOUBLE AS open, \
                137.0::DOUBLE AS high, \
                133.0::DOUBLE AS low, \
                136.0::DOUBLE AS close, \
                5000::BIGINT AS volume, \
                50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        stock_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let rates_parquet = rates_dir.join("rates.parquet");
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                (DATE '2025-01-15', 4.53::DOUBLE, 4.35::DOUBLE, 4.22::DOUBLE, 4.28::DOUBLE, 4.43::DOUBLE, 4.60::DOUBLE, 4.82::DOUBLE)\
            ) AS t(date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year)\
         ) TO '{}' (FORMAT PARQUET)",
        rates_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    Ok(tmp)
}

#[tokio::test]
async fn option_ticker_query_minute_greeks_enabled() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = create_greeks_minute_test_env()?;
    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/ticker_query?contract=O:NVDA250221C00140000&start=2025-01-15T14:00:00&end=2025-01-15T16:00:00&resolution=minute&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 2, "should return 2 minute bars");

    for (i, row) in array.iter().enumerate() {
        assert!(row.get("iv").is_some(), "row {i} should have iv field");
        assert!(
            row.get("delta").is_some(),
            "row {i} should have delta field"
        );
        assert!(
            row.get("gamma").is_some(),
            "row {i} should have gamma field"
        );
        assert!(
            row.get("greek_status").is_some(),
            "row {i} should have greek_status"
        );

        let status = row["greek_status"]
            .as_str()
            .ok_or_else(|| std::io::Error::other("expected string"))?;
        assert_eq!(status, "ok", "row {i} greek_status should be ok");

        // Call delta should be positive
        let delta = row["delta"]
            .as_f64()
            .ok_or_else(|| std::io::Error::other("delta should be a number"))?;
        assert!(
            delta > 0.0 && delta < 1.0,
            "row {i} call delta={delta} should be in (0,1)"
        );

        // IV should be reasonable
        let iv = row["iv"]
            .as_f64()
            .ok_or_else(|| std::io::Error::other("iv should be a number"))?;
        assert!(
            iv > 0.0 && iv < 10.0,
            "row {i} iv={iv} should be reasonable"
        );

        // Strike should have been injected from OPRA contract
        assert!(
            row.get("strike").is_some(),
            "row {i} should have strike from OPRA injection"
        );

        // Meta should reflect minute_precise T convention
        let meta = &row["greek_meta"];
        assert_eq!(
            meta["t_convention"], "minute_precise",
            "row {i} should use minute_precise T convention"
        );
    }

    Ok(())
}

#[tokio::test]
async fn option_ticker_query_minute_greeks_with_minimal_fields_still_computes(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = create_greeks_minute_test_env()?;
    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/ticker_query?contract=O:NVDA250221C00140000&start=2025-01-15T14:00:00&end=2025-01-15T16:00:00&resolution=minute&fields=volume&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 2);

    for row in array {
        // User-requested field should remain.
        assert!(row.get("volume").is_some());
        // Internal enrichment should still work even when user omitted close/window_start.
        assert_eq!(row["greek_status"], "ok");
        assert!(!row["iv"].is_null());
        assert!(!row["delta"].is_null());
        assert_eq!(row["greek_meta"]["t_convention"], "minute_precise");
    }

    Ok(())
}

#[tokio::test]
async fn option_ticker_query_minute_uses_trade_date_not_utc_date_for_spot_and_rates(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = create_greeks_minute_utc_boundary_env()?;
    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/ticker_query?contract=O:NVDA250221C00140000&start=2025-01-15T23:50:00&end=2025-01-16T00:20:00&resolution=minute&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 1);

    // Regression intent: should remain computable from trade_date=2025-01-15
    // data, even when window_start UTC date is 2025-01-16.
    assert_eq!(array[0]["greek_status"], "ok");
    assert!(!array[0]["iv"].is_null(), "iv should be present");
    assert_eq!(array[0]["greek_meta"]["spot_source"], "stock_daily");
    assert_eq!(array[0]["greek_meta"]["t_convention"], "minute_precise");
    assert_eq!(
        array[0]["greek_meta"]["expiry_anchor"],
        "expiry_date_16_00_ET"
    );

    Ok(())
}

#[tokio::test]
async fn option_chain_greeks_below_intrinsic_returns_status(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let conn = Connection::open_in_memory()?;

    // Create option_day with a close price below intrinsic value
    // Deep ITM call: underlying=136, strike=100, so intrinsic ≈ 36
    // Set close=0.01 (way below intrinsic) to trigger below_intrinsic status
    let option_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
    fs::create_dir_all(&option_dir)?;
    let option_parquet = option_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT 'O:NVDA250221C00100000' AS ticker, 'NVDA' AS underlying, DATE '2025-02-21' AS expiry, \
            100.0::DOUBLE AS strike, 'C' AS \"right\", 1736974800000000000::BIGINT AS window_start, \
            0.01::DOUBLE AS open, 0.02::DOUBLE AS high, 0.005::DOUBLE AS low, 0.01::DOUBLE AS close, \
            200::BIGINT AS volume, 50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        option_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Stock spot
    let stock_dir = tmp.path().join("stock_daily").join("trade_date=2025-01-15");
    fs::create_dir_all(&stock_dir)?;
    let stock_parquet = stock_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT 'NVDA' AS ticker, DATE '2025-01-15' AS trade_date, \
            135.0::DOUBLE AS open, 137.0::DOUBLE AS high, 133.0::DOUBLE AS low, \
            136.0::DOUBLE AS close, 5000::BIGINT AS volume, 50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        stock_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Rates
    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let rates_parquet = rates_dir.join("rates.parquet");
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                (DATE '2025-01-15', 4.53::DOUBLE, 4.35::DOUBLE, 4.22::DOUBLE, 4.28::DOUBLE, 4.43::DOUBLE, 4.60::DOUBLE, 4.82::DOUBLE)\
            ) AS t(date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year)\
         ) TO '{}' (FORMAT PARQUET)",
        rates_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 1);
    assert_eq!(
        array[0]["greek_status"], "below_intrinsic",
        "option priced below intrinsic should get below_intrinsic status"
    );
    assert!(
        array[0]["iv"].is_null(),
        "IV should be null for below_intrinsic"
    );
    assert!(
        array[0]["delta"].is_null(),
        "delta should be null for below_intrinsic"
    );

    Ok(())
}

#[tokio::test]
async fn option_chain_greeks_no_bracket_returns_status() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let conn = Connection::open_in_memory()?;

    // Create option_day with impossibly high close price (999.0) for S=136, K=140.
    // BSM cannot bracket the root when the option price exceeds the maximum
    // theoretical price at sigma=10.
    let option_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
    fs::create_dir_all(&option_dir)?;
    let option_parquet = option_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT 'O:NVDA250221C00140000' AS ticker, 'NVDA' AS underlying, DATE '2025-02-21' AS expiry, \
            140.0::DOUBLE AS strike, 'C' AS \"right\", 1736974800000000000::BIGINT AS window_start, \
            999.0::DOUBLE AS open, 999.0::DOUBLE AS high, 999.0::DOUBLE AS low, 999.0::DOUBLE AS close, \
            200::BIGINT AS volume, 50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        option_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Stock spot
    let stock_dir = tmp.path().join("stock_daily").join("trade_date=2025-01-15");
    fs::create_dir_all(&stock_dir)?;
    let stock_parquet = stock_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT 'NVDA' AS ticker, DATE '2025-01-15' AS trade_date, \
            135.0::DOUBLE AS open, 137.0::DOUBLE AS high, 133.0::DOUBLE AS low, \
            136.0::DOUBLE AS close, 5000::BIGINT AS volume, 50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        stock_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Rates
    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let rates_parquet = rates_dir.join("rates.parquet");
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                (DATE '2025-01-15', 4.53::DOUBLE, 4.35::DOUBLE, 4.22::DOUBLE, 4.28::DOUBLE, 4.43::DOUBLE, 4.60::DOUBLE, 4.82::DOUBLE)\
            ) AS t(date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year)\
         ) TO '{}' (FORMAT PARQUET)",
        rates_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 1);
    assert_eq!(
        array[0]["greek_status"], "no_bracket",
        "impossibly high option price should get no_bracket status"
    );
    assert!(array[0]["iv"].is_null(), "IV should be null for no_bracket");

    Ok(())
}

#[tokio::test]
async fn option_chain_greeks_non_finite_input_returns_status(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let conn = Connection::open_in_memory()?;

    // Create option_day with close=0.0 (zero price triggers non_finite_input
    // because enrich_row_with_greeks rejects close <= 0.0).
    let option_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
    fs::create_dir_all(&option_dir)?;
    let option_parquet = option_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT 'O:NVDA250221C00140000' AS ticker, 'NVDA' AS underlying, DATE '2025-02-21' AS expiry, \
            140.0::DOUBLE AS strike, 'C' AS \"right\", 1736974800000000000::BIGINT AS window_start, \
            0.0::DOUBLE AS open, 0.0::DOUBLE AS high, 0.0::DOUBLE AS low, 0.0::DOUBLE AS close, \
            200::BIGINT AS volume, 50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        option_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Stock spot
    let stock_dir = tmp.path().join("stock_daily").join("trade_date=2025-01-15");
    fs::create_dir_all(&stock_dir)?;
    let stock_parquet = stock_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT 'NVDA' AS ticker, DATE '2025-01-15' AS trade_date, \
            135.0::DOUBLE AS open, 137.0::DOUBLE AS high, 133.0::DOUBLE AS low, \
            136.0::DOUBLE AS close, 5000::BIGINT AS volume, 50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        stock_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Rates
    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let rates_parquet = rates_dir.join("rates.parquet");
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                (DATE '2025-01-15', 4.53::DOUBLE, 4.35::DOUBLE, 4.22::DOUBLE, 4.28::DOUBLE, 4.43::DOUBLE, 4.60::DOUBLE, 4.82::DOUBLE)\
            ) AS t(date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year)\
         ) TO '{}' (FORMAT PARQUET)",
        rates_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 1);
    assert_eq!(
        array[0]["greek_status"], "non_finite_input",
        "zero option price should get non_finite_input status"
    );
    assert!(
        array[0]["iv"].is_null(),
        "IV should be null for non_finite_input"
    );

    Ok(())
}

#[tokio::test]
async fn option_chain_greeks_model_error_returns_status() -> Result<(), Box<dyn std::error::Error>>
{
    let tmp = TempDir::new()?;
    let conn = Connection::open_in_memory()?;

    // Create option_day with an invalid right value ('X' instead of 'C' or 'P').
    // During chain enrichment, row_is_call() returns None for unknown right,
    // which triggers model_error status.
    let option_dir = tmp.path().join("option_day").join("trade_date=2025-01-15");
    fs::create_dir_all(&option_dir)?;
    let option_parquet = option_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT 'BADTICKER' AS ticker, 'NVDA' AS underlying, DATE '2025-02-21' AS expiry, \
            140.0::DOUBLE AS strike, 'X' AS \"right\", 1736974800000000000::BIGINT AS window_start, \
            5.50::DOUBLE AS open, 5.70::DOUBLE AS high, 5.30::DOUBLE AS low, 5.50::DOUBLE AS close, \
            200::BIGINT AS volume, 50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        option_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Stock spot
    let stock_dir = tmp.path().join("stock_daily").join("trade_date=2025-01-15");
    fs::create_dir_all(&stock_dir)?;
    let stock_parquet = stock_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT 'NVDA' AS ticker, DATE '2025-01-15' AS trade_date, \
            135.0::DOUBLE AS open, 137.0::DOUBLE AS high, 133.0::DOUBLE AS low, \
            136.0::DOUBLE AS close, 5000::BIGINT AS volume, 50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        stock_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Rates
    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let rates_parquet = rates_dir.join("rates.parquet");
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                (DATE '2025-01-15', 4.53::DOUBLE, 4.35::DOUBLE, 4.22::DOUBLE, 4.28::DOUBLE, 4.43::DOUBLE, 4.60::DOUBLE, 4.82::DOUBLE)\
            ) AS t(date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year)\
         ) TO '{}' (FORMAT PARQUET)",
        rates_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 1);
    assert_eq!(
        array[0]["greek_status"], "model_error",
        "invalid right value should get model_error status"
    );
    assert!(
        array[0]["iv"].is_null(),
        "IV should be null for model_error"
    );

    Ok(())
}

#[tokio::test]
async fn option_ticker_query_minute_near_expiry_approx_returns_status(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let conn = Connection::open_in_memory()?;

    // Create option_minute data where the option expires on 2025-01-15 and
    // window_start is 10 seconds before the 16:00 ET expiry anchor.
    // January is EST, so 16:00 ET = 21:00 UTC.
    // window_start = 2025-01-15 20:59:50 UTC = 1736974790000000000 ns
    // T will be ~10 seconds expressed in years, well below the 1-minute threshold.
    let option_dir = tmp
        .path()
        .join("option_minute")
        .join("trade_date=2025-01-15");
    fs::create_dir_all(&option_dir)?;
    let option_parquet = option_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT \
                'O:NVDA250115C00140000' AS ticker, \
                1736974790000000000::BIGINT AS window_start, \
                5.40::DOUBLE AS open, \
                5.70::DOUBLE AS high, \
                5.30::DOUBLE AS low, \
                5.50::DOUBLE AS close, \
                200::BIGINT AS volume, \
                50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        option_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Stock spot
    let stock_dir = tmp.path().join("stock_daily").join("trade_date=2025-01-15");
    fs::create_dir_all(&stock_dir)?;
    let stock_parquet = stock_dir.join("data.parquet");
    let sql = format!(
        "COPY (\
            SELECT 'NVDA' AS ticker, DATE '2025-01-15' AS trade_date, \
            135.0::DOUBLE AS open, 137.0::DOUBLE AS high, 133.0::DOUBLE AS low, \
            136.0::DOUBLE AS close, 5000::BIGINT AS volume, 50::BIGINT AS transactions\
         ) TO '{}' (FORMAT PARQUET)",
        stock_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    // Rates
    let rates_dir = tmp.path().join("rates");
    fs::create_dir_all(&rates_dir)?;
    let rates_parquet = rates_dir.join("rates.parquet");
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                (DATE '2025-01-15', 4.53::DOUBLE, 4.35::DOUBLE, 4.22::DOUBLE, 4.28::DOUBLE, 4.43::DOUBLE, 4.60::DOUBLE, 4.82::DOUBLE)\
            ) AS t(date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year)\
         ) TO '{}' (FORMAT PARQUET)",
        rates_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/ticker_query?contract=O:NVDA250115C00140000&start=2025-01-15T20:59:00&end=2025-01-15T21:00:00&resolution=minute&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 1);
    assert_eq!(
        array[0]["greek_status"], "near_expiry_approx",
        "option near expiry should get near_expiry_approx status"
    );
    // near_expiry_approx still produces an IV value (approximation)
    assert!(
        !array[0]["iv"].is_null(),
        "IV should be present (approximated) for near_expiry_approx"
    );

    Ok(())
}

/// Helper: create test env with dividend data for NVDA.
/// NVDA spot=136, option expiry=2025-02-21, obs=2025-01-15.
/// Dividend: ex_date=2025-02-03 (in range), amount=0.50.
fn create_greeks_test_env_with_dividends() -> Result<TempDir, Box<dyn std::error::Error>> {
    let tmp = create_greeks_test_env()?;
    let conn = Connection::open_in_memory()?;

    let div_dir = tmp.path().join("dividends");
    fs::create_dir_all(&div_dir)?;
    let div_parquet = div_dir.join("dividends.parquet");
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                ('NVDA', DATE '2025-02-03', 0.50::DOUBLE)\
            ) AS t(ticker, ex_dividend_date, amount)\
         ) TO '{}' (FORMAT PARQUET, COMPRESSION ZSTD)",
        div_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    Ok(tmp)
}

#[tokio::test]
async fn option_chain_greeks_with_dividends_returns_discrete_assumption(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = create_greeks_test_env_with_dividends()?;
    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 2);

    for row in array {
        let meta = &row["greek_meta"];
        assert_eq!(
            meta["dividend_assumption"], "discrete",
            "should be discrete when dividend data exists in range"
        );
        assert!(
            meta["spot_original"].is_number(),
            "spot_original should be present when dividends applied"
        );
        assert!(
            meta["dividend_pv"].is_number(),
            "dividend_pv should be present when dividends applied"
        );

        let spot_orig = meta["spot_original"].as_f64().ok_or("not a number")?;
        let div_pv = meta["dividend_pv"].as_f64().ok_or("not a number")?;
        assert!(
            (spot_orig - 136.0).abs() < 0.01,
            "spot_original={spot_orig} should be ~136"
        );
        assert!(
            div_pv > 0.0 && div_pv < 1.0,
            "dividend_pv={div_pv} should be PV of 0.50 dividend"
        );
    }

    // Greeks should still be computable
    let call_row = &array[1];
    assert_eq!(call_row["greek_status"], "ok");
    assert!(!call_row["iv"].is_null());

    Ok(())
}

#[tokio::test]
async fn option_chain_greeks_without_dividends_has_no_disclosure_fields(
) -> Result<(), Box<dyn std::error::Error>> {
    // Use base env without dividends
    let tmp = create_greeks_test_env()?;
    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;

    for row in array {
        let meta = &row["greek_meta"];
        assert_eq!(meta["dividend_assumption"], "q0");
        // spot_original and dividend_pv should be absent (skip_serializing_if None)
        assert!(
            meta.get("spot_original").is_none() || meta["spot_original"].is_null(),
            "spot_original should not be present without dividends"
        );
        assert!(
            meta.get("dividend_pv").is_none() || meta["dividend_pv"].is_null(),
            "dividend_pv should not be present without dividends"
        );
    }

    Ok(())
}

#[tokio::test]
async fn option_chain_greeks_dividends_affect_delta_value() -> Result<(), Box<dyn std::error::Error>>
{
    // Get Greeks WITHOUT dividends
    let tmp_no_div = create_greeks_test_env()?;
    let app = upq_service::app::build_router_with_storage_root(tmp_no_div.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload_no_div: Value = serde_json::from_slice(&bytes)?;
    let arr_no_div = payload_no_div.as_array().ok_or("expected array")?;
    let call_no_div = &arr_no_div[1]; // call row
    let delta_no_div = call_no_div["delta"].as_f64().ok_or("expected delta")?;

    // Get Greeks WITH dividends
    let tmp_div = create_greeks_test_env_with_dividends()?;
    let app = upq_service::app::build_router_with_storage_root(tmp_div.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload_div: Value = serde_json::from_slice(&bytes)?;
    let arr_div = payload_div.as_array().ok_or("expected array")?;
    let call_div = &arr_div[1]; // call row
    let delta_div = call_div["delta"].as_f64().ok_or("expected delta")?;

    // Dividend reduces effective spot → call delta should decrease
    assert!(
        delta_div < delta_no_div,
        "call delta with dividends ({delta_div}) should be less than without ({delta_no_div})"
    );

    Ok(())
}

#[tokio::test]
async fn option_chain_greeks_extreme_dividend_still_computes(
) -> Result<(), Box<dyn std::error::Error>> {
    // Create env with massive dividend (PV > spot → triggers floor)
    let tmp = create_greeks_test_env()?;
    let conn = Connection::open_in_memory()?;

    let div_dir = tmp.path().join("dividends");
    fs::create_dir_all(&div_dir)?;
    let div_parquet = div_dir.join("dividends.parquet");
    // Dividend of 200.0 on NVDA (spot = 136) → PV > spot → S_adj floors at 0.01
    let sql = format!(
        "COPY (\
            SELECT * FROM (VALUES \
                ('NVDA', DATE '2025-02-03', 200.0::DOUBLE)\
            ) AS t(ticker, ex_dividend_date, amount)\
         ) TO '{}' (FORMAT PARQUET, COMPRESSION ZSTD)",
        div_parquet.to_string_lossy().replace('\'', "''")
    );
    conn.execute_batch(&sql)?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=true")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload
        .as_array()
        .ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 2);

    for row in array {
        let meta = &row["greek_meta"];
        assert_eq!(meta["dividend_assumption"], "discrete");
        let div_pv = meta["dividend_pv"].as_f64().ok_or("expected dividend_pv")?;
        let spot_orig = meta["spot_original"]
            .as_f64()
            .ok_or("expected spot_original")?;
        assert!(
            div_pv > spot_orig,
            "dividend PV ({div_pv}) should exceed spot ({spot_orig})"
        );
        // Greeks should still be computed (S_adj floored at 0.01, not a crash)
        assert!(
            !row["greek_status"].is_null(),
            "greek_status should be present"
        );
    }

    Ok(())
}

// ============== Split Adjustment Tests ==============

#[tokio::test]
async fn test_stock_daily_applies_split_adjustment() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;

    // Write splits.json with NVDA 10:1 split on 2024-06-10
    let splits_json = r#"{"splits":[{"ticker":"NVDA","effective_date":"2024-06-10","ratio":10}]}"#;
    std::fs::write(tmp.path().join("splits.json"), splits_json)?;

    // Create stock_daily parquet with pre-split NVDA price ($1200)
    let daily_dir = tmp.path().join("stock_daily").join("trade_date=2024-06-07");
    std::fs::create_dir_all(&daily_dir)?;
    let conn = Connection::open_in_memory()?;
    let parquet_path = daily_dir.join("data.parquet");
    conn.execute_batch(&format!(
        "COPY (SELECT 'NVDA' AS ticker, 1200.0::DOUBLE AS open, 1220.0::DOUBLE AS high, \
         1180.0::DOUBLE AS low, 1210.0::DOUBLE AS close, BIGINT '5000000' AS volume, \
         BIGINT '100000' AS transactions, DATE '2024-06-07' AS trade_date) \
         TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    ))?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/stock/daily?tickers=NVDA&start=2024-06-07&end=2024-06-07&fields=ticker,date,close,volume")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);
    assert_eq!(response.status(), StatusCode::OK);

    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let arr = payload.as_array().unwrap();
    assert_eq!(arr.len(), 1);

    let close = arr[0]["close"].as_f64().unwrap();
    assert!(
        (close - 121.0).abs() < 0.01,
        "split-adjusted close should be ~121.0, got {}",
        close
    );

    let volume = arr[0]["volume"].as_i64().unwrap();
    assert_eq!(
        volume, 50_000_000,
        "split-adjusted volume should be 50M, got {}",
        volume
    );

    Ok(())
}

#[tokio::test]
async fn test_stock_daily_no_adjustment_for_post_split_dates(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;

    let splits_json = r#"{"splits":[{"ticker":"NVDA","effective_date":"2024-06-10","ratio":10}]}"#;
    std::fs::write(tmp.path().join("splits.json"), splits_json)?;

    let daily_dir = tmp.path().join("stock_daily").join("trade_date=2024-06-10");
    std::fs::create_dir_all(&daily_dir)?;
    let conn = Connection::open_in_memory()?;
    let parquet_path = daily_dir.join("data.parquet");
    conn.execute_batch(&format!(
        "COPY (SELECT 'NVDA' AS ticker, 120.0::DOUBLE AS open, 122.0::DOUBLE AS high, \
         118.0::DOUBLE AS low, 121.0::DOUBLE AS close, BIGINT '50000000' AS volume, \
         BIGINT '200000' AS transactions, DATE '2024-06-10' AS trade_date) \
         TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    ))?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/stock/daily?tickers=NVDA&start=2024-06-10&end=2024-06-10&fields=ticker,date,close,volume")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);
    assert_eq!(response.status(), StatusCode::OK);

    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let arr = payload.as_array().unwrap();
    assert_eq!(arr.len(), 1);

    let close = arr[0]["close"].as_f64().unwrap();
    assert!(
        (close - 121.0).abs() < 0.01,
        "post-split close should be unchanged at 121.0, got {}",
        close
    );

    let volume = arr[0]["volume"].as_i64().unwrap();
    assert_eq!(volume, 50_000_000, "post-split volume should be unchanged");

    Ok(())
}

#[tokio::test]
async fn test_stock_daily_no_splits_json_returns_unadjusted(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    // No splits.json — should fall back to empty SplitCalendar

    let daily_dir = tmp.path().join("stock_daily").join("trade_date=2024-06-07");
    std::fs::create_dir_all(&daily_dir)?;
    let conn = Connection::open_in_memory()?;
    let parquet_path = daily_dir.join("data.parquet");
    conn.execute_batch(&format!(
        "COPY (SELECT 'NVDA' AS ticker, 1200.0::DOUBLE AS open, 1220.0::DOUBLE AS high, \
         1180.0::DOUBLE AS low, 1210.0::DOUBLE AS close, BIGINT '5000000' AS volume, \
         BIGINT '100000' AS transactions, DATE '2024-06-07' AS trade_date) \
         TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    ))?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/stock/daily?tickers=NVDA&start=2024-06-07&end=2024-06-07&fields=ticker,date,close")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);
    assert_eq!(response.status(), StatusCode::OK);

    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let arr = payload.as_array().unwrap();
    assert_eq!(arr.len(), 1);

    let close = arr[0]["close"].as_f64().unwrap();
    assert!(
        (close - 1210.0).abs() < 0.01,
        "without splits.json, close should be unadjusted at 1210.0, got {}",
        close
    );

    Ok(())
}

#[tokio::test]
async fn test_dividends_query_returns_data() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;

    // Create dividends parquet
    let div_dir = tmp.path().join("dividends");
    std::fs::create_dir_all(&div_dir)?;
    let conn = Connection::open_in_memory()?;
    conn.execute_batch(&format!(
        "COPY (SELECT 'JEPQ' AS ticker, DATE '2024-02-01' AS ex_dividend_date, 0.3417::DOUBLE AS amount \
         UNION ALL \
         SELECT 'JEPQ', DATE '2024-03-01', 0.3804::DOUBLE) \
         TO '{}' (FORMAT PARQUET)",
        div_dir
            .join("dividends.parquet")
            .to_string_lossy()
            .replace('\'', "''")
    ))?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/dividends/query?tickers=JEPQ&start=2024-01-01&end=2024-12-31")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);
    assert_eq!(response.status(), StatusCode::OK);

    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let arr = payload.as_array().unwrap();
    assert_eq!(arr.len(), 2);
    assert_eq!(arr[0]["ticker"], "JEPQ");
    assert!((arr[0]["amount"].as_f64().unwrap() - 0.3417).abs() < 0.001);
    Ok(())
}

#[tokio::test]
async fn test_dividends_query_filters_by_date_range() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;

    let div_dir = tmp.path().join("dividends");
    std::fs::create_dir_all(&div_dir)?;
    let conn = Connection::open_in_memory()?;
    conn.execute_batch(&format!(
        "COPY (SELECT 'JEPQ' AS ticker, DATE '2024-02-01' AS ex_dividend_date, 0.3417::DOUBLE AS amount \
         UNION ALL \
         SELECT 'JEPQ', DATE '2024-03-01', 0.3804::DOUBLE \
         UNION ALL \
         SELECT 'JEPQ', DATE '2024-06-01', 0.4500::DOUBLE) \
         TO '{}' (FORMAT PARQUET)",
        div_dir
            .join("dividends.parquet")
            .to_string_lossy()
            .replace('\'', "''")
    ))?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    // Only query Feb-Mar range
    let request = Request::builder()
        .uri("/dividends/query?tickers=JEPQ&start=2024-02-01&end=2024-03-31")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);
    assert_eq!(response.status(), StatusCode::OK);

    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let arr = payload.as_array().unwrap();
    assert_eq!(
        arr.len(),
        2,
        "should only return 2 dividends in Feb-Mar range, got {}",
        arr.len()
    );
    Ok(())
}

#[tokio::test]
async fn test_dividends_query_empty_when_no_parquet() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    // No dividends parquet

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/dividends/query?tickers=JEPQ&start=2024-01-01&end=2024-12-31")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);
    assert_eq!(response.status(), StatusCode::OK);

    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let arr = payload.as_array().unwrap();
    assert_eq!(arr.len(), 0);
    Ok(())
}
