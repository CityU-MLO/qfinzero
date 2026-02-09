use std::convert::Infallible;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use tower::util::ServiceExt;

fn unwrap_infallible<T>(result: Result<T, Infallible>) -> T {
    match result {
        Ok(value) => value,
        Err(never) => match never {},
    }
}

#[tokio::test]
async fn stock_endpoint_accepts_valid_request() -> Result<(), axum::http::Error> {
    let app = upq_service::app::build_router();
    let request = Request::builder()
        .uri("/stock?tickers=AAPL,MSFT&start=2025-01-06T09:30:00&end=2025-01-06T16:00:00")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    Ok(())
}

#[tokio::test]
async fn option_ticker_query_rejects_invalid_resolution() -> Result<(), axum::http::Error> {
    let app = upq_service::app::build_router();
    let request = Request::builder()
        .uri("/option/ticker_query?contract=O:NVDA250117C00136000&start=2025-01-02&end=2025-01-31&resolution=hour")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    Ok(())
}

#[tokio::test]
async fn rates_endpoint_requires_date_range() -> Result<(), axum::http::Error> {
    let app = upq_service::app::build_router();
    let request = Request::builder()
        .uri("/rates/query?start=2025-01-01")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    Ok(())
}
