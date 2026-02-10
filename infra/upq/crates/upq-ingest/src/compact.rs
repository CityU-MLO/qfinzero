use std::fs;
use std::path::{Path, PathBuf};

use duckdb::Connection;
use thiserror::Error;

#[derive(Debug, Clone)]
pub struct CompactOptions {
    pub storage_root: PathBuf,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CompactReport {
    pub partitions_scanned: usize,
    pub partitions_compacted: usize,
}

#[derive(Debug, Error)]
pub enum CompactError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("duckdb error: {0}")]
    Duckdb(#[from] duckdb::Error),
}

pub fn run_compaction(options: &CompactOptions) -> Result<CompactReport, CompactError> {
    let mut report = CompactReport {
        partitions_scanned: 0,
        partitions_compacted: 0,
    };
    let conn = Connection::open_in_memory()?;

    for table in ["stock_daily", "stock_minute", "option_day", "option_minute"] {
        let table_dir = options.storage_root.join(table);
        if !table_dir.is_dir() {
            continue;
        }

        for entry in fs::read_dir(&table_dir)? {
            let entry = entry?;
            let partition = entry.path();
            if !partition.is_dir() {
                continue;
            }

            let Some(name) = partition.file_name().and_then(|s| s.to_str()) else {
                continue;
            };
            if !name.starts_with("trade_date=") {
                continue;
            }

            report.partitions_scanned += 1;
            let parquet_files = list_parquet_files(&partition)?;
            if parquet_files.len() <= 1 {
                continue;
            }

            compact_partition(&conn, &partition, &parquet_files)?;
            report.partitions_compacted += 1;
        }
    }

    Ok(report)
}

fn list_parquet_files(partition: &Path) -> Result<Vec<PathBuf>, CompactError> {
    let mut out = Vec::new();
    for entry in fs::read_dir(partition)? {
        let entry = entry?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        if path.extension().and_then(|s| s.to_str()) == Some("parquet") {
            out.push(path);
        }
    }
    out.sort();
    Ok(out)
}

fn compact_partition(
    conn: &Connection,
    partition: &Path,
    parquet_files: &[PathBuf],
) -> Result<(), CompactError> {
    let input_pattern = partition.join("*.parquet");
    let compacted_tmp = partition.join("__compact_new.parquet");
    let final_output = partition.join("part-0000.parquet");

    let sql = format!(
        "COPY (SELECT * FROM read_parquet('{input}')) TO '{output}' (FORMAT PARQUET, COMPRESSION ZSTD)",
        input = sql_escape_literal(input_pattern.to_string_lossy().as_ref()),
        output = sql_escape_literal(compacted_tmp.to_string_lossy().as_ref()),
    );
    conn.execute_batch(&sql)?;

    if final_output.is_file() {
        fs::remove_file(&final_output)?;
    }
    fs::rename(&compacted_tmp, &final_output)?;

    for file in parquet_files {
        if file == &final_output {
            continue;
        }
        if file.is_file() {
            fs::remove_file(file)?;
        }
    }
    Ok(())
}

fn sql_escape_literal(input: &str) -> String {
    input.replace('\'', "''")
}
