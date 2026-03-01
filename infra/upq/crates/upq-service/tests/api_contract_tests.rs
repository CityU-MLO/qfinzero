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
async fn freshness_endpoint_detects_latest_partition_date(
) -> Result<(), Box<dyn std::error::Error>> {
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
                1736899200000000000::BIGINT AS window_start, \
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
                ('O:NVDA250221C00140000', 'NVDA', DATE '2025-02-21', 140.0::DOUBLE, 'C', 1736899200000000000::BIGINT, 5.40::DOUBLE, 5.70::DOUBLE, 5.30::DOUBLE, 5.50::DOUBLE, 200::BIGINT, 50::BIGINT),\
                ('O:NVDA250221P00130000', 'NVDA', DATE '2025-02-21', 130.0::DOUBLE, 'P', 1736899200000000000::BIGINT, 2.20::DOUBLE, 2.50::DOUBLE, 2.10::DOUBLE, 2.30::DOUBLE, 150::BIGINT, 30::BIGINT)\
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
async fn option_chain_greeks_disabled_returns_legacy_fields() -> Result<(), Box<dyn std::error::Error>>
{
    let tmp = create_greeks_test_env()?;
    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/option/chain_query?underlying=NVDA&date=2025-01-15&include_greeks=false")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let array = payload.as_array().ok_or_else(|| std::io::Error::other("expected array"))?;
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
    let array = payload.as_array().ok_or_else(|| std::io::Error::other("expected array"))?;
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
    assert!(call_row.get("greek_status").is_some(), "should have greek_status");
    assert!(call_row.get("greek_meta").is_some(), "should have greek_meta");

    let status = call_row["greek_status"].as_str().ok_or_else(|| std::io::Error::other("expected string"))?;
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
    let iv = call_row["iv"].as_f64().ok_or_else(|| std::io::Error::other("iv should be a number"))?;
    assert!(iv > 0.0 && iv < 10.0, "iv={iv} should be reasonable");

    // Delta for a call should be positive
    let delta = call_row["delta"].as_f64().ok_or_else(|| std::io::Error::other("delta should be a number"))?;
    assert!(delta > 0.0 && delta < 1.0, "call delta={delta} should be in (0,1)");

    // Put row checks
    let put_status = put_row["greek_status"].as_str().ok_or_else(|| std::io::Error::other("expected string"))?;
    assert_eq!(put_status, "ok");
    let put_delta = put_row["delta"].as_f64().ok_or_else(|| std::io::Error::other("delta should be a number"))?;
    assert!(put_delta > -1.0 && put_delta < 0.0, "put delta={put_delta} should be in (-1,0)");

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
            140.0::DOUBLE AS strike, 'C' AS \"right\", 1736899200000000000::BIGINT AS window_start, \
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
    let array = payload.as_array().ok_or_else(|| std::io::Error::other("expected array"))?;
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
            140.0::DOUBLE AS strike, 'C' AS \"right\", 1736899200000000000::BIGINT AS window_start, \
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
    let array = payload.as_array().ok_or_else(|| std::io::Error::other("expected array"))?;
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
    let array = payload.as_array().ok_or_else(|| std::io::Error::other("expected array"))?;
    assert_eq!(array.len(), 1);

    let row = &array[0];
    assert!(row.get("iv").is_some());
    assert!(row.get("greek_status").is_some());
    let status = row["greek_status"].as_str().ok_or_else(|| std::io::Error::other("expected string"))?;
    assert_eq!(status, "ok");

    // Call delta should be positive
    let delta = row["delta"].as_f64().ok_or_else(|| std::io::Error::other("delta should be a number"))?;
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
