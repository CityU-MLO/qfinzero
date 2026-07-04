> English: [../../../../../infra/upq/docs/schemas.md](../../../../../infra/upq/docs/schemas.md)

# UPQ Schemas

## 数据源探查摘要
使用只读命令并抽样行，从服务器上检查数据。

### Stocks（`/home/qlib/data/stock`）
文件：
- `us_stocks_sip_day_aggs_v1_*.csv.gz`
- `us_stocks_sip_minute_aggs_v1_*.csv.gz`

列：
- `ticker` (string)
- `volume` (int64)
- `open` (float64)
- `close` (float64)
- `high` (float64)
- `low` (float64)
- `window_start` (int64, ns epoch)
- `transactions` (int64)

### Options（`/home/qlib/data/us_options_opra`）
文件：
- `day_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`
- `minute_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`

列（与 stocks 相同）：
- `ticker` (string, OPRA contract)
- `volume` (int64)
- `open` (float64)
- `close` (float64)
- `high` (float64)
- `low` (float64)
- `window_start` (int64, ns epoch)
- `transactions` (int64)

从 OPRA `ticker` 派生的字段：
- `underlying` (string)
- `expiry` (date)
- `right` (string, `C`/`P`)
- `strike` (float64)
- `contract` (string, normalized ticker)

### Rates（`/home/qlib/data/assets/treasury_yields.csv`）
列：
- `date` (date)
- `yield_1_year` (float64)
- `yield_5_year` (float64)
- `yield_10_year` (float64)
- `yield_2_year` (float64)
- `yield_30_year` (float64)
- `yield_3_month` (float64)
- `yield_1_month` (float64)

### Dividends（`qlib:/home/qlib/news/massive_dividends.sqlite`）
源格式：包含单个 `dividends` 表的 SQLite 数据库。

摄取时使用的列（筛选条件为 `currency = 'USD'`）：
- `ticker` (text)
- `ex_dividend_date` (text, YYYY-MM-DD)
- `split_adjusted_cash_amount` (real)

## 逻辑表

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

排序键：`(ticker, window_start)`
分区：`trade_date`

### `stock_daily`
- 与 `stock_minute` 相同的列
- 日线数据仍以 `window_start` 和 `trade_date` 为键

排序键：`(ticker, window_start)`
分区：`trade_date`

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

排序键：`(underlying, expiry, strike, right, window_start)`
分区：`trade_date`

### `option_minute`
- 与 `option_day` 相同的列

排序键：`(contract, window_start)`
分区：`trade_date`

### `rates`
- `date DATE`
- 各期限列为 double 类型

存储为 `storage/rates/` 中的单个 Parquet 文件。

### `dividends`
- `ticker TEXT`
- `ex_dividend_date DATE`
- `amount DOUBLE`（拆股调整后的现金分红，仅限 USD）

存储为 `storage/dividends/` 中的单个 Parquet 文件。
由 `DividendCalendar` 用于希腊字母计算中的离散分红调整（`S_adj = S - Σ PV(D_i)`）。
