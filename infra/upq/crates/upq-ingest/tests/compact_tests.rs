use std::fs;

use duckdb::Connection;
use tempfile::TempDir;
use upq_ingest::compact::{run_compaction, CompactOptions};

#[test]
fn run_compaction_merges_partition_parquet_files() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let partition_dir = tmp.path().join("option_day").join("trade_date=2025-01-10");
    fs::create_dir_all(&partition_dir)?;

    let parquet_1 = partition_dir.join("part-a.parquet");
    let parquet_2 = partition_dir.join("part-b.parquet");
    let conn = Connection::open_in_memory()?;
    let sql = format!(
        "COPY (SELECT * FROM (VALUES \
            ('O:NVDA250117C00136000', 'NVDA', DATE '2025-01-17', 136.0::DOUBLE, 'C', 1736496000000000000::BIGINT, 3.2::DOUBLE),\
            ('O:NVDA250117P00130000', 'NVDA', DATE '2025-01-17', 130.0::DOUBLE, 'P', 1736496000000000000::BIGINT, 1.8::DOUBLE)\
         ) AS t(ticker, underlying, expiry, strike, \"right\", window_start, close) \
         LIMIT 1) TO '{}' (FORMAT PARQUET); \
         COPY (SELECT * FROM (VALUES \
            ('O:NVDA250117C00136000', 'NVDA', DATE '2025-01-17', 136.0::DOUBLE, 'C', 1736496000000000000::BIGINT, 3.2::DOUBLE),\
            ('O:NVDA250117P00130000', 'NVDA', DATE '2025-01-17', 130.0::DOUBLE, 'P', 1736496000000000000::BIGINT, 1.8::DOUBLE)\
         ) AS t(ticker, underlying, expiry, strike, \"right\", window_start, close) \
         OFFSET 1) TO '{}' (FORMAT PARQUET)",
        parquet_1.to_string_lossy().replace('\'', "''"),
        parquet_2.to_string_lossy().replace('\'', "''"),
    );
    conn.execute_batch(&sql)?;

    let report = run_compaction(&CompactOptions {
        storage_root: tmp.path().to_path_buf(),
    })?;
    assert_eq!(report.partitions_compacted, 1);

    let parquet_files: Vec<_> = fs::read_dir(&partition_dir)?
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| path.extension().and_then(|s| s.to_str()) == Some("parquet"))
        .collect();
    assert_eq!(parquet_files.len(), 1);

    let verify_conn = Connection::open_in_memory()?;
    let count_sql = format!(
        "SELECT COUNT(*) FROM read_parquet('{}')",
        partition_dir
            .join("*.parquet")
            .to_string_lossy()
            .replace('\'', "''")
    );
    let count: i64 = verify_conn.query_row(&count_sql, [], |row| row.get(0))?;
    assert_eq!(count, 2);

    Ok(())
}
