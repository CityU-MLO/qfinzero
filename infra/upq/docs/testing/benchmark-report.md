# Benchmark Report

Date: 2026-02-10

## Scope
- Dataset: local 14-trading-day sample synced from `qlib`
- Query shape: stock minute query for `AAPL` in `2025-12-31T09:30:00` to `2025-12-31T16:00:00`
- Matched rows: 172 rows per query
- Command:
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
- `p50_ms`: 9252.212
- `p95_ms`: 9846.713
- `p99_ms`: 9911.838
- `throughput_qps`: 0.108
- `peak_rss_mb`: `NA` (sandbox blocks `ps` memory sampling)

### `duckdb_parquet`
- `rows_per_query`: 172
- `p50_ms`: 30.203
- `p95_ms`: 41.590
- `p99_ms`: 43.247
- `throughput_qps`: 30.334
- `peak_rss_mb`: `NA` (sandbox blocks `ps` memory sampling)

## Summary
- On this sample workload, DuckDB+Parquet reduced median latency from ~9.25s to ~30ms.
- Throughput improved from ~0.108 qps to ~30.334 qps.
- This benchmark is intentionally narrow (single ticker/time window) and should be extended with option/rates workloads and multi-ticker scenarios.
