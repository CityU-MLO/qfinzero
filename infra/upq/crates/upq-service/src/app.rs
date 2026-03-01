use std::cell::RefCell;
use std::collections::{HashMap, VecDeque};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::get;
use axum::{Json, Router};
use chrono::{Datelike, Duration, NaiveDate, NaiveDateTime};
use duckdb::types::{TimeUnit, ValueRef};
use duckdb::Connection;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use thiserror::Error;
use tokio::sync::RwLock;
use tokio::task::JoinSet;
use tower_http::trace::{self, TraceLayer};
use tracing::Level;
use upq_core::rates::map_tenor_aliases;
use upq_core::rates::split_by_month;
use upq_core::sql_builder::build_tenor_projection;
use upq_core::validation::{
    parse_csv_list, validate_date, validate_date_or_datetime, validate_datetime, validate_fields,
    validate_resolution,
};

use crate::greeks::{compute_greeks, IvStatus};
use crate::rates_curve::RatesCurve;

const MAX_LIMIT: usize = 100_000;
const RATES_CACHE_CAPACITY: usize = 512;

#[derive(Clone, Debug)]
pub struct AppState {
    storage_root: PathBuf,
    rates_cache: Arc<RwLock<RatesCache>>,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct RatesCacheKey {
    start: String,
    end: String,
    projection: String,
}

#[derive(Debug, Default)]
struct RatesCache {
    rows_by_key: HashMap<RatesCacheKey, Vec<Value>>,
    lru_order: VecDeque<RatesCacheKey>,
}

impl RatesCache {
    fn get(&mut self, key: &RatesCacheKey) -> Option<Vec<Value>> {
        let rows = self.rows_by_key.get(key)?.clone();
        self.touch(key);
        Some(rows)
    }

    fn insert(&mut self, key: RatesCacheKey, rows: Vec<Value>) {
        if self.rows_by_key.contains_key(&key) {
            self.rows_by_key.insert(key.clone(), rows);
            self.touch(&key);
            return;
        }

        if self.rows_by_key.len() >= RATES_CACHE_CAPACITY {
            if let Some(oldest_key) = self.lru_order.pop_front() {
                self.rows_by_key.remove(&oldest_key);
            }
        }
        self.lru_order.push_back(key.clone());
        self.rows_by_key.insert(key, rows);
    }

    fn touch(&mut self, key: &RatesCacheKey) {
        if let Some(index) = self.lru_order.iter().position(|entry| entry == key) {
            let _ = self.lru_order.remove(index);
        }
        self.lru_order.push_back(key.clone());
    }
}

#[derive(Debug, Error)]
enum ServiceError {
    #[error("duckdb error: {0}")]
    Duckdb(#[from] duckdb::Error),
    #[error("join error: {0}")]
    Join(String),
    #[error("connection error: {0}")]
    Connection(String),
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum GreekStatus {
    Ok,
    BelowIntrinsic,
    NoBracket,
    NonFiniteInput,
    NearExpiryApprox,
    MissingSpot,
    MissingRate,
    ModelError,
}

#[derive(Debug, Clone, Serialize)]
pub struct GreekMeta {
    pub model: &'static str,
    pub style_assumption: &'static str,
    pub dividend_assumption: &'static str,
    pub theta_unit: &'static str,
    pub vega_unit: &'static str,
    pub rho_unit: &'static str,
    pub spot_source: &'static str,
    pub rate_source: &'static str,
    pub t_convention: &'static str,
    pub expiry_anchor: &'static str,
}

#[derive(Debug, Clone, Serialize)]
pub struct GreekResult {
    pub iv: Option<f64>,
    pub delta: Option<f64>,
    pub gamma: Option<f64>,
    pub theta: Option<f64>,
    pub vega: Option<f64>,
    pub rho: Option<f64>,
    pub greek_status: GreekStatus,
    pub greek_meta: GreekMeta,
}

pub fn build_router() -> Router {
    let storage_root = env::var("STORAGE_ROOT").unwrap_or_else(|_| "./storage".to_string());
    eprintln!("upq-service storage_root={storage_root}");
    build_router_with_storage_root(storage_root)
}

pub fn build_router_with_storage_root(storage_root: impl Into<PathBuf>) -> Router {
    let state = AppState {
        storage_root: storage_root.into(),
        rates_cache: Arc::new(RwLock::new(RatesCache::default())),
    };

    Router::new()
        .route("/health", get(health))
        .route("/health/freshness", get(health_freshness))
        .route("/stock", get(stock))
        .route("/stock/daily", get(stock_daily))
        .route("/option", get(option))
        .route("/option/ticker_query", get(option_ticker_query))
        .route("/option/chain_query", get(option_chain_query))
        .route("/rates/query", get(rates_query))
        .layer(
            TraceLayer::new_for_http()
                .make_span_with(trace::DefaultMakeSpan::new().level(Level::INFO))
                .on_response(trace::DefaultOnResponse::new().level(Level::INFO)),
        )
        .with_state(state)
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
    include_greeks: Option<bool>,
    greek_model: Option<String>,
    greek_price_field: Option<String>,
}

#[derive(Debug, Deserialize)]
struct OptionChainQuery {
    underlying: String,
    date: String,
    expiry_min: Option<String>,
    expiry_max: Option<String>,
    strike_min: Option<f64>,
    strike_max: Option<f64>,
    r#type: Option<String>,
    fields: Option<String>,
    include_greeks: Option<bool>,
    greek_model: Option<String>,
    greek_price_field: Option<String>,
}

#[derive(Debug, Deserialize)]
struct RatesQuery {
    start: String,
    end: String,
    tenors: Option<String>,
}

async fn stock(
    State(state): State<AppState>,
    Query(params): Query<StockQuery>,
) -> axum::response::Response {
    let limit = params.limit.unwrap_or(10_000);
    if limit == 0 || limit > MAX_LIMIT {
        return invalid_argument("limit must be between 1 and 100000");
    }

    if validate_datetime(&params.start).is_err() || validate_datetime(&params.end).is_err() {
        return invalid_argument("start/end must be ISO datetime: YYYY-MM-DDTHH:MM:SS");
    }

    let tickers = parse_csv_list(&params.tickers);
    if tickers.is_empty() {
        return invalid_argument("tickers must not be empty");
    }

    let projection = match parse_stock_projection(params.fields.as_deref()) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };

    let start_ns = match parse_datetime_ns(&params.start, false) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };
    let end_ns = match parse_datetime_ns(&params.end, true) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };
    let start_date = match extract_date_from_datetime(&params.start) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };
    let end_date = match extract_date_from_datetime(&params.end) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };

    let dataset_dir = state.storage_root.join("stock_minute");
    if !has_any_parquet_file(&dataset_dir) {
        return (StatusCode::OK, Json(json!([]))).into_response();
    }

    let path_pattern = dataset_dir
        .join("trade_date=*")
        .join("*.parquet")
        .to_string_lossy()
        .to_string();

    let ticker_sql = tickers
        .iter()
        .map(|ticker| sql_quote(ticker))
        .collect::<Vec<String>>()
        .join(", ");

    let sql = format!(
        "SELECT {projection} FROM read_parquet('{path}') \
         WHERE trade_date >= DATE '{start_date}' AND trade_date <= DATE '{end_date}' \
         AND ticker IN ({tickers}) AND window_start >= {start_ns} AND window_start <= {end_ns} \
         ORDER BY ticker, window_start LIMIT {limit}",
        path = sql_escape_literal(&path_pattern),
        start_date = sql_escape_literal(&start_date),
        end_date = sql_escape_literal(&end_date),
        tickers = ticker_sql,
    );

    match run_sql_json_async(sql).await {
        Ok(rows) => (StatusCode::OK, Json(Value::Array(rows))).into_response(),
        Err(error) => internal_error(error),
    }
}

