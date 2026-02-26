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
use tower_http::trace::{self, TraceLayer};
use tracing::Level;
use chrono::{Duration, NaiveDate, NaiveDateTime};
use duckdb::types::{TimeUnit, ValueRef};
use duckdb::Connection;
use serde::Deserialize;
use serde_json::{json, Map, Value};
use thiserror::Error;
use tokio::sync::RwLock;
use tokio::task::JoinSet;
use upq_core::rates::map_tenor_aliases;
use upq_core::rates::split_by_month;
use upq_core::sql_builder::build_tenor_projection;
use upq_core::validation::{
    parse_csv_list, validate_date, validate_date_or_datetime, validate_datetime, validate_fields,
    validate_resolution,
};

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

    let projection = match parse_option_ticker_projection(params.fields.as_deref(), &resolution) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
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
        "SELECT {projection} FROM read_parquet('{path}') \
         WHERE trade_date >= DATE '{start_date}' AND trade_date <= DATE '{end_date}' \
         AND ticker = {contract} AND window_start >= {start_ns} AND window_start <= {end_ns} \
         ORDER BY window_start",
        path = sql_escape_literal(&path_pattern),
        start_date = sql_escape_literal(&start_date),
        end_date = sql_escape_literal(&end_date),
        contract = sql_quote(&params.contract),
    );

    match run_sql_json_async(sql).await {
        Ok(rows) => (StatusCode::OK, Json(Value::Array(rows))).into_response(),
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
    (StatusCode::OK, Json(json!({ "status": "ok", "version": "0.1.0" }))).into_response()
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
                            source_info
                                .insert("latest_timestamp".to_string(), latest_ts.clone());
                        }
                    }
                }
            }
        }

        source_info.insert(
            "unique_key_label".to_string(),
            json!(unique_key_label),
        );
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
                rates_info.insert(
                    "unique_key_label".to_string(),
                    json!("tenors"),
                );
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

    let projection = match parse_option_chain_projection(params.fields.as_deref()) {
        Ok(value) => value,
        Err(message) => return invalid_argument(message),
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

    let mut filters = vec![format!("underlying = {}", sql_quote(&params.underlying))];
    if let Some(expiry_min) = params.expiry_min.as_deref() {
        filters.push(format!(
            "expiry >= DATE '{}'",
            sql_escape_literal(expiry_min)
        ));
    }
    if let Some(expiry_max) = params.expiry_max.as_deref() {
        filters.push(format!(
            "expiry <= DATE '{}'",
            sql_escape_literal(expiry_max)
        ));
    }
    if let Some(strike_min) = params.strike_min {
        filters.push(format!("strike >= {strike_min}"));
    }
    if let Some(strike_max) = params.strike_max {
        filters.push(format!("strike <= {strike_max}"));
    }
    if let Some(option_type) = params.r#type.as_deref() {
        filters.push(format!(
            "\"right\" = '{}'",
            sql_escape_literal(&option_type.trim().to_ascii_uppercase())
        ));
    }

    let sql = format!(
        "SELECT {projection} FROM read_parquet('{path}') WHERE {filters} ORDER BY expiry, strike",
        path = sql_escape_literal(&path_pattern),
        filters = filters.join(" AND "),
    );

    match run_sql_json_async(sql).await {
        Ok(rows) => (StatusCode::OK, Json(Value::Array(rows))).into_response(),
        Err(error) => internal_error(error),
    }
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
