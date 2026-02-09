use std::fs;
use std::io::Write;

use duckdb::Connection;
use flate2::write::GzEncoder;
use flate2::Compression;
use tempfile::TempDir;
use upq_ingest::ingest::{run_ingest, IngestOptions};

#[test]
fn run_ingest_writes_parquet_and_respects_manifest() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let raw_root = tmp.path().join("raw_sample");
    let storage_root = tmp.path().join("storage");
    let manifest_path = tmp.path().join("state").join("manifest.sqlite");

    fs::create_dir_all(raw_root.join("stock/minute"))?;
    fs::create_dir_all(raw_root.join("options/day"))?;
    fs::create_dir_all(raw_root.join("assets"))?;

    write_gzip_csv(
        &raw_root
            .join("stock/minute")
            .join("us_stocks_sip_minute_aggs_v1_2025_12_2025-12-31.csv.gz"),
        "ticker,volume,open,close,high,low,window_start,transactions\nAAPL,100,10.0,10.5,10.6,9.9,1735637400000000000,5\n",
    )?;
    write_gzip_csv(
        &raw_root.join("options/day").join("2025-12-31.csv.gz"),
        "ticker,volume,open,close,high,low,window_start,transactions\nO:NVDA250117C00136000,200,3.0,3.2,3.5,2.9,1735603200000000000,10\n",
    )?;
    fs::write(
        raw_root.join("assets/treasury_yields.csv"),
        "date,yield_1_month,yield_3_month,yield_1_year,yield_2_year,yield_5_year,yield_10_year,yield_30_year\n2025-12-31,4.0,4.1,4.2,4.3,4.4,4.5,4.6\n",
    )?;

    let report = run_ingest(&IngestOptions {
        raw_root: raw_root.clone(),
        storage_root: storage_root.clone(),
        manifest_path: manifest_path.clone(),
    })?;
    assert_eq!(report.processed_files, 3);
    assert_eq!(report.skipped_files, 0);

    let conn = Connection::open_in_memory()?;

    let stock_sql = format!(
        "SELECT ticker, CAST(trade_date AS VARCHAR), close \
         FROM read_parquet('{}')",
        storage_root
            .join("stock_minute/trade_date=2025-12-31/*.parquet")
            .to_string_lossy()
            .replace('\'', "''")
    );
    let (ticker, trade_date, close): (String, String, f64) =
        conn.query_row(&stock_sql, [], |row| {
            Ok((row.get(0)?, row.get(1)?, row.get(2)?))
        })?;
    assert_eq!(ticker, "AAPL");
    assert_eq!(trade_date, "2025-12-31");
    assert_eq!(close, 10.5);

    let option_sql = format!(
        "SELECT contract, underlying, CAST(expiry AS VARCHAR), strike, \"right\" \
         FROM read_parquet('{}')",
        storage_root
            .join("option_day/trade_date=2025-12-31/*.parquet")
            .to_string_lossy()
            .replace('\'', "''")
    );
    let (contract, underlying, expiry, strike, right): (String, String, String, f64, String) = conn
        .query_row(&option_sql, [], |row| {
            Ok((
                row.get(0)?,
                row.get(1)?,
                row.get(2)?,
                row.get(3)?,
                row.get(4)?,
            ))
        })?;
    assert_eq!(contract, "O:NVDA250117C00136000");
    assert_eq!(underlying, "NVDA");
    assert_eq!(expiry, "2025-01-17");
    assert_eq!(strike, 136.0);
    assert_eq!(right, "C");

    let rates_sql = format!(
        "SELECT COUNT(*) FROM read_parquet('{}')",
        storage_root
            .join("rates/rates.parquet")
            .to_string_lossy()
            .replace('\'', "''")
    );
    let rates_count: i64 = conn.query_row(&rates_sql, [], |row| row.get(0))?;
    assert_eq!(rates_count, 1);

    let second = run_ingest(&IngestOptions {
        raw_root,
        storage_root,
        manifest_path,
    })?;
    assert_eq!(second.processed_files, 0);
    assert_eq!(second.skipped_files, 3);

    Ok(())
}

fn write_gzip_csv(path: &std::path::Path, content: &str) -> Result<(), Box<dyn std::error::Error>> {
    let file = fs::File::create(path)?;
    let mut encoder = GzEncoder::new(file, Compression::default());
    encoder.write_all(content.as_bytes())?;
    encoder.finish()?;
    Ok(())
}