async fn stock_daily(
    State(state): State<AppState>,
    Query(params): Query<StockQuery>,
) -> axum::response::Response {
    if validate_date(&params.start).is_err() || validate_date(&params.end).is_err() {
        return invalid_argument("start/end must be date: YYYY-MM-DD");
    }

    let tickers = parse_csv_list(&params.tickers);
    if tickers.is_empty() {
        return invalid_argument("tickers must not be empty");
    }

    let projection = match parse_stock_daily_projection(params.fields.as_deref()) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };

    let dataset_dir = state.storage_root.join("stock_daily");
    if !has_any_parquet_file(&dataset_dir) {
        return (StatusCode::OK, Json(json!([]))).into_response();
    }

    let path_pattern = dataset_dir
        .join("trade_date=*")
        .join("*.parquet")
        .to_string_lossy()
        .to_string();

    let ticker_sql = tickers
        .iter()
        .map(|ticker| sql_quote(ticker))
        .collect::<Vec<String>>()
        .join(", ");

    let sql = format!(
        "SELECT {projection} FROM read_parquet('{path}') \
         WHERE ticker IN ({tickers}) AND trade_date >= DATE '{start}' AND trade_date <= DATE '{end}' \
         ORDER BY ticker, trade_date",
        path = sql_escape_literal(&path_pattern),
        tickers = ticker_sql,
        start = sql_escape_literal(&params.start),
        end = sql_escape_literal(&params.end),
    );

    match run_sql_json_async(sql).await {
        Ok(rows) => (StatusCode::OK, Json(Value::Array(rows))).into_response(),
        Err(error) => internal_error(error),
    }
}

async fn option_ticker_query(
    State(state): State<AppState>,
    Query(params): Query<OptionTickerQuery>,
) -> axum::response::Response {
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

    if validate_date_or_datetime(&params.start).is_err()
        || validate_date_or_datetime(&params.end).is_err()
    {
        return invalid_argument("start/end must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS");
    }

    let include_greeks = params.include_greeks.unwrap_or(false);
    if include_greeks {
        if let Some(ref model) = params.greek_model {
            if model != "bsm" {
                return invalid_argument("greek_model must be bsm");
            }
        }
        if let Some(ref price_field) = params.greek_price_field {
            if price_field != "close" {
                return invalid_argument("greek_price_field must be close");
            }
        }
    }

    let projection = match parse_option_ticker_projection(params.fields.as_deref(), &resolution) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };

    // When Greeks are enabled for day resolution, ensure extra columns
    let greeks_projection = if include_greeks && resolution == "day" {
        ensure_greeks_columns_ticker_day(&projection)
    } else if include_greeks && resolution == "minute" {
        // For minute, we need close, and we also need trade_date to look up rates/spot
        ensure_greeks_columns_ticker_minute(&projection)
    } else {
        projection.clone()
    };

    let start_ns = match parse_date_or_datetime_ns(&params.start, false) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };
    let end_ns = match parse_date_or_datetime_ns(&params.end, true) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };
    let start_date = match extract_date_from_date_or_datetime(&params.start) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };
    let end_date = match extract_date_from_date_or_datetime(&params.end) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };

    let dataset_dir = if resolution == "minute" {
        state.storage_root.join("option_minute")
    } else {
        state.storage_root.join("option_day")
    };

    if !has_any_parquet_file(&dataset_dir) {
        return (StatusCode::OK, Json(json!([]))).into_response();
    }

    let path_pattern = dataset_dir
        .join("trade_date=*")
        .join("*.parquet")
        .to_string_lossy()
        .to_string();

    let sql = format!(
        "SELECT {greeks_projection} FROM read_parquet('{path}') \
         WHERE trade_date >= DATE '{start_date}' AND trade_date <= DATE '{end_date}' \
         AND ticker = {contract} AND window_start >= {start_ns} AND window_start <= {end_ns} \
         ORDER BY window_start",
        path = sql_escape_literal(&path_pattern),
        start_date = sql_escape_literal(&start_date),
        end_date = sql_escape_literal(&end_date),
        contract = sql_quote(&params.contract),
    );

    match run_sql_json_async(sql).await {
        Ok(mut rows) => {
            if include_greeks {
                let storage_root = state.storage_root.clone();
                let contract = params.contract.clone();
                let resolution_clone = resolution.clone();
                let result = tokio::task::spawn_blocking(move || {
                    enrich_ticker_rows(&storage_root, &contract, &resolution_clone, &mut rows);
                    rows
                })
                .await;
                match result {
                    Ok(enriched) => (StatusCode::OK, Json(Value::Array(enriched))).into_response(),
                    Err(join_error) => internal_error(ServiceError::Join(join_error.to_string())),
                }
            } else {
                (StatusCode::OK, Json(Value::Array(rows))).into_response()
            }
        }
        Err(error) => internal_error(error),
    }
}

async fn option() -> axum::response::Response {
    (
        StatusCode::OK,
        Json(json!({
            "ticker_query_path": "/option/ticker_query",
            "chain_query_path": "/option/chain_query"
        })),
    )
        .into_response()
}

async fn health() -> axum::response::Response {
    (
        StatusCode::OK,
        Json(json!({ "status": "ok", "version": "0.1.0" })),
    )
        .into_response()
}

async fn health_freshness(State(state): State<AppState>) -> axum::response::Response {
    let storage_root = state.storage_root.clone();
    let result = tokio::task::spawn_blocking(move || build_freshness_response(&storage_root)).await;
    match result {
        Ok(Ok(value)) => (StatusCode::OK, Json(value)).into_response(),
        Ok(Err(error)) => internal_error(error),
        Err(join_error) => internal_error(ServiceError::Join(join_error.to_string())),
    }
}

fn build_freshness_response(storage_root: &Path) -> Result<Value, ServiceError> {
    let checked_at = chrono::Utc::now().to_rfc3339();
    let mut sources = Map::new();

    // Partitioned datasets: (name, unique_key_label, has_window_start)
    // has_window_start=true means the dataset has a window_start BIGINT column
    let partitioned_datasets = [
        ("stock_minute", "tickers", true),
        ("stock_daily", "tickers", false),
        ("option_minute", "tickers", true),
        ("option_day", "tickers", true),
    ];

    for (dataset_name, unique_key_label, has_window_start) in &partitioned_datasets {
        let dataset_dir = storage_root.join(dataset_name);
        if !has_any_parquet_file(&dataset_dir) {
            continue;
        }

        let partition_dirs = collect_partition_dirs(&dataset_dir);
        if partition_dirs.is_empty() {
            continue;
        }

        let partition_count = partition_dirs.len() as i64;
        let latest_date = partition_dirs
            .iter()
            .filter_map(|dir_name| dir_name.strip_prefix("trade_date="))
            .max()
            .map(String::from);

        let latest_date_str = match &latest_date {
            Some(d) => d.as_str(),
            None => continue,
        };

        let latest_partition_path = dataset_dir
            .join(format!("trade_date={latest_date_str}"))
            .join("*.parquet")
            .to_string_lossy()
            .to_string();

        let mut source_info = Map::new();
        source_info.insert("latest_date".to_string(), json!(latest_date_str));

        // Single DuckDB query for all stats on the latest partition
        let ts_col = if *has_window_start {
            ", MAX(window_start) AS latest_timestamp"
        } else {
            ""
        };
        let stats_sql = format!(
            "SELECT COUNT(*) AS record_count, COUNT(DISTINCT ticker) AS unique_keys{ts_col} FROM read_parquet('{}')",
            sql_escape_literal(&latest_partition_path)
        );

        if let Ok(rows) = run_sql_json(&stats_sql) {
            if let Some(row) = rows.first() {
                if let Some(record_count) = row.get("record_count") {
                    source_info.insert("record_count".to_string(), record_count.clone());
                }
                if let Some(unique_keys) = row.get("unique_keys") {
                    source_info.insert("unique_keys".to_string(), unique_keys.clone());
                }
                if *has_window_start {
                    if let Some(latest_ts) = row.get("latest_timestamp") {
                        if !latest_ts.is_null() {
                            source_info.insert("latest_timestamp".to_string(), latest_ts.clone());
                        }
                    }
                }
            }
        }

        source_info.insert("unique_key_label".to_string(), json!(unique_key_label));
        source_info.insert("partition_count".to_string(), json!(partition_count));

        sources.insert(dataset_name.to_string(), Value::Object(source_info));
    }

    // Rates dataset
    let rates_file = storage_root.join("rates").join("rates.parquet");
    if rates_file.exists() {
        let rates_path = rates_file.to_string_lossy().to_string();
        let sql = format!(
            "SELECT MAX(date) AS latest_date FROM read_parquet('{}')",
            sql_escape_literal(&rates_path)
        );
        if let Ok(rows) = run_sql_json(&sql) {
            if let Some(row) = rows.first() {
                let mut rates_info = Map::new();
                if let Some(latest_date) = row.get("latest_date") {
                    rates_info.insert("latest_date".to_string(), latest_date.clone());
                }
                // 7 standard tenors: 1M, 3M, 1Y, 2Y, 5Y, 10Y, 30Y
                rates_info.insert("unique_keys".to_string(), json!(7));
                rates_info.insert("unique_key_label".to_string(), json!("tenors"));
                sources.insert("rates".to_string(), Value::Object(rates_info));
            }
        }
    }

    Ok(json!({
        "service": "upq",
        "checked_at": checked_at,
        "sources": Value::Object(sources),
    }))
}

