mod stats;

use std::path::PathBuf;
use std::process::Command;
use std::time::Instant;

use anyhow::{anyhow, Context, Result};
use chrono::{NaiveDate, NaiveDateTime};
use duckdb::Connection;
use stats::summarize;

#[derive(Debug, Clone)]
struct BenchOptions {
    raw_root: PathBuf,
    storage_root: PathBuf,
    ticker: String,
    start: String,
    end: String,
    iterations: usize,
    warmup: usize,
}

#[derive(Debug, Clone, Copy)]
struct TimeRange {
    start_ns: i64,
    end_ns: i64,
    start_date: NaiveDate,
    end_date: NaiveDate,
}

#[derive(Debug, Clone, Copy)]
struct ModeSummary {
    rows_per_query: usize,
    latency: stats::LatencySummary,
    peak_rss_mb: Option<f64>,
}

fn main() -> Result<()> {
    let options = parse_args(std::env::args().collect::<Vec<String>>().as_slice())?;
    let time_range = parse_time_range(&options.start, &options.end)?;

    println!(
        "benchmark config: ticker={} start={} end={} iterations={} warmup={}",
        options.ticker, options.start, options.end, options.iterations, options.warmup
    );

    for _ in 0..options.warmup {
        let _ = run_csv_gzip_baseline(&options, &time_range)?;
        let _ = run_duckdb_parquet(&options, &time_range)?;
    }

    let baseline = run_mode(&options, &time_range, run_csv_gzip_baseline)?;
    let duckdb = run_mode(&options, &time_range, run_duckdb_parquet)?;

    println!("\nmode=csv_gzip_baseline");
    print_mode_summary(&baseline);
    println!("\nmode=duckdb_parquet");
    print_mode_summary(&duckdb);

    Ok(())
}

fn run_mode(
    options: &BenchOptions,
    range: &TimeRange,
    mode_fn: fn(&BenchOptions, &TimeRange) -> Result<usize>,
) -> Result<ModeSummary> {
    let mut latencies_ms = Vec::with_capacity(options.iterations);
    let mut rows_per_query = 0;
    let start = Instant::now();
    let mut peak_rss_mb = current_rss_mb();

    for _ in 0..options.iterations {
        let iter_start = Instant::now();
        rows_per_query = mode_fn(options, range)?;
        latencies_ms.push(iter_start.elapsed().as_secs_f64() * 1000.0);

        if let Some(current_rss) = current_rss_mb() {
            peak_rss_mb = Some(match peak_rss_mb {
                Some(existing) => existing.max(current_rss),
                None => current_rss,
            });
        }
    }

    let total_elapsed_ms = start.elapsed().as_secs_f64() * 1000.0;
    Ok(ModeSummary {
        rows_per_query,
        latency: summarize(&latencies_ms, total_elapsed_ms),
        peak_rss_mb,
    })
}

fn run_csv_gzip_baseline(options: &BenchOptions, range: &TimeRange) -> Result<usize> {
    let conn = Connection::open_in_memory()?;
    let pattern = options
        .raw_root
        .join("stock")
        .join("minute")
        .join("*.csv.gz")
        .to_string_lossy()
        .to_string();

    let sql = format!(
        "SELECT COUNT(*) FROM read_csv_auto('{path}', header=true) \
         WHERE ticker = '{ticker}' AND window_start >= {start_ns} AND window_start <= {end_ns}",
        path = sql_escape_literal(&pattern),
        ticker = sql_escape_literal(&options.ticker),
        start_ns = range.start_ns,
        end_ns = range.end_ns,
    );

    let rows: i64 = conn.query_row(&sql, [], |row| row.get(0))?;
    usize::try_from(rows).map_err(|_| anyhow!("baseline row count overflow"))
}

fn run_duckdb_parquet(options: &BenchOptions, range: &TimeRange) -> Result<usize> {
    let conn = Connection::open_in_memory()?;
    let pattern = options
        .storage_root
        .join("stock_minute")
        .join("trade_date=*")
        .join("*.parquet")
        .to_string_lossy()
        .to_string();

    let sql = format!(
        "SELECT COUNT(*) FROM read_parquet('{path}') \
         WHERE trade_date >= DATE '{start_date}' AND trade_date <= DATE '{end_date}' \
         AND ticker = '{ticker}' AND window_start >= {start_ns} AND window_start <= {end_ns}",
        path = sql_escape_literal(&pattern),
        start_date = range.start_date,
        end_date = range.end_date,
        ticker = sql_escape_literal(&options.ticker),
        start_ns = range.start_ns,
        end_ns = range.end_ns,
    );

    let rows: i64 = conn.query_row(&sql, [], |row| row.get(0))?;
    usize::try_from(rows).map_err(|_| anyhow!("duckdb row count overflow"))
}

