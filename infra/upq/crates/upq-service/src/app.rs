use axum::extract::Query;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::get;
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::json;
use upq_core::validation::{parse_csv_list, validate_fields, validate_resolution};

pub fn build_router() -> Router {
    Router::new()
        .route("/stock", get(stock))
        .route("/stock/daily", get(stock_daily))
        .route("/option/ticker_query", get(option_ticker_query))
        .route("/option/chain_query", get(option_chain_query))
        .route("/rates/query", get(rates_query))
}

#[derive(Debug, Deserialize)]
struct StockQuery {
    tickers: String,
    start: String,
    end: String,
    fields: Option<String>,
    limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
struct OptionTickerQuery {
    contract: String,
    start: String,
    end: String,
    resolution: Option<String>,
    fields: Option<String>,
}

#[derive(Debug, Deserialize)]
struct OptionChainQuery {
    underlying: String,
    date: String,
    fields: Option<String>,
}

#[derive(Debug, Deserialize)]
struct RatesQuery {
    start: String,
    end: String,
    tenors: Option<String>,
}

async fn stock(Query(params): Query<StockQuery>) -> impl IntoResponse {
    let _ = params.start.as_str();
    let _ = params.end.as_str();
    let _ = params.limit.unwrap_or(10_000);

    let tickers = parse_csv_list(&params.tickers);
    if tickers.is_empty() {
        return invalid_argument("tickers must not be empty");
    }

    if let Some(fields_csv) = params.fields.as_deref() {
        let fields = parse_csv_list(fields_csv);
        let refs: Vec<&str> = fields.iter().map(String::as_str).collect();
        if validate_fields(
            &refs,
            &[
                "ticker",
                "window_start",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "transactions",
            ],
        )
        .is_err()
        {
            return invalid_argument("fields contains unsupported column");
        }
    }

    (StatusCode::OK, Json(json!([]))).into_response()
}

async fn stock_daily(Query(params): Query<StockQuery>) -> impl IntoResponse {
    let _ = params.start.as_str();
    let _ = params.end.as_str();

    let tickers = parse_csv_list(&params.tickers);
    if tickers.is_empty() {
        return invalid_argument("tickers must not be empty");
    }

    (StatusCode::OK, Json(json!([]))).into_response()
}

async fn option_ticker_query(Query(params): Query<OptionTickerQuery>) -> impl IntoResponse {
    let resolution = params.resolution.unwrap_or_else(|| "day".to_string());
    if validate_resolution(&resolution).is_err() {
        return invalid_argument("resolution must be day or minute");
    }

    if params.contract.trim().is_empty()
        || params.start.trim().is_empty()
        || params.end.trim().is_empty()
    {
        return invalid_argument("contract/start/end are required");
    }

    if let Some(fields_csv) = params.fields.as_deref() {
        let fields = parse_csv_list(fields_csv);
        let refs: Vec<&str> = fields.iter().map(String::as_str).collect();
        if validate_fields(
            &refs,
            &[
                "ticker",
                "window_start",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "transactions",
            ],
        )
        .is_err()
        {
            return invalid_argument("fields contains unsupported column");
        }
    }

    (StatusCode::OK, Json(json!([]))).into_response()
}

async fn option_chain_query(Query(params): Query<OptionChainQuery>) -> impl IntoResponse {
    if params.underlying.trim().is_empty() || params.date.trim().is_empty() {
        return invalid_argument("underlying/date are required");
    }

    if let Some(fields_csv) = params.fields.as_deref() {
        let fields = parse_csv_list(fields_csv);
        let refs: Vec<&str> = fields.iter().map(String::as_str).collect();
        if validate_fields(
            &refs,
            &[
                "ticker",
                "underlying",
                "expiry",
                "strike",
                "right",
                "close",
                "volume",
            ],
        )
        .is_err()
        {
            return invalid_argument("fields contains unsupported column");
        }
    }

    (StatusCode::OK, Json(json!([]))).into_response()
}

async fn rates_query(Query(params): Query<RatesQuery>) -> impl IntoResponse {
    if params.start.trim().is_empty() || params.end.trim().is_empty() {
        return invalid_argument("start/end are required");
    }

    if let Some(tenors_csv) = params.tenors.as_deref() {
        let tenors = parse_csv_list(tenors_csv);
        let refs: Vec<&str> = tenors.iter().map(String::as_str).collect();
        if validate_fields(
            &refs,
            &[
                "yield_1_month",
                "yield_3_month",
                "yield_1_year",
                "yield_2_year",
                "yield_5_year",
                "yield_10_year",
                "yield_30_year",
            ],
        )
        .is_err()
        {
            return invalid_argument("tenors contains unsupported value");
        }
    }

    (StatusCode::OK, Json(json!([]))).into_response()
}

fn invalid_argument(message: &str) -> axum::response::Response {
    (
        StatusCode::BAD_REQUEST,
        Json(json!({
            "code": "invalid_argument",
            "message": message,
        })),
    )
        .into_response()
}