fn collect_partition_dirs(dataset_dir: &Path) -> Vec<String> {
    let entries = match fs::read_dir(dataset_dir) {
        Ok(entries) => entries,
        Err(_) => return Vec::new(),
    };

    let mut partition_names = Vec::new();
    for entry in entries.flatten() {
        let entry_path = entry.path();
        if !entry_path.is_dir() {
            continue;
        }
        let dir_name = match entry.file_name().to_str() {
            Some(name) => name.to_string(),
            None => continue,
        };
        if !dir_name.starts_with("trade_date=") {
            continue;
        }
        // Only count partitions that contain parquet files
        if has_any_parquet_file(&entry_path) {
            partition_names.push(dir_name);
        }
    }
    partition_names
}

async fn option_chain_query(
    State(state): State<AppState>,
    Query(params): Query<OptionChainQuery>,
) -> axum::response::Response {
    if params.underlying.trim().is_empty() || params.date.trim().is_empty() {
        return invalid_argument("underlying/date are required");
    }
    if validate_date(&params.date).is_err() {
        return invalid_argument("date must be YYYY-MM-DD");
    }

    if let Some(expiry_min) = params.expiry_min.as_deref() {
        if validate_date(expiry_min).is_err() {
            return invalid_argument("expiry_min must be YYYY-MM-DD");
        }
    }
    if let Some(expiry_max) = params.expiry_max.as_deref() {
        if validate_date(expiry_max).is_err() {
            return invalid_argument("expiry_max must be YYYY-MM-DD");
        }
    }

    if let Some(option_type) = params.r#type.as_deref() {
        let value = option_type.trim().to_ascii_uppercase();
        if value != "C" && value != "P" {
            return invalid_argument("type must be C or P");
        }
    }
    if let Some(strike_min) = params.strike_min {
        if !strike_min.is_finite() {
            return invalid_argument("strike_min must be finite");
        }
    }
    if let Some(strike_max) = params.strike_max {
        if !strike_max.is_finite() {
            return invalid_argument("strike_max must be finite");
        }
    }

    let include_greeks = params.include_greeks.unwrap_or(false);
    if include_greeks {
        if let Some(ref model) = params.greek_model {
            if model != "bsm" {
                return invalid_argument("greek_model must be bsm");
            }
        }
        if let Some(ref price_field) = params.greek_price_field {
            if price_field != "close" {
                return invalid_argument("greek_price_field must be close");
            }
        }
    }

    let projection = match parse_option_chain_projection(params.fields.as_deref()) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
    };

    // When Greeks are enabled, we need certain columns even if user didn't request them.
    let greeks_projection = if include_greeks {
        ensure_greeks_columns_chain(&projection)
    } else {
        projection.clone()
    };

    let partition_dir = state
        .storage_root
        .join("option_day")
        .join(format!("trade_date={}", params.date));
    if !has_any_parquet_file(&partition_dir) {
        return (StatusCode::OK, Json(json!([]))).into_response();
    }

    let path_pattern = partition_dir
        .join("*.parquet")
        .to_string_lossy()
        .to_string();

    let mut base_filters = vec![format!("underlying = {}", sql_quote(&params.underlying))];
    if let Some(strike_min) = params.strike_min {
        base_filters.push(format!("strike >= {strike_min}"));
    }
    if let Some(strike_max) = params.strike_max {
        base_filters.push(format!("strike <= {strike_max}"));
    }
    if let Some(option_type) = params.r#type.as_deref() {
        base_filters.push(format!(
            "\"right\" = '{}'",
            sql_escape_literal(&option_type.trim().to_ascii_uppercase())
        ));
    }

    let mut exact_filters = base_filters.clone();
    if let Some(expiry_min) = params.expiry_min.as_deref() {
        exact_filters.push(format!(
            "expiry >= DATE '{}'",
            sql_escape_literal(expiry_min)
        ));
    }
    if let Some(expiry_max) = params.expiry_max.as_deref() {
        exact_filters.push(format!(
            "expiry <= DATE '{}'",
            sql_escape_literal(expiry_max)
        ));
    }

    // Helper: optionally enrich rows with Greeks and return response.
    let maybe_enrich = |mut rows: Vec<Value>| async {
        if include_greeks {
            let storage_root = state.storage_root.clone();
            let date = params.date.clone();
            let underlying = params.underlying.clone();
            let result = tokio::task::spawn_blocking(move || {
                enrich_chain_rows_day(&storage_root, &date, &underlying, &mut rows);
                rows
            })
            .await;
            match result {
                Ok(enriched) => (StatusCode::OK, Json(Value::Array(enriched))).into_response(),
                Err(join_error) => internal_error(ServiceError::Join(join_error.to_string())),
            }
        } else {
            (StatusCode::OK, Json(Value::Array(rows))).into_response()
        }
    };

    match run_option_chain_rows(&path_pattern, &greeks_projection, &exact_filters).await {
        Ok(rows) if !rows.is_empty() => maybe_enrich(rows).await,
        Ok(_) => {
            // Fallback only applies to exact-expiry requests. Range filters keep legacy behavior.
            let Some(exact_expiry) =
                exact_expiry_target(params.expiry_min.as_deref(), params.expiry_max.as_deref())
            else {
                return (StatusCode::OK, Json(json!([]))).into_response();
            };

            // If base filters have no rows at all (same underlying/type/strike context),
            // fallback cannot produce meaningful results and should exit early.
            let base_has_rows = match option_chain_base_has_rows(&path_pattern, &base_filters).await
            {
                Ok(value) => value,
                Err(error) => return internal_error(error),
            };
            if !base_has_rows {
                return (StatusCode::OK, Json(json!([]))).into_response();
            }

            let target_expiry = match NaiveDate::parse_from_str(exact_expiry, "%Y-%m-%d") {
                Ok(value) => value,
                Err(_) => return invalid_argument("expiry_min/expiry_max must be YYYY-MM-DD"),
            };

            // Two-stage fallback:
            // 1) nearest expiry within ±7 days of requested expiry
            // 2) if still empty, nearest expiry within requested expiry's calendar month
            let fallback_expiry =
                match find_nearest_fallback_expiry(&path_pattern, &base_filters, target_expiry)
                    .await
                {
                    Ok(value) => value,
                    Err(error) => return internal_error(error),
                };

            let Some(selected_expiry) = fallback_expiry else {
                return (StatusCode::OK, Json(json!([]))).into_response();
            };

            let mut fallback_filters = base_filters;
            let selected_expiry_str = selected_expiry.format("%Y-%m-%d").to_string();
            fallback_filters.push(format!(
                "expiry >= DATE '{}'",
                sql_escape_literal(&selected_expiry_str)
            ));
            fallback_filters.push(format!(
                "expiry <= DATE '{}'",
                sql_escape_literal(&selected_expiry_str)
            ));

            match run_option_chain_rows(&path_pattern, &greeks_projection, &fallback_filters).await
            {
                Ok(fallback_rows) => maybe_enrich(fallback_rows).await,
                Err(error) => internal_error(error),
            }
        }
        Err(error) => internal_error(error),
    }
}

fn exact_expiry_target<'a>(
    expiry_min: Option<&'a str>,
    expiry_max: Option<&'a str>,
) -> Option<&'a str> {
    match (expiry_min, expiry_max) {
        (Some(min), Some(max)) if min == max => Some(min),
        _ => None,
    }
}

fn build_option_chain_sql(path_pattern: &str, projection: &str, filters: &[String]) -> String {
    format!(
        "SELECT {projection} FROM read_parquet('{path}') WHERE {filters} ORDER BY expiry, strike",
        path = sql_escape_literal(path_pattern),
        filters = filters.join(" AND "),
    )
}

async fn run_option_chain_rows(
    path_pattern: &str,
    projection: &str,
    filters: &[String],
) -> Result<Vec<Value>, ServiceError> {
    let sql = build_option_chain_sql(path_pattern, projection, filters);
    run_sql_json_async(sql).await
}

