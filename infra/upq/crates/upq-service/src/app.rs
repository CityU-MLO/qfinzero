use std::collections::BTreeSet;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::get;
use axum::{Json, Router};
use chrono::{Duration, NaiveDate, NaiveDateTime};
use duckdb::types::{TimeUnit, ValueRef};
use duckdb::Connection;
use serde::Deserialize;
use serde_json::{json, Map, Value};
use thiserror::Error;
use tokio::task::JoinSet;
use upq_core::rates::map_tenor_aliases;
use upq_core::rates::split_by_month;
use upq_core::sql_builder::build_tenor_projection;
use upq_core::validation::{
    parse_csv_list, validate_date, validate_date_or_datetime, validate_datetime, validate_fields,
    validate_resolution,
};

const MAX_LIMIT: usize = 100_000;

#[derive(Clone, Debug)]
pub struct AppState {
    storage_root: PathBuf,
}

#[derive(Debug, Error)]
enum ServiceError {
    #[error("duckdb error: {0}")]
    Duckdb(#[from] duckdb::Error),
    #[error("join error: {0}")]
    Join(String),
}

pub fn build_router() -> Router {
    let storage_root = env::var("STORAGE_ROOT").unwrap_or_else(|_| "./storage".to_string());
    build_router_with_storage_root(storage_root)
}

pub fn build_router_with_storage_root(storage_root: impl Into<PathBuf>) -> Router {
    let state = AppState {
        storage_root: storage_root.into(),
    };

    Router::new()
        .route("/stock", get(stock))
        .route("/stock/daily", get(stock_daily))
        .route("/option/ticker_query", get(option_ticker_query))
        .route("/option/chain_query", get(option_chain_query))
        .route("/rates/query", get(rates_query))
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

    let file_path = state.storage_root.join("rates").join("rates.parquet");
    if !file_path.exists() {
        return (StatusCode::OK, Json(json!([]))).into_response();
    }

    let sql = format!(
        "SELECT {projection} FROM read_parquet('{path}') WHERE date >= DATE '{start}' AND date <= DATE '{end}' ORDER BY date",
        path = sql_escape_literal(&file_path.to_string_lossy()),
        start = "{start}",
        end = "{end}",
    );
    let chunks = match split_by_month(&params.start, &params.end) {
        Ok(value) => value,
        Err(_) => return invalid_argument("start/end must be date: YYYY-MM-DD"),
    };

    let mut join_set = JoinSet::new();
    for (chunk_start, chunk_end) in chunks {
        let sql = sql
            .replace("{start}", &sql_escape_literal(&chunk_start))
            .replace("{end}", &sql_escape_literal(&chunk_end));
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

    let mut seen_dates = BTreeSet::new();
    rows.retain(|row| {
        let key = row
            .get("date")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        if seen_dates.contains(&key) {
            return false;
        }
        seen_dates.insert(key);
        true
    });

    rows.sort_by(|left, right| {
        let left_date = left
            .get("date")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let right_date = right
            .get("date")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        left_date.cmp(&right_date)
    });

    (StatusCode::OK, Json(Value::Array(rows))).into_response()
}

fn run_sql_json(sql: &str) -> Result<Vec<Value>, ServiceError> {
    let conn = Connection::open_in_memory()?;
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
}

async fn run_sql_json_async(sql: String) -> Result<Vec<Value>, ServiceError> {
    let task = tokio::task::spawn_blocking(move || run_sql_json(&sql));
    task.await
        .map_err(|error| ServiceError::Join(error.to_string()))?
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
        return path
            .extension()
            .and_then(|ext| ext.to_str())
            .map(|ext| ext.eq_ignore_ascii_case("parquet"))
            .unwrap_or(false);
    }

    let entries = match fs::read_dir(path) {
        Ok(entries) => entries,
        Err(_) => return false,
    };

    for entry in entries.flatten() {
        if has_any_parquet_file(&entry.path()) {
            return true;
        }
    }

    false
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
