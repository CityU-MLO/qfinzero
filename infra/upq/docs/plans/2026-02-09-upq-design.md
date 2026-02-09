# UPQ Design (Rust + DuckDB + Parquet)

## Goal
Build a Rust price query service compatible with existing `price_query_service` APIs while moving to disk-based Parquet querying to reduce memory pressure.

## Confirmed Data Paths (Server)
- Stocks: `/home/qlib/data/stock`
- Options: `/home/qlib/data/us_options_opra`
- Rates: `/home/qlib/data/assets/treasury_yields.csv`

## Decisions
- Stack: Rust + Axum + DuckDB + Parquet
- Query model: Parquet-first (no long-lived imported DuckDB tables)
- API compatibility: path/params/default behavior compatible with Python service
- Partitioning: `trade_date=YYYY-MM-DD`
- Local dev data: latest 14 trading days sample
- Rates missing-date policy: strict raw dates only (no forward fill)

## Storage Layout
- `storage/stock_minute/trade_date=YYYY-MM-DD/*.parquet`
- `storage/stock_daily/trade_date=YYYY-MM-DD/*.parquet`
- `storage/option_day/trade_date=YYYY-MM-DD/*.parquet`
- `storage/option_minute/trade_date=YYYY-MM-DD/*.parquet`
- `storage/rates/rates.parquet`
- `storage/_meta/manifest.sqlite`

## Access Path Strategy
Use:
- partition pruning (`trade_date` filters)
- projection pushdown (`fields` whitelist)
- sorted writes (zone-map friendly)

No per-ticker partitioning to avoid directory explosion.

## API Scope
- `GET /stock`
- `GET /stock/daily`
- `GET /option/ticker_query`
- `GET /option/chain_query`
- `GET /rates/query`

## Non-Goals (Phase 1)
- Migrating `quotes_v1`
- Replacing source HDF5 assets
- New API versioning or response format changes

## Rollout
1. Local spec + tests + implementation on 14-day sample
2. Contract/latency validation against Python baseline
3. Server-side full-data validation
4. Deployment and smoke checks