async fn option_chain_base_has_rows(
    path_pattern: &str,
    base_filters: &[String],
) -> Result<bool, ServiceError> {
    let sql = format!(
        "SELECT 1 AS has_row FROM read_parquet('{path}') WHERE {filters} LIMIT 1",
        path = sql_escape_literal(path_pattern),
        filters = base_filters.join(" AND "),
    );
    let rows = run_sql_json_async(sql).await?;
    Ok(!rows.is_empty())
}

async fn find_nearest_fallback_expiry(
    path_pattern: &str,
    base_filters: &[String],
    target_expiry: NaiveDate,
) -> Result<Option<NaiveDate>, ServiceError> {
    let week_start = target_expiry - Duration::days(7);
    let week_end = target_expiry + Duration::days(7);

    let weekly_candidates =
        query_distinct_expiries_in_window(path_pattern, base_filters, week_start, week_end).await?;
    if let Some(expiry) = select_nearest_expiry(target_expiry, &weekly_candidates) {
        return Ok(Some(expiry));
    }

    let month_start = match NaiveDate::from_ymd_opt(target_expiry.year(), target_expiry.month(), 1)
    {
        Some(value) => value,
        None => return Ok(None),
    };
    let (next_year, next_month) = if target_expiry.month() == 12 {
        (target_expiry.year() + 1, 1)
    } else {
        (target_expiry.year(), target_expiry.month() + 1)
    };
    let month_end = match NaiveDate::from_ymd_opt(next_year, next_month, 1) {
        Some(next_month_start) => next_month_start - Duration::days(1),
        None => return Ok(None),
    };

    let monthly_candidates =
        query_distinct_expiries_in_window(path_pattern, base_filters, month_start, month_end)
            .await?;
    Ok(select_nearest_expiry(target_expiry, &monthly_candidates))
}

async fn query_distinct_expiries_in_window(
    path_pattern: &str,
    base_filters: &[String],
    window_start: NaiveDate,
    window_end: NaiveDate,
) -> Result<Vec<NaiveDate>, ServiceError> {
    let mut filters = base_filters.to_vec();
    filters.push(format!(
        "expiry >= DATE '{}'",
        sql_escape_literal(&window_start.format("%Y-%m-%d").to_string())
    ));
    filters.push(format!(
        "expiry <= DATE '{}'",
        sql_escape_literal(&window_end.format("%Y-%m-%d").to_string())
    ));

    let sql = format!(
        "SELECT DISTINCT expiry FROM read_parquet('{path}') WHERE {filters} ORDER BY expiry",
        path = sql_escape_literal(path_pattern),
        filters = filters.join(" AND "),
    );
    let rows = run_sql_json_async(sql).await?;

    let expiries = rows
        .iter()
        .filter_map(|row| row.get("expiry").and_then(Value::as_str))
        .filter_map(|value| NaiveDate::parse_from_str(value, "%Y-%m-%d").ok())
        .collect::<Vec<NaiveDate>>();

    Ok(expiries)
}

fn select_nearest_expiry(target_expiry: NaiveDate, candidates: &[NaiveDate]) -> Option<NaiveDate> {
    candidates
        .iter()
        .min_by_key(|candidate| {
            // Tie-break by earlier expiry when distances are equal.
            let distance = (**candidate - target_expiry).num_days().abs();
            (distance, **candidate)
        })
        .copied()
}

async fn rates_query(
    State(state): State<AppState>,
    Query(params): Query<RatesQuery>,
) -> axum::response::Response {
    if params.start.trim().is_empty() || params.end.trim().is_empty() {
        return invalid_argument("start/end are required");
    }

    if validate_date(&params.start).is_err() || validate_date(&params.end).is_err() {
        return invalid_argument("start/end must be date: YYYY-MM-DD");
    }

    let projection = if let Some(tenors_csv) = params.tenors.as_deref() {
        let tenors = parse_csv_list(tenors_csv);
        let refs: Vec<&str> = tenors.iter().map(String::as_str).collect();
        let mapped = match map_tenor_aliases(&refs) {
            Ok(columns) => columns,
            Err(_) => return invalid_argument("tenors contains unsupported value"),
        };
        let mapped_refs: Vec<&str> = mapped.to_vec();
        build_tenor_projection(&mapped_refs)
    } else {
        build_tenor_projection(&[])
    };

    let cache_key = RatesCacheKey {
        start: params.start.clone(),
        end: params.end.clone(),
        projection: projection.clone(),
    };
    if let Some(cached_rows) = state.rates_cache.write().await.get(&cache_key) {
        return (StatusCode::OK, Json(Value::Array(cached_rows))).into_response();
    }

    let file_path = state.storage_root.join("rates").join("rates.parquet");
    if !file_path.exists() {
        return (StatusCode::OK, Json(json!([]))).into_response();
    }

    let file_path_literal = sql_escape_literal(&file_path.to_string_lossy());
    let chunks = match split_by_month(&params.start, &params.end) {
        Ok(value) => value,
        Err(_) => return invalid_argument("start/end must be date: YYYY-MM-DD"),
    };

    let mut join_set = JoinSet::new();
    for (chunk_start, chunk_end) in chunks {
        let sql = format!(
            "SELECT {projection} FROM read_parquet('{path}') \
             WHERE date >= DATE '{start}' AND date <= DATE '{end}' ORDER BY date",
            projection = projection,
            path = file_path_literal,
            start = sql_escape_literal(&chunk_start),
            end = sql_escape_literal(&chunk_end),
        );
        join_set.spawn_blocking(move || run_sql_json(&sql));
    }

    let mut rows = Vec::new();
    while let Some(task_result) = join_set.join_next().await {
        match task_result {
            Ok(Ok(mut chunk_rows)) => rows.append(&mut chunk_rows),
            Ok(Err(error)) => return internal_error(error),
            Err(join_error) => return internal_error(ServiceError::Join(join_error.to_string())),
        }
    }

    rows.sort_by(|left, right| {
        let left_date = left.get("date").and_then(Value::as_str).unwrap_or_default();
        let right_date = right
            .get("date")
            .and_then(Value::as_str)
            .unwrap_or_default();
        left_date.cmp(right_date)
    });
    rows.dedup_by(|left, right| {
        let left_date = left.get("date").and_then(Value::as_str).unwrap_or_default();
        let right_date = right
            .get("date")
            .and_then(Value::as_str)
            .unwrap_or_default();
        left_date == right_date
    });

    {
        let mut cache = state.rates_cache.write().await;
        cache.insert(cache_key, rows.clone());
    }

    (StatusCode::OK, Json(Value::Array(rows))).into_response()
}

/// Check if a column list already contains a given column name (or alias).
fn projection_has_column(cols: &[String], name: &str) -> bool {
    cols.iter().any(|c| {
        let lower = c.to_lowercase();
        lower == name
            || lower.contains(&format!("as {name}"))
            || lower.starts_with(&format!("{name} "))
    })
}

/// Ensure the chain query projection includes columns needed for Greeks computation.
fn ensure_greeks_columns_chain(base_projection: &str) -> String {
    let mut cols: Vec<String> = base_projection.split(", ").map(String::from).collect();

    if !projection_has_column(&cols, "strike") {
        cols.push("strike".to_string());
    }
    if !projection_has_column(&cols, "close") {
        cols.push("close".to_string());
    }
    if !projection_has_column(&cols, "expiry") {
        cols.push("expiry".to_string());
    }
    if !projection_has_column(&cols, "type") && !projection_has_column(&cols, "right") {
        cols.push("\"right\" AS type".to_string());
    }

    cols.join(", ")
}

/// Ensure the ticker query day-resolution projection includes columns needed for Greeks.
fn ensure_greeks_columns_ticker_day(base_projection: &str) -> String {
    let mut cols: Vec<String> = base_projection.split(", ").map(String::from).collect();

    if !projection_has_column(&cols, "strike") {
        cols.push("strike".to_string());
    }
    if !projection_has_column(&cols, "close") {
        cols.push("close".to_string());
    }
    if !projection_has_column(&cols, "expiry") {
        cols.push("expiry".to_string());
    }
    if !projection_has_column(&cols, "type") && !projection_has_column(&cols, "right") {
        cols.push("\"right\" AS type".to_string());
    }
    if !projection_has_column(&cols, "underlying") {
        cols.push("underlying".to_string());
    }
    if !projection_has_column(&cols, "window_start") {
        cols.push("window_start".to_string());
    }

    cols.join(", ")
}

