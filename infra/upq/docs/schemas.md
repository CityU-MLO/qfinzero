# UPQ Schemas

## Source Discovery Summary
Data inspected from server with read-only commands and sampled rows.

### Stocks (`/home/qlib/data/stock`)
Files:
- `us_stocks_sip_day_aggs_v1_*.csv.gz`
- `us_stocks_sip_minute_aggs_v1_*.csv.gz`

Columns:
- `ticker` (string)
- `volume` (int64)
- `open` (float64)
- `close` (float64)
- `high` (float64)
- `low` (float64)
- `window_start` (int64, ns epoch)
- `transactions` (int64)

### Options (`/home/qlib/data/us_options_opra`)
Files:
- `day_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`
- `minute_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`

Columns (same as stocks):
- `ticker` (string, OPRA contract)
- `volume` (int64)
- `open` (float64)
- `close` (float64)
- `high` (float64)
- `low` (float64)
- `window_start` (int64, ns epoch)
- `transactions` (int64)

Derived fields from OPRA `ticker`:
- `underlying` (string)
- `expiry` (date)
- `right` (string, `C`/`P`)
- `strike` (float64)
- `contract` (string, normalized ticker)

### Rates (`/home/qlib/data/assets/treasury_yields.csv`)
Columns:
- `date` (date)
- `yield_1_year` (float64)
- `yield_5_year` (float64)
- `yield_10_year` (float64)
- `yield_2_year` (float64)
- `yield_30_year` (float64)
- `yield_3_month` (float64)
- `yield_1_month` (float64)

## Logical Tables

### `stock_minute`
- `ticker TEXT`
- `window_start BIGINT`
- `trade_date DATE` (derived)
- `open DOUBLE`
- `high DOUBLE`
- `low DOUBLE`
- `close DOUBLE`
- `volume BIGINT`
- `transactions BIGINT`

Sort key: `(ticker, window_start)`
Partition: `trade_date`

### `stock_daily`
- Same columns as `stock_minute`
- Daily data still keyed by `window_start` and `trade_date`

Sort key: `(ticker, window_start)`
Partition: `trade_date`

### `option_day`
- `contract TEXT`
- `underlying TEXT`
- `expiry DATE`
- `strike DOUBLE`
- `right TEXT`
- `window_start BIGINT`
- `trade_date DATE`
- `open DOUBLE`
- `high DOUBLE`
- `low DOUBLE`
- `close DOUBLE`
- `volume BIGINT`
- `transactions BIGINT`

Sort key: `(underlying, expiry, strike, right, window_start)`
Partition: `trade_date`

### `option_minute`
- Same columns as `option_day`

Sort key: `(contract, window_start)`
Partition: `trade_date`

### `rates`
- `date DATE`
- tenor columns as doubles

Stored in a single Parquet file in `storage/rates/`.
