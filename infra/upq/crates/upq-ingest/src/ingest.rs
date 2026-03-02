use std::ffi::OsStr;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use std::time::Instant;

use duckdb::Connection;
use regex::Regex;
use thiserror::Error;

use crate::manifest::{ManifestError, ManifestStore};

#[derive(Debug, Clone)]
pub struct IngestOptions {
    pub raw_root: PathBuf,
    pub storage_root: PathBuf,
    pub manifest_path: PathBuf,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct IngestReport {
    pub processed_files: usize,
    pub skipped_files: usize,
}

#[derive(Debug, Error)]
pub enum IngestError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("manifest error: {0}")]
    Manifest(#[from] ManifestError),
    #[error("duckdb error: {0}")]
    Duckdb(#[from] duckdb::Error),
    #[error("invalid source file name: {0}")]
    InvalidFileName(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DatasetKind {
    StockDaily,
    StockMinute,
    OptionDay,
    OptionMinute,
    Rates,
    Dividends,
}

#[derive(Debug, Clone)]
struct SourceFile {
    dataset: DatasetKind,
    path: PathBuf,
}

static TRADE_DATE_FILE_REGEX: LazyLock<Option<Regex>> =
    LazyLock::new(|| Regex::new(r"(\d{4}-\d{2}-\d{2})\.csv(\.gz)?$").ok());

pub fn run_ingest(options: &IngestOptions) -> Result<IngestReport, IngestError> {
    fs::create_dir_all(&options.storage_root)?;

    let manifest = ManifestStore::open(&options.manifest_path)?;
    let conn = Connection::open_in_memory()?;
    let files = discover_input_files(&options.raw_root)?;
    let total_files = files.len();

    let mut report = IngestReport {
        processed_files: 0,
        skipped_files: 0,
    };

    println!("Ingesting {} files...", total_files);
    let start_time = Instant::now();

    for (idx, source) in files.into_iter().enumerate() {
        let current = idx + 1;
        let file_name = source
            .path
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| format!("file_{}", current));

        if !manifest.should_process(&source.path)? {
            report.skipped_files += 1;
            println!(
                "[{}/{}] SKIP {} (already processed)",
                current, total_files, file_name
            );
            continue;
        }

        print!("[{}/{}] Processing {}... ", current, total_files, file_name);
        Write::flush(&mut std::io::stdout()).ok();

        match ingest_file(&conn, &options.storage_root, &source) {
            Ok(rows) => {
                manifest.mark_done(&source.path, rows)?;
                report.processed_files += 1;

                let elapsed = start_time.elapsed().as_secs_f64();
                let files_done = current;
                let avg_time = elapsed / files_done as f64;
                let remaining_files = total_files - current;
                let eta_secs = avg_time * remaining_files as f64;

                println!(
                    "OK ({} rows) [{:.1}%] ETA: {:.0}s",
                    rows,
                    (files_done as f64 / total_files as f64) * 100.0,
                    eta_secs
                );
            }
            Err(error) => {
                let message = error.to_string();
                manifest.mark_error(&source.path, &message)?;
                println!("ERROR: {}", message);
                return Err(error);
            }
        }
    }

    let total_elapsed = start_time.elapsed();
    println!(
        "\nIngest complete: {}/{} files processed, {} skipped in {:?}",
        report.processed_files, total_files, report.skipped_files, total_elapsed
    );

    Ok(report)
}

fn discover_input_files(raw_root: &Path) -> Result<Vec<SourceFile>, IngestError> {
    let mut out = Vec::new();

    out.extend(list_files(
        raw_root.join("stock/day"),
        DatasetKind::StockDaily,
        "csv.gz",
    )?);
    out.extend(list_files(
        raw_root.join("stock/minute"),
        DatasetKind::StockMinute,
        "csv.gz",
    )?);
    out.extend(list_files(
        raw_root.join("options/day"),
        DatasetKind::OptionDay,
        "csv.gz",
    )?);
    out.extend(list_files(
        raw_root.join("options/minute"),
        DatasetKind::OptionMinute,
        "csv.gz",
    )?);

    let rates = raw_root.join("assets/treasury_yields.csv");
    if rates.is_file() {
        out.push(SourceFile {
            dataset: DatasetKind::Rates,
            path: rates,
        });
    }

    let dividends_sqlite = raw_root.join("dividends/massive_dividends.sqlite");
    if dividends_sqlite.is_file() {
        out.push(SourceFile {
            dataset: DatasetKind::Dividends,
            path: dividends_sqlite,
        });
    }

    out.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(out)
}

fn list_files(
    dir: PathBuf,
    dataset: DatasetKind,
    suffix: &str,
) -> Result<Vec<SourceFile>, IngestError> {
    if !dir.is_dir() {
        return Ok(Vec::new());
    }

    let mut out = Vec::new();
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let name = match path.file_name().and_then(OsStr::to_str) {
            Some(value) => value,
            None => continue,
        };
        if name.ends_with(suffix) {
            out.push(SourceFile { dataset, path });
        }
    }

    Ok(out)
}

fn ingest_file(
    conn: &Connection,
    storage_root: &Path,
    source: &SourceFile,
) -> Result<i64, IngestError> {
    match source.dataset {
        DatasetKind::StockDaily => ingest_stock(conn, storage_root, source, "stock_daily"),
        DatasetKind::StockMinute => ingest_stock(conn, storage_root, source, "stock_minute"),
        DatasetKind::OptionDay => ingest_option(conn, storage_root, source, "option_day"),
        DatasetKind::OptionMinute => ingest_option(conn, storage_root, source, "option_minute"),
        DatasetKind::Rates => ingest_rates(conn, storage_root, source),
        DatasetKind::Dividends => ingest_dividends(conn, storage_root, source),
    }
}

fn ingest_stock(
    conn: &Connection,
    storage_root: &Path,
    source: &SourceFile,
    table_dir: &str,
) -> Result<i64, IngestError> {
    let source_literal = sql_escape_literal(source.path.to_string_lossy().as_ref());
    let trade_date = extract_trade_date(&source.path)?;
    let output = output_file_path(storage_root, table_dir, Some(&trade_date), &source.path)?;
    let output_literal = sql_escape_literal(output.to_string_lossy().as_ref());

    let select_sql = format!(
        "SELECT \
            ticker, \
            CAST(window_start AS BIGINT) AS window_start, \
            CAST(open AS DOUBLE) AS open, \
            CAST(high AS DOUBLE) AS high, \
            CAST(low AS DOUBLE) AS low, \
            CAST(close AS DOUBLE) AS close, \
            CAST(volume AS BIGINT) AS volume, \
            CAST(transactions AS BIGINT) AS transactions, \
            DATE '{trade_date}' AS trade_date \
         FROM read_csv_auto('{source}', header=true) \
         ORDER BY ticker, window_start",
        trade_date = trade_date,
        source = source_literal,
    );

    write_parquet(conn, &select_sql, &output_literal, &output)?;
    row_count(conn, &output)
}

fn ingest_option(
    conn: &Connection,
    storage_root: &Path,
    source: &SourceFile,
    table_dir: &str,
) -> Result<i64, IngestError> {
    let source_literal = sql_escape_literal(source.path.to_string_lossy().as_ref());
    let trade_date = extract_trade_date(&source.path)?;
    let output = output_file_path(storage_root, table_dir, Some(&trade_date), &source.path)?;
    let output_literal = sql_escape_literal(output.to_string_lossy().as_ref());
    let opra_regex = "^O:([A-Z]+)(\\d{6})([CP])(\\d{8})$";

    let select_sql = format!(
        "SELECT \
            ticker AS ticker, \
            ticker AS contract, \
            NULLIF(regexp_extract(ticker, '{regex}', 1), '') AS underlying, \
            CAST(strptime(NULLIF(regexp_extract(ticker, '{regex}', 2), ''), '%y%m%d') AS DATE) AS expiry, \
            CAST(NULLIF(regexp_extract(ticker, '{regex}', 4), '') AS BIGINT) / 1000.0 AS strike, \
            NULLIF(regexp_extract(ticker, '{regex}', 3), '') AS \"right\", \
            CAST(window_start AS BIGINT) AS window_start, \
            CAST(open AS DOUBLE) AS open, \
            CAST(high AS DOUBLE) AS high, \
            CAST(low AS DOUBLE) AS low, \
            CAST(close AS DOUBLE) AS close, \
            CAST(volume AS BIGINT) AS volume, \
            CAST(transactions AS BIGINT) AS transactions, \
            DATE '{trade_date}' AS trade_date \
         FROM read_csv_auto('{source}', header=true) \
         ORDER BY contract, window_start",
        regex = opra_regex,
        trade_date = trade_date,
        source = source_literal,
    );

    write_parquet(conn, &select_sql, &output_literal, &output)?;
    row_count(conn, &output)
}

fn ingest_rates(
    conn: &Connection,
    storage_root: &Path,
    source: &SourceFile,
) -> Result<i64, IngestError> {
    let source_literal = sql_escape_literal(source.path.to_string_lossy().as_ref());
    let output_dir = storage_root.join("rates");
    fs::create_dir_all(&output_dir)?;
    let output = output_dir.join("rates.parquet");
    let output_literal = sql_escape_literal(output.to_string_lossy().as_ref());

    let select_sql = format!(
        "SELECT \
            CAST(date AS DATE) AS date, \
            CAST(yield_1_month AS DOUBLE) AS yield_1_month, \
            CAST(yield_3_month AS DOUBLE) AS yield_3_month, \
            CAST(yield_1_year AS DOUBLE) AS yield_1_year, \
            CAST(yield_2_year AS DOUBLE) AS yield_2_year, \
            CAST(yield_5_year AS DOUBLE) AS yield_5_year, \
            CAST(yield_10_year AS DOUBLE) AS yield_10_year, \
            CAST(yield_30_year AS DOUBLE) AS yield_30_year \
         FROM read_csv_auto('{source}', header=true) \
         ORDER BY date",
        source = source_literal,
    );

    write_parquet(conn, &select_sql, &output_literal, &output)?;
    row_count(conn, &output)
}

fn ingest_dividends(
    conn: &Connection,
    storage_root: &Path,
    source: &SourceFile,
) -> Result<i64, IngestError> {
    let source_literal = sql_escape_literal(source.path.to_string_lossy().as_ref());
    let output_dir = storage_root.join("dividends");
    fs::create_dir_all(&output_dir)?;
    let output = output_dir.join("dividends.parquet");
    let output_literal = sql_escape_literal(output.to_string_lossy().as_ref());

    conn.execute_batch("INSTALL sqlite_scanner; LOAD sqlite_scanner;")?;

    let select_sql = format!(
        "SELECT \
            ticker, \
            CAST(ex_dividend_date AS DATE) AS ex_dividend_date, \
            CAST(split_adjusted_cash_amount AS DOUBLE) AS amount \
         FROM sqlite_scan('{source}', 'dividends') \
         WHERE currency = 'USD' \
           AND ticker IS NOT NULL \
           AND ex_dividend_date IS NOT NULL \
           AND split_adjusted_cash_amount > 0 \
         ORDER BY ticker, ex_dividend_date",
        source = source_literal,
    );

    write_parquet(conn, &select_sql, &output_literal, &output)?;
    row_count(conn, &output)
}

fn output_file_path(
    storage_root: &Path,
    table_dir: &str,
    trade_date: Option<&str>,
    source_path: &Path,
) -> Result<PathBuf, IngestError> {
    let mut out_dir = storage_root.join(table_dir);
    if let Some(date) = trade_date {
        out_dir = out_dir.join(format!("trade_date={date}"));
    }
    fs::create_dir_all(&out_dir)?;

    let name = file_stem_no_csv_suffix(source_path)?;
    Ok(out_dir.join(format!("{name}.parquet")))
}

fn write_parquet(
    conn: &Connection,
    select_sql: &str,
    output_literal: &str,
    output_path: &Path,
) -> Result<(), IngestError> {
    if output_path.is_file() {
        fs::remove_file(output_path)?;
    }

    let sql = format!(
        "COPY ({select_sql}) TO '{output}' (FORMAT PARQUET, COMPRESSION ZSTD)",
        select_sql = select_sql,
        output = output_literal,
    );
    conn.execute_batch(&sql)?;
    Ok(())
}

fn row_count(conn: &Connection, parquet_path: &Path) -> Result<i64, IngestError> {
    let source_literal = sql_escape_literal(parquet_path.to_string_lossy().as_ref());
    let sql = format!(
        "SELECT COUNT(*) FROM read_parquet('{source}')",
        source = source_literal,
    );
    let count: i64 = conn.query_row(&sql, [], |row| row.get(0))?;
    Ok(count)
}

fn extract_trade_date(path: &Path) -> Result<String, IngestError> {
    let name = path
        .file_name()
        .and_then(OsStr::to_str)
        .ok_or_else(|| IngestError::InvalidFileName(path.to_string_lossy().to_string()))?;
    let captures = TRADE_DATE_FILE_REGEX
        .as_ref()
        .ok_or_else(|| IngestError::InvalidFileName(name.to_string()))?
        .captures(name)
        .ok_or_else(|| IngestError::InvalidFileName(name.to_string()))?;
    let date = captures
        .get(1)
        .map(|value| value.as_str().to_string())
        .ok_or_else(|| IngestError::InvalidFileName(name.to_string()))?;
    Ok(date)
}

fn file_stem_no_csv_suffix(path: &Path) -> Result<String, IngestError> {
    let name = path
        .file_name()
        .and_then(OsStr::to_str)
        .ok_or_else(|| IngestError::InvalidFileName(path.to_string_lossy().to_string()))?;

    let trimmed = name
        .strip_suffix(".csv.gz")
        .or_else(|| name.strip_suffix(".csv"))
        .ok_or_else(|| IngestError::InvalidFileName(name.to_string()))?;

    Ok(trimmed.to_string())
}

fn sql_escape_literal(input: &str) -> String {
    input.replace('\'', "''")
}