/// Enrich chain query rows (day-level) with Greeks.
fn enrich_chain_rows_day(storage_root: &Path, date: &str, underlying: &str, rows: &mut [Value]) {
    // Per-request caches
    let spot = fetch_spot_daily(storage_root, underlying, date);
    let rates_row = fetch_rates_row(storage_root, date);

    let curve = rates_row
        .as_ref()
        .and_then(|r| RatesCurve::from_json_row(r).ok());

    let observation_date = NaiveDate::parse_from_str(date, "%Y-%m-%d").ok();

    for row_val in rows.iter_mut() {
        let row = match row_val.as_object_mut() {
            Some(r) => r,
            None => continue,
        };

        let spot_val = match spot {
            Some(s) => s,
            None => {
                let result = null_greek_result(
                    GreekStatus::MissingSpot,
                    "stock_daily",
                    "calendar_days_over_365",
                    "expiry_date_eod",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        let curve_ref = match curve.as_ref() {
            Some(c) => c,
            None => {
                let result = null_greek_result(
                    GreekStatus::MissingRate,
                    "stock_daily",
                    "calendar_days_over_365",
                    "expiry_date_eod",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        let is_call = match row_is_call(row) {
            Some(v) => v,
            None => {
                let result = null_greek_result(
                    GreekStatus::ModelError,
                    "stock_daily",
                    "calendar_days_over_365",
                    "expiry_date_eod",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        // Parse expiry from row
        let expiry_str = match row.get("expiry").and_then(Value::as_str) {
            Some(e) => e.to_string(),
            None => {
                let result = null_greek_result(
                    GreekStatus::ModelError,
                    "stock_daily",
                    "calendar_days_over_365",
                    "expiry_date_eod",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        let expiry_date = match NaiveDate::parse_from_str(&expiry_str, "%Y-%m-%d").ok() {
            Some(d) => d,
            None => {
                let result = null_greek_result(
                    GreekStatus::ModelError,
                    "stock_daily",
                    "calendar_days_over_365",
                    "expiry_date_eod",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        let obs_date = match observation_date {
            Some(d) => d,
            None => {
                let result = null_greek_result(
                    GreekStatus::ModelError,
                    "stock_daily",
                    "calendar_days_over_365",
                    "expiry_date_eod",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        // T = calendar days / 365, floored at a small positive value
        let days_to_expiry = (expiry_date - obs_date).num_days();
        let t_years = if days_to_expiry <= 0 {
            1.0 / (365.0 * 24.0 * 60.0) // ~1 minute floor
        } else {
            days_to_expiry as f64 / 365.0
        };

        enrich_row_with_greeks(
            row,
            spot_val,
            curve_ref,
            t_years,
            is_call,
            "stock_daily",
            "calendar_days_over_365",
            "expiry_date_eod",
        );
    }
}

/// Ensure minute-resolution ticker query has columns needed for Greeks.
fn ensure_greeks_columns_ticker_minute(base_projection: &str) -> String {
    let mut cols: Vec<String> = base_projection.split(", ").map(String::from).collect();

    if !projection_has_column(&cols, "close") {
        cols.push("close".to_string());
    }
    if !projection_has_column(&cols, "window_start") {
        cols.push("window_start".to_string());
    }

    cols.join(", ")
}

/// Enrich ticker query rows with Greeks.
/// For day resolution: similar to chain but needs to parse underlying/expiry from the OPRA contract.
/// For minute resolution: uses window_start for T calculation.
fn enrich_ticker_rows(storage_root: &Path, contract: &str, resolution: &str, rows: &mut [Value]) {
    // Parse the OPRA contract to extract underlying, expiry, and right
    let parsed = parse_opra_contract(contract);
    let opra = match parsed {
        Some(p) => p,
        None => {
            // Can't parse contract — mark all rows as model_error
            for row_val in rows.iter_mut() {
                if let Some(row) = row_val.as_object_mut() {
                    let t_conv = if resolution == "minute" {
                        "minute_precise"
                    } else {
                        "calendar_days_over_365"
                    };
                    let anchor = if resolution == "minute" {
                        "expiry_date_16_00_ET"
                    } else {
                        "expiry_date_eod"
                    };
                    let result =
                        null_greek_result(GreekStatus::ModelError, "stock_daily", t_conv, anchor);
                    merge_greek_result(row, &result);
                }
            }
            return;
        }
    };

    if resolution == "day" {
        enrich_ticker_rows_day(
            storage_root,
            &opra.underlying,
            &opra.expiry,
            opra.is_call,
            rows,
        );
    } else {
        enrich_ticker_rows_minute(
            storage_root,
            &opra.underlying,
            &opra.expiry,
            opra.is_call,
            opra.strike,
            rows,
        );
    }
}

/// Parsed OPRA contract fields.
struct OpraContract {
    underlying: String,
    expiry: NaiveDate,
    is_call: bool,
    strike: f64,
}

/// Parse an OPRA contract string like "O:NVDA250117C00136000" into its components.
fn parse_opra_contract(contract: &str) -> Option<OpraContract> {
    let stripped = contract.strip_prefix("O:")?;
    // Find the date portion — it's 6 digits after the ticker letters
    let alpha_end = stripped.find(|c: char| c.is_ascii_digit())?;
    let underlying = stripped[..alpha_end].to_string();
    let remainder = &stripped[alpha_end..];
    if remainder.len() < 15 {
        return None; // Need 6 date digits + C/P + 8 strike digits
    }
    let date_str = &remainder[..6];
    let right_char = remainder.as_bytes().get(6)?;
    let is_call = match *right_char {
        b'C' => true,
        b'P' => false,
        _ => return None,
    };
    let expiry = NaiveDate::parse_from_str(date_str, "%y%m%d").ok()?;
    let strike_str = &remainder[7..15];
    let strike_millis: u64 = strike_str.parse().ok()?;
    let strike = strike_millis as f64 / 1000.0;
    Some(OpraContract {
        underlying,
        expiry,
        is_call,
        strike,
    })
}

/// Enrich ticker query rows at day resolution.
fn enrich_ticker_rows_day(
    storage_root: &Path,
    underlying: &str,
    expiry_date: &NaiveDate,
    is_call: bool,
    rows: &mut [Value],
) {
    // Per-request caches for spot and rates by date
    let mut spot_cache: HashMap<String, Option<f64>> = HashMap::new();
    let mut rates_cache: HashMap<String, Option<RatesCurve>> = HashMap::new();

    for row_val in rows.iter_mut() {
        let row = match row_val.as_object_mut() {
            Some(r) => r,
            None => continue,
        };

        // Extract trade_date from the row (may come as "trade_date" field from partition)
        // For day resolution, we use window_start to infer the date, or if trade_date is present
        // Since we're querying over date ranges, we need the observation date.
        // The chain query uses a single date param, but ticker_query spans a range.
        // We need to extract the date from each row somehow.
        // The day-resolution default projection doesn't include trade_date, but we can derive from window_start.
        let obs_date_str = extract_trade_date_from_row(row);
        let obs_date_str = match obs_date_str {
            Some(d) => d,
            None => {
                let result = null_greek_result(
                    GreekStatus::ModelError,
                    "stock_daily",
                    "calendar_days_over_365",
                    "expiry_date_eod",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        let obs_date = match NaiveDate::parse_from_str(&obs_date_str, "%Y-%m-%d").ok() {
            Some(d) => d,
            None => {
                let result = null_greek_result(
                    GreekStatus::ModelError,
                    "stock_daily",
                    "calendar_days_over_365",
                    "expiry_date_eod",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        let spot_val = *spot_cache
            .entry(obs_date_str.clone())
            .or_insert_with(|| fetch_spot_daily(storage_root, underlying, &obs_date_str));

        let spot = match spot_val {
            Some(s) => s,
            None => {
                let result = null_greek_result(
                    GreekStatus::MissingSpot,
                    "stock_daily",
                    "calendar_days_over_365",
                    "expiry_date_eod",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        let curve = rates_cache.entry(obs_date_str.clone()).or_insert_with(|| {
            fetch_rates_row(storage_root, &obs_date_str)
                .and_then(|r| RatesCurve::from_json_row(&r).ok())
        });

        let curve_ref = match curve.as_ref() {
            Some(c) => c,
            None => {
                let result = null_greek_result(
                    GreekStatus::MissingRate,
                    "stock_daily",
                    "calendar_days_over_365",
                    "expiry_date_eod",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        let days_to_expiry = (*expiry_date - obs_date).num_days();
        let t_years = if days_to_expiry <= 0 {
            1.0 / (365.0 * 24.0 * 60.0)
        } else {
            days_to_expiry as f64 / 365.0
        };

        enrich_row_with_greeks(
            row,
            spot,
            curve_ref,
            t_years,
            is_call,
            "stock_daily",
            "calendar_days_over_365",
            "expiry_date_eod",
        );
    }
}

/// Enrich ticker query rows at minute resolution.
fn enrich_ticker_rows_minute(
    storage_root: &Path,
    underlying: &str,
    expiry_date: &NaiveDate,
    is_call: bool,
    strike: f64,
    rows: &mut [Value],
) {
    // Per-request caches
    let mut spot_cache: HashMap<String, Option<f64>> = HashMap::new();
    let mut rates_cache: HashMap<String, Option<RatesCurve>> = HashMap::new();

    // Expiry anchor: 16:00 ET = 21:00 UTC (EST) or 20:00 UTC (EDT)
    let utc_hour = if is_us_dst(expiry_date) { 20 } else { 21 };
    let expiry_dt = expiry_date
        .and_hms_opt(utc_hour, 0, 0)
        .and_then(|dt| dt.and_utc().timestamp_nanos_opt());

    let expiry_ns = match expiry_dt {
        Some(ns) => ns,
        None => {
            for row_val in rows.iter_mut() {
                if let Some(row) = row_val.as_object_mut() {
                    let result = null_greek_result(
                        GreekStatus::ModelError,
                        "stock_daily",
                        "minute_precise",
                        "expiry_date_16_00_ET",
                    );
                    merge_greek_result(row, &result);
                }
            }
            return;
        }
    };

    for row_val in rows.iter_mut() {
        let row = match row_val.as_object_mut() {
            Some(r) => r,
            None => continue,
        };

        // Get window_start as nanoseconds
        let window_start_ns = match row.get("window_start").and_then(Value::as_i64) {
            Some(ns) => ns,
            None => {
                let result = null_greek_result(
                    GreekStatus::ModelError,
                    "stock_daily",
                    "minute_precise",
                    "expiry_date_16_00_ET",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        // T in years = (expiry_ns - window_start_ns) / (365.25 * 24 * 60 * 60 * 1e9)
        let ns_diff = expiry_ns - window_start_ns;
        let t_years = if ns_diff <= 0 {
            1.0 / (365.0 * 24.0 * 60.0) // floor at ~1 minute
        } else {
            ns_diff as f64 / (365.0 * 24.0 * 3600.0 * 1_000_000_000.0)
        };

        // Extract trade date from window_start for spot/rates lookup
        let trade_date_str = ns_to_date_string(window_start_ns);
        let trade_date_str = match trade_date_str {
            Some(d) => d,
            None => {
                let result = null_greek_result(
                    GreekStatus::ModelError,
                    "stock_daily",
                    "minute_precise",
                    "expiry_date_16_00_ET",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        // For minute resolution, spot fallback: stock daily close
        let spot_val = *spot_cache
            .entry(trade_date_str.clone())
            .or_insert_with(|| fetch_spot_daily(storage_root, underlying, &trade_date_str));

        let spot = match spot_val {
            Some(s) => s,
            None => {
                let result = null_greek_result(
                    GreekStatus::MissingSpot,
                    "stock_daily",
                    "minute_precise",
                    "expiry_date_16_00_ET",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        let curve = rates_cache
            .entry(trade_date_str.clone())
            .or_insert_with(|| {
                fetch_rates_row(storage_root, &trade_date_str)
                    .and_then(|r| RatesCurve::from_json_row(&r).ok())
            });

        let curve_ref = match curve.as_ref() {
            Some(c) => c,
            None => {
                let result = null_greek_result(
                    GreekStatus::MissingRate,
                    "stock_daily",
                    "minute_precise",
                    "expiry_date_16_00_ET",
                );
                merge_greek_result(row, &result);
                continue;
            }
        };

        // Inject strike from OPRA contract (minute parquet doesn't have strike column)
        row.insert("strike".to_string(), json!(strike));

        enrich_row_with_greeks(
            row,
            spot,
            curve_ref,
            t_years,
            is_call,
            "stock_daily",
            "minute_precise",
            "expiry_date_16_00_ET",
        );
    }
}

/// Extract trade date string from a row. Tries "trade_date" field first, then derives from window_start.
fn extract_trade_date_from_row(row: &Map<String, Value>) -> Option<String> {
    // Try trade_date field directly
    if let Some(td) = row.get("trade_date").and_then(Value::as_str) {
        return Some(td.to_string());
    }
    // Try expiry field (not ideal but as a fallback...)
    // Better: derive from window_start
    if let Some(ns) = row.get("window_start").and_then(Value::as_i64) {
        return ns_to_date_string(ns);
    }
    None
}

/// Check if a date falls within US Eastern Daylight Time.
/// US DST: second Sunday of March 02:00 to first Sunday of November 02:00.
fn is_us_dst(date: &NaiveDate) -> bool {
    let year = date.year();
    let month = date.month();

    // Quick reject: Jan, Feb, Dec are always EST
    if !(3..=11).contains(&month) {
        return false;
    }
    // Quick accept: Apr-Oct are always EDT
    if (4..=10).contains(&month) {
        return true;
    }

    if month == 3 {
        // Second Sunday of March: find day of first Sunday, add 7
        let march_1 = NaiveDate::from_ymd_opt(year, 3, 1);
        if let Some(m1) = march_1 {
            let dow = m1.weekday().num_days_from_sunday(); // 0=Sun
            let first_sunday = if dow == 0 { 1 } else { 8 - dow };
            let second_sunday = first_sunday + 7;
            return date.day() >= second_sunday;
        }
        false
    } else {
        // month == 11: first Sunday of November
        let nov_1 = NaiveDate::from_ymd_opt(year, 11, 1);
        if let Some(n1) = nov_1 {
            let dow = n1.weekday().num_days_from_sunday();
            let first_sunday = if dow == 0 { 1 } else { 8 - dow };
            return date.day() < first_sunday;
        }
        false
    }
}

/// Convert nanoseconds since epoch to a YYYY-MM-DD date string.
fn ns_to_date_string(ns: i64) -> Option<String> {
    let secs = ns / 1_000_000_000;
    let dt = chrono::DateTime::from_timestamp(secs, 0)?;
    Some(dt.format("%Y-%m-%d").to_string())
}

/// Fetch the spot (close) price for a given ticker on a given date from stock_daily.
fn fetch_spot_daily(storage_root: &Path, ticker: &str, date: &str) -> Option<f64> {
    let dataset_dir = storage_root.join("stock_daily");
    let partition_dir = dataset_dir.join(format!("trade_date={date}"));
    if !has_any_parquet_file(&partition_dir) {
        return None;
    }
    let path_pattern = partition_dir
        .join("*.parquet")
        .to_string_lossy()
        .to_string();
    let sql = format!(
        "SELECT close FROM read_parquet('{path}') WHERE ticker = {ticker} LIMIT 1",
        path = sql_escape_literal(&path_pattern),
        ticker = sql_quote(ticker),
    );
    let rows = run_sql_json(&sql).ok()?;
    rows.first()?.get("close")?.as_f64()
}

/// Fetch the full rates row for a given date from rates.parquet.
fn fetch_rates_row(storage_root: &Path, date: &str) -> Option<Value> {
    let rates_path = storage_root.join("rates").join("rates.parquet");
    if !rates_path.exists() {
        return None;
    }
    let sql = format!(
        "SELECT * FROM read_parquet('{path}') WHERE date = DATE '{date}' LIMIT 1",
        path = sql_escape_literal(&rates_path.to_string_lossy()),
        date = sql_escape_literal(date),
    );
    let rows = run_sql_json(&sql).ok()?;
    rows.into_iter().next()
}

/// Convert an IvStatus to our API GreekStatus.
fn iv_status_to_greek_status(status: &IvStatus) -> GreekStatus {
    match status {
        IvStatus::Ok => GreekStatus::Ok,
        IvStatus::BelowIntrinsic => GreekStatus::BelowIntrinsic,
        IvStatus::NoBracket => GreekStatus::NoBracket,
        IvStatus::NonFiniteInput => GreekStatus::NonFiniteInput,
        IvStatus::NearExpiryApprox => GreekStatus::NearExpiryApprox,
    }
}

/// Build a GreekResult with null fields and the given status.
fn null_greek_result(
    status: GreekStatus,
    spot_source: &'static str,
    t_convention: &'static str,
    expiry_anchor: &'static str,
) -> GreekResult {
    GreekResult {
        iv: None,
        delta: None,
        gamma: None,
        theta: None,
        vega: None,
        rho: None,
        greek_status: status,
        greek_meta: GreekMeta {
            model: "bsm_european",
            style_assumption: "European",
            dividend_assumption: "q0",
            theta_unit: "per_day",
            vega_unit: "per_1pct_vol",
            rho_unit: "per_1pct_rate",
            spot_source,
            rate_source: "rates_parquet",
            t_convention,
            expiry_anchor,
        },
    }
}

/// Enrich a single option row with Greeks fields.
/// Returns the row with Greek fields appended.
#[allow(clippy::too_many_arguments)]
fn enrich_row_with_greeks(
    row: &mut Map<String, Value>,
    spot: f64,
    curve: &RatesCurve,
    t_years: f64,
    is_call: bool,
    spot_source: &'static str,
    t_convention: &'static str,
    expiry_anchor: &'static str,
) {
    let close = match row.get("close").and_then(Value::as_f64) {
        Some(c) if c.is_finite() && c > 0.0 => c,
        _ => {
            let result = null_greek_result(
                GreekStatus::NonFiniteInput,
                spot_source,
                t_convention,
                expiry_anchor,
            );
            merge_greek_result(row, &result);
            return;
        }
    };

    let strike = match row.get("strike").and_then(Value::as_f64) {
        Some(k) if k.is_finite() && k > 0.0 => k,
        _ => {
            let result = null_greek_result(
                GreekStatus::NonFiniteInput,
                spot_source,
                t_convention,
                expiry_anchor,
            );
            merge_greek_result(row, &result);
            return;
        }
    };

    let r = match curve.interpolate(t_years) {
        Ok(rate) => rate,
        Err(_) => {
            let result = null_greek_result(
                GreekStatus::MissingRate,
                spot_source,
                t_convention,
                expiry_anchor,
            );
            merge_greek_result(row, &result);
            return;
        }
    };

    let q = 0.0; // V1: no dividend
    let (iv_result, greeks_opt) = compute_greeks(close, spot, strike, t_years, r, q, is_call);

    let greek_status = iv_status_to_greek_status(&iv_result.status);
    let meta = GreekMeta {
        model: "bsm_european",
        style_assumption: "European",
        dividend_assumption: "q0",
        theta_unit: "per_day",
        vega_unit: "per_1pct_vol",
        rho_unit: "per_1pct_rate",
        spot_source,
        rate_source: "rates_parquet",
        t_convention,
        expiry_anchor,
    };

    let result = match greeks_opt {
        Some(g) => GreekResult {
            iv: iv_result.iv,
            delta: Some(g.delta),
            gamma: Some(g.gamma),
            theta: Some(g.theta),
            vega: Some(g.vega),
            rho: Some(g.rho),
            greek_status,
            greek_meta: meta,
        },
        None => GreekResult {
            iv: None,
            delta: None,
            gamma: None,
            theta: None,
            vega: None,
            rho: None,
            greek_status,
            greek_meta: meta,
        },
    };

    merge_greek_result(row, &result);
}

/// Merge a GreekResult into a row's JSON map.
fn merge_greek_result(row: &mut Map<String, Value>, result: &GreekResult) {
    row.insert(
        "iv".to_string(),
        match result.iv {
            Some(v) => json!(v),
            None => Value::Null,
        },
    );
    row.insert(
        "delta".to_string(),
        match result.delta {
            Some(v) => json!(v),
            None => Value::Null,
        },
    );
    row.insert(
        "gamma".to_string(),
        match result.gamma {
            Some(v) => json!(v),
            None => Value::Null,
        },
    );
    row.insert(
        "theta".to_string(),
        match result.theta {
            Some(v) => json!(v),
            None => Value::Null,
        },
    );
    row.insert(
        "vega".to_string(),
        match result.vega {
            Some(v) => json!(v),
            None => Value::Null,
        },
    );
    row.insert(
        "rho".to_string(),
        match result.rho {
            Some(v) => json!(v),
            None => Value::Null,
        },
    );
    row.insert("greek_status".to_string(), json!(result.greek_status));
    row.insert("greek_meta".to_string(), json!(result.greek_meta));
}

/// Determine if a row represents a call based on the "type" or "right" field.
fn row_is_call(row: &Map<String, Value>) -> Option<bool> {
    let right_val = row
        .get("type")
        .or_else(|| row.get("right"))
        .and_then(Value::as_str)?;
    match right_val {
        "C" => Some(true),
        "P" => Some(false),
        _ => None,
    }
}

fn run_sql_json(sql: &str) -> Result<Vec<Value>, ServiceError> {
    with_thread_local_connection(|conn| {
        let mut stmt = conn.prepare(sql)?;
        let mut rows = stmt.query([])?;
        let columns = match rows.as_ref() {
            Some(statement) => statement.column_names(),
            None => Vec::new(),
        };

        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            let mut object = Map::new();
            for (idx, col) in columns.iter().enumerate() {
                let value = row.get_ref(idx)?;
                object.insert(col.clone(), value_ref_to_json(value));
            }
            out.push(Value::Object(object));
        }

        Ok(out)
    })
}

async fn run_sql_json_async(sql: String) -> Result<Vec<Value>, ServiceError> {
    let task = tokio::task::spawn_blocking(move || run_sql_json(&sql));
    task.await
        .map_err(|error| ServiceError::Join(error.to_string()))?
}

thread_local! {
    static THREAD_LOCAL_DUCKDB_CONN: RefCell<Option<Connection>> = const { RefCell::new(None) };
}

fn with_thread_local_connection<T>(
    f: impl FnOnce(&Connection) -> Result<T, ServiceError>,
) -> Result<T, ServiceError> {
    THREAD_LOCAL_DUCKDB_CONN.with(|cell| {
        if cell.borrow().is_none() {
            *cell.borrow_mut() = Some(Connection::open_in_memory()?);
        }

        let borrow = cell.borrow();
        let conn = borrow.as_ref().ok_or_else(|| {
            ServiceError::Connection("failed to initialize connection".to_string())
        })?;
        f(conn)
    })
}

fn value_ref_to_json(value: ValueRef<'_>) -> Value {
    match value {
        ValueRef::Null => Value::Null,
        ValueRef::Boolean(v) => json!(v),
        ValueRef::TinyInt(v) => json!(v),
        ValueRef::SmallInt(v) => json!(v),
        ValueRef::Int(v) => json!(v),
        ValueRef::BigInt(v) => json!(v),
        ValueRef::HugeInt(v) => json!(v.to_string()),
        ValueRef::UTinyInt(v) => json!(v),
        ValueRef::USmallInt(v) => json!(v),
        ValueRef::UInt(v) => json!(v),
        ValueRef::UBigInt(v) => json!(v),
        ValueRef::Float(v) => json!(v),
        ValueRef::Double(v) => json!(v),
        ValueRef::Decimal(v) => json!(v.to_string()),
        ValueRef::Timestamp(unit, raw) => json!(timestamp_to_epoch_ns(unit, raw)),
        ValueRef::Text(bytes) => json!(String::from_utf8_lossy(bytes).to_string()),
        ValueRef::Blob(bytes) => json!(bytes),
        ValueRef::Date32(days) => match format_date32(days) {
            Some(value) => json!(value),
            None => json!(days),
        },
        ValueRef::Time64(_, raw) => json!(raw),
        ValueRef::Interval {
            months,
            days,
            nanos,
        } => json!({"months": months, "days": days, "nanos": nanos}),
        _ => json!(format!("{:?}", value.to_owned())),
    }
}

fn format_date32(days_since_epoch: i32) -> Option<String> {
    let epoch = NaiveDate::from_ymd_opt(1970, 1, 1)?;
    let days = Duration::days(i64::from(days_since_epoch));
    epoch
        .checked_add_signed(days)
        .map(|d| d.format("%Y-%m-%d").to_string())
}

fn timestamp_to_epoch_ns(unit: TimeUnit, raw: i64) -> i64 {
    match unit {
        TimeUnit::Second => raw.saturating_mul(1_000_000_000),
        TimeUnit::Millisecond => raw.saturating_mul(1_000_000),
        TimeUnit::Microsecond => raw.saturating_mul(1_000),
        TimeUnit::Nanosecond => raw,
    }
}

fn parse_stock_projection(fields_csv: Option<&str>) -> Result<String, &'static str> {
    let default = [
        "ticker",
        "window_start",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "transactions",
    ];
    parse_projection(fields_csv, &default, &default)
}

fn parse_stock_daily_projection(fields_csv: Option<&str>) -> Result<String, &'static str> {
    let allowlist = [
        "ticker",
        "trade_date",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "transactions",
    ];
    let default = [
        "ticker",
        "trade_date AS date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "transactions",
    ];

    if let Some(fields_csv) = fields_csv {
        let fields = parse_csv_list(fields_csv);
        if fields.is_empty() {
            return Ok(default.join(", "));
        }
        let refs: Vec<&str> = fields.iter().map(String::as_str).collect();
        if validate_fields(&refs, &allowlist).is_err() {
            return Err("fields contains unsupported column");
        }

        let mapped = refs
            .iter()
            .map(|field| {
                if *field == "date" {
                    "trade_date AS date".to_string()
                } else {
                    (*field).to_string()
                }
            })
            .collect::<Vec<String>>()
            .join(", ");
        return Ok(mapped);
    }

    Ok(default.join(", "))
}

fn parse_option_ticker_projection(
    fields_csv: Option<&str>,
    resolution: &str,
) -> Result<String, &'static str> {
    if resolution == "minute" {
        let default = [
            "ticker",
            "window_start",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "transactions",
        ];
        let allowlist = [
            "ticker",
            "contract",
            "window_start",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "transactions",
        ];

        if let Some(fields_csv) = fields_csv {
            let fields = parse_csv_list(fields_csv);
            if fields.is_empty() {
                return Ok(default.join(", "));
            }
            let refs: Vec<&str> = fields.iter().map(String::as_str).collect();
            if validate_fields(&refs, &allowlist).is_err() {
                return Err("fields contains unsupported column");
            }
            let mapped = refs
                .iter()
                .map(|field| {
                    if *field == "contract" {
                        "ticker AS contract".to_string()
                    } else {
                        (*field).to_string()
                    }
                })
                .collect::<Vec<String>>()
                .join(", ");
            return Ok(mapped);
        }

        Ok(default.join(", "))
    } else {
        let default = [
            "ticker",
            "underlying",
            "expiry",
            "strike",
            "\"right\" AS type",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "transactions",
            "window_start",
        ];
        let allowlist = [
            "ticker",
            "contract",
            "underlying",
            "expiry",
            "strike",
            "right",
            "type",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "transactions",
            "window_start",
        ];

        if let Some(fields_csv) = fields_csv {
            let fields = parse_csv_list(fields_csv);
            if fields.is_empty() {
                return Ok(default.join(", "));
            }
            let refs: Vec<&str> = fields.iter().map(String::as_str).collect();
            if validate_fields(&refs, &allowlist).is_err() {
                return Err("fields contains unsupported column");
            }
            let mapped = refs
                .iter()
                .map(|field| {
                    if *field == "type" {
                        "\"right\" AS type".to_string()
                    } else if *field == "contract" {
                        "ticker AS contract".to_string()
                    } else if *field == "right" {
                        "\"right\"".to_string()
                    } else {
                        (*field).to_string()
                    }
                })
                .collect::<Vec<String>>()
                .join(", ");
            return Ok(mapped);
        }

        Ok(default.join(", "))
    }
}

fn parse_option_chain_projection(fields_csv: Option<&str>) -> Result<String, &'static str> {
    let allowlist = [
        "ticker",
        "contract",
        "underlying",
        "expiry",
        "strike",
        "right",
        "type",
        "close",
        "volume",
    ];
    let default = [
        "ticker",
        "underlying",
        "expiry",
        "strike",
        "\"right\" AS type",
        "close",
        "volume",
    ];

    if let Some(fields_csv) = fields_csv {
        let fields = parse_csv_list(fields_csv);
        if fields.is_empty() {
            return Ok(default.join(", "));
        }
        let refs: Vec<&str> = fields.iter().map(String::as_str).collect();
        if validate_fields(&refs, &allowlist).is_err() {
            return Err("fields contains unsupported column");
        }

        let mapped = refs
            .iter()
            .map(|field| {
                if *field == "type" {
                    "\"right\" AS type".to_string()
                } else if *field == "contract" {
                    "ticker AS contract".to_string()
                } else if *field == "right" {
                    "\"right\"".to_string()
                } else {
                    (*field).to_string()
                }
            })
            .collect::<Vec<String>>()
            .join(", ");
        return Ok(mapped);
    }

    Ok(default.join(", "))
}

fn parse_projection(
    fields_csv: Option<&str>,
    default_fields: &[&str],
    allowlist: &[&str],
) -> Result<String, &'static str> {
    if let Some(fields_csv) = fields_csv {
        let fields = parse_csv_list(fields_csv);
        if fields.is_empty() {
            return Ok(default_fields.join(", "));
        }
        let refs: Vec<&str> = fields.iter().map(String::as_str).collect();
        if validate_fields(&refs, allowlist).is_err() {
            return Err("fields contains unsupported column");
        }
        return Ok(refs.join(", "));
    }

    Ok(default_fields.join(", "))
}

fn parse_datetime_ns(input: &str, end_of_second: bool) -> Result<i64, &'static str> {
    let dt = NaiveDateTime::parse_from_str(input, "%Y-%m-%dT%H:%M:%S")
        .map_err(|_| "failed to parse datetime")?;
    let dt = if end_of_second {
        dt.checked_add_signed(Duration::nanoseconds(999_999_999))
            .ok_or("datetime overflow")?
    } else {
        dt
    };

    dt.and_utc()
        .timestamp_nanos_opt()
        .ok_or("datetime overflow")
}

fn parse_date_or_datetime_ns(input: &str, end_of_day: bool) -> Result<i64, &'static str> {
    if let Ok(dt) = NaiveDateTime::parse_from_str(input, "%Y-%m-%dT%H:%M:%S") {
        let final_dt = if end_of_day {
            dt.checked_add_signed(Duration::nanoseconds(999_999_999))
                .ok_or("datetime overflow")?
        } else {
            dt
        };
        return final_dt
            .and_utc()
            .timestamp_nanos_opt()
            .ok_or("datetime overflow");
    }

    let date = NaiveDate::parse_from_str(input, "%Y-%m-%d").map_err(|_| "failed to parse date")?;
    let dt = if end_of_day {
        date.and_hms_nano_opt(23, 59, 59, 999_999_999)
            .ok_or("datetime overflow")?
    } else {
        date.and_hms_nano_opt(0, 0, 0, 0)
            .ok_or("datetime overflow")?
    };

    dt.and_utc()
        .timestamp_nanos_opt()
        .ok_or("datetime overflow")
}

fn extract_date_from_datetime(input: &str) -> Result<String, &'static str> {
    let dt = NaiveDateTime::parse_from_str(input, "%Y-%m-%dT%H:%M:%S")
        .map_err(|_| "failed to parse datetime")?;
    Ok(dt.date().format("%Y-%m-%d").to_string())
}

fn extract_date_from_date_or_datetime(input: &str) -> Result<String, &'static str> {
    if let Ok(date) = NaiveDate::parse_from_str(input, "%Y-%m-%d") {
        return Ok(date.format("%Y-%m-%d").to_string());
    }
    extract_date_from_datetime(input)
}

fn has_any_parquet_file(path: &Path) -> bool {
    if !path.exists() {
        return false;
    }

    if path.is_file() {
        return is_parquet_file(path);
    }

    let entries = match fs::read_dir(path) {
        Ok(entries) => entries,
        Err(_) => return false,
    };

    for entry in entries.flatten() {
        let entry_path = entry.path();
        if is_parquet_file(&entry_path) {
            return true;
        }
        if !entry_path.is_dir() {
            continue;
        }

        let partition_entries = match fs::read_dir(entry_path) {
            Ok(items) => items,
            Err(_) => continue,
        };
        for partition_entry in partition_entries.flatten() {
            if is_parquet_file(&partition_entry.path()) {
                return true;
            }
        }
    }

    false
}

fn is_parquet_file(path: &Path) -> bool {
    path.is_file()
        && path
            .extension()
            .and_then(|ext| ext.to_str())
            .map(|ext| ext.eq_ignore_ascii_case("parquet"))
            .unwrap_or(false)
}

fn sql_escape_literal(value: &str) -> String {
    value.replace('\'', "''")
}

fn sql_quote(value: &str) -> String {
    format!("'{}'", sql_escape_literal(value))
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

fn internal_error(error: ServiceError) -> axum::response::Response {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({
            "code": "internal_error",
            "message": error.to_string(),
        })),
    )
        .into_response()
}