fn print_mode_summary(summary: &ModeSummary) {
    println!("rows_per_query={}", summary.rows_per_query);
    println!("p50_ms={:.3}", summary.latency.p50_ms);
    println!("p95_ms={:.3}", summary.latency.p95_ms);
    println!("p99_ms={:.3}", summary.latency.p99_ms);
    println!("throughput_qps={:.3}", summary.latency.throughput_qps);
    match summary.peak_rss_mb {
        Some(value) => println!("peak_rss_mb={value:.3}"),
        None => println!("peak_rss_mb=NA"),
    }
}

fn parse_time_range(start: &str, end: &str) -> Result<TimeRange> {
    let start_dt = NaiveDateTime::parse_from_str(start, "%Y-%m-%dT%H:%M:%S")
        .with_context(|| format!("invalid start datetime: {start}"))?;
    let end_dt = NaiveDateTime::parse_from_str(end, "%Y-%m-%dT%H:%M:%S")
        .with_context(|| format!("invalid end datetime: {end}"))?;

    let start_ns = start_dt
        .and_utc()
        .timestamp_nanos_opt()
        .ok_or_else(|| anyhow!("start datetime overflow"))?;
    let end_ns = end_dt
        .and_utc()
        .timestamp_nanos_opt()
        .ok_or_else(|| anyhow!("end datetime overflow"))?;

    Ok(TimeRange {
        start_ns,
        end_ns,
        start_date: start_dt.date(),
        end_date: end_dt.date(),
    })
}

fn parse_args(args: &[String]) -> Result<BenchOptions> {
    let mut options = BenchOptions {
        raw_root: PathBuf::from("./raw_sample"),
        storage_root: PathBuf::from("./storage"),
        ticker: "AAPL".to_string(),
        start: "2025-12-31T09:30:00".to_string(),
        end: "2025-12-31T16:00:00".to_string(),
        iterations: 30,
        warmup: 5,
    };

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--raw-root" => {
                options.raw_root = PathBuf::from(next_arg(args, i)?);
                i += 2;
            }
            "--storage-root" => {
                options.storage_root = PathBuf::from(next_arg(args, i)?);
                i += 2;
            }
            "--ticker" => {
                options.ticker = next_arg(args, i)?.to_string();
                i += 2;
            }
            "--start" => {
                options.start = next_arg(args, i)?.to_string();
                i += 2;
            }
            "--end" => {
                options.end = next_arg(args, i)?.to_string();
                i += 2;
            }
            "--iterations" => {
                options.iterations = next_arg(args, i)?
                    .parse::<usize>()
                    .with_context(|| "invalid --iterations value")?;
                i += 2;
            }
            "--warmup" => {
                options.warmup = next_arg(args, i)?
                    .parse::<usize>()
                    .with_context(|| "invalid --warmup value")?;
                i += 2;
            }
            "--help" | "-h" => {
                print_usage();
                std::process::exit(0);
            }
            flag => return Err(anyhow!("unknown flag: {flag}")),
        }
    }

    Ok(options)
}

fn next_arg(args: &[String], index: usize) -> Result<&str> {
    args.get(index + 1)
        .map(String::as_str)
        .ok_or_else(|| anyhow!("missing value for {}", args[index]))
}

fn print_usage() {
    println!(
        "usage: upq-bench [--raw-root ./raw_sample] [--storage-root ./storage] [--ticker AAPL] \
         [--start YYYY-MM-DDTHH:MM:SS] [--end YYYY-MM-DDTHH:MM:SS] [--iterations 30] [--warmup 5]"
    );
}

fn sql_escape_literal(input: &str) -> String {
    input.replace('\'', "''")
}

fn current_rss_mb() -> Option<f64> {
    let pid = std::process::id().to_string();
    let output = Command::new("ps")
        .args(["-o", "rss=", "-p", &pid])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }

    let value = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let rss_kb = value.parse::<f64>().ok()?;
    Some(rss_kb / 1024.0)
}

#[cfg(test)]
mod tests {
    use super::parse_time_range;

    #[test]
    fn parse_time_range_extracts_ns_and_dates() -> Result<(), Box<dyn std::error::Error>> {
        let range = parse_time_range("2025-12-31T09:30:00", "2025-12-31T16:00:00")?;
        assert_eq!(range.start_date.to_string(), "2025-12-31");
        assert_eq!(range.end_date.to_string(), "2025-12-31");
        assert!(range.end_ns > range.start_ns);
        Ok(())
    }
}
