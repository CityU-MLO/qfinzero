# Benchmark Report

Date: 2026-02-10

## Scope
- Dataset: local 14-trading-day sample synced from `qlib`
- Query shape: stock minute query for `AAPL` in `2025-12-31T09:30:00` to `2025-12-31T16:00:00`
- Matched rows: 172 rows per query
- Command:
- Environment note: this run used elevated execution so `ps`-based RSS sampling is available.
  Command:
```bash
cargo run -p upq-bench -- \
  --raw-root ./raw_sample \
  --storage-root ./storage \
  --ticker AAPL \
  --start 2025-12-31T09:30:00 \
  --end 2025-12-31T16:00:00 \
  --iterations 20 \
  --warmup 3
```

## Results

### `csv_gzip_baseline`
- `rows_per_query`: 172
- `p50_ms`: 9006.607
- `p95_ms`: 9670.436
- `p99_ms`: 9726.376
- `throughput_qps`: 0.111
- `peak_rss_mb`: 506.906

### `duckdb_parquet`
- `rows_per_query`: 172
- `p50_ms`: 27.446
- `p95_ms`: 37.548
- `p99_ms`: 39.061
- `throughput_qps`: 30.931
- `peak_rss_mb`: 410.328

## Summary
- On this sample workload, DuckDB+Parquet reduced median latency from ~9.25s to ~30ms.
- Throughput improved from ~0.108 qps to ~30.334 qps.
- This benchmark is intentionally narrow (single ticker/time window) and should be extended with option/rates workloads and multi-ticker scenarios.
