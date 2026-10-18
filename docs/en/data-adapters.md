# Data adapters

> 中文: [docs/cn/data-adapters.md](../cn/data-adapters.md)

UPQ serves prices from one on-disk format. Every vendor is an **adapter** in the
Python pipeline (`qfinzero/pipeline/sources/`) that converts raw files into that
format. The UPQ engine (`infra/upq`, Rust) never knows which vendor a row came
from, so adding a vendor does not touch the engine.

```
raw vendor files ──▶ adapter (sources/<vendor>.py) ──▶ UPQ storage ──▶ UPQ engine ──▶ MCP / clients
 read in place        normalize + convert              parquet          unchanged
```

## The storage contract

Everything an adapter must produce lives under `STORAGE_ROOT`
(default `$QFZ_DATA_ROOT/upq`).

| Store | Partition | Columns (in this order) |
|-------|-----------|-------------------------|
| `stock_daily` | `trade_date=YYYY-MM-DD/` | `ticker, trade_date, open, high, low, close, volume, transactions` |
| `stock_minute` | `trade_date=YYYY-MM-DD/` | `ticker, window_start, open, high, low, close, volume, transactions, trade_date` |
| `option_day` | `trade_date=YYYY-MM-DD/` | `ticker, contract, underlying, expiry, strike, right, window_start, open, high, low, close, volume, transactions, trade_date` |
| `option_minute` | `trade_date=YYYY-MM-DD/` | same as `option_day` |
| `stock_quote_minute` | `trade_date=YYYY-MM-DD/` | `ticker, window_start, bid_price, ask_price, bid_size, ask_size, trade_date` |
| `option_quote_minute` | `trade_date=YYYY-MM-DD/` | `ticker, contract, underlying, expiry, strike, right, window_start, bid_price, ask_price, bid_size, ask_size, trade_date` |
| `future_daily` | `trade_date=YYYY-MM-DD/` | `ticker, root, trade_date, open, high, low, close, settle, volume, transactions` |
| `future_minute` | `trade_date=YYYY-MM-DD/` | `ticker, root, window_start, open, high, low, close, volume, transactions, trade_date` |
| `future_quote_minute` | `trade_date=YYYY-MM-DD/` | `ticker, root, window_start, bid_price, ask_price, bid_size, ask_size, trade_date` |

The types are fixed in [`qfinzero/pipeline/schema.py`](../../qfinzero/pipeline/schema.py):
`VARCHAR` for text, `DATE` for dates, `DOUBLE` for prices and strikes, and
`BIGINT` for volume, transactions and timestamps. Files are ZSTD parquet.

Conventions every adapter follows:

- `window_start` is the bar start in nanoseconds since the Unix epoch, UTC.
  On `option_day` it is 00:00 US/Eastern of the trade date.
- `trade_date` is the US/Eastern calendar date for US markets. For futures it
  is the CME session: 18:00 ET the evening before to 17:00 ET.
- Prices are raw, as traded. Splits and dividends live in
  `corporate_actions/` and UPQ applies them on read.
- Option tickers use `O:{ROOT}{YYMMDD}{C|P}{strike×1000, 8 digits}`, for example
  `O:SPY250117C00500000`.
- Each vendor writes its own file into a partition: `part-0000.parquet` for
  massive, `part-cn-0000.parquet` for tushare and
  `part-databento-0000.parquet` for Databento.

The engine reads each store with a single `read_parquet('<store>/trade_date=*/*.parquet')`
glob. Two consequences follow:

1. Every part file must have the same column names, order and types. A test
   (`test_parts_match_upq_storage_schema_exactly`) holds the Databento adapter to this.
2. If two parts in one partition hold the same ticker, its bars appear twice.
   Adapters that overlap must agree on a precedence rule. The rule is described
   below.

## Adding a vendor

1. Add a reader in `qfinzero/pipeline/sources/<vendor>.py` that produces the
   SELECT for each store, with the columns and types above.
2. Add a `convert_<vendor>` method on `Converter` (`qfinzero/pipeline/convert.py`)
   that writes the partitions and records them in the manifest so re-runs are
   incremental.
3. Report the raw files in `registry.scan_raw` and the converted state in
   `registry.scan_storage` so `qfz-data status` and the update freshness can see them.
4. Register an update source in `qfinzero/update/sources.py`.
5. Add the raw directory, credentials and scan/acquire entries in
   `qfinzero/admin/` if the vendor has an API.

Nothing under `infra/upq` changes. A new **kind** of data does need engine work
(a store and endpoints); order books, for example, have none today.

## The Databento adapter

Code: [`qfinzero/pipeline/sources/databento.py`](../../qfinzero/pipeline/sources/databento.py)
and `Converter.convert_databento`. Install with `pip install -e ".[databento]"`.
Parquet exports also convert without the `databento` package.

### Which files are read

Every `*.dbn`, `*.dbn.zst` and Databento-exported `*.parquet` under
`RAW_DATABENTO_DIR` (default `/data/databento`) is identified from its own header
or columns, so any folder layout works. Folders that start with `_` or `.` are
skipped, for example Databento's `_tmp` batch scratch. Header reads are cached in
`$STORAGE_ROOT/_state/databento_index.json`. A first scan of about 6,600 files
takes about two minutes, and later scans take about one second.

### Schema mapping

| Databento schema | UPQ stores | How |
|------------------|------------|-----|
| `ohlcv-1m` | minute + daily | bars copied; daily aggregated from minutes |
| `ohlcv-1s` | minute + daily | re-aggregated to minutes |
| `ohlcv-1h`, `ohlcv-1d`, `ohlcv-eod` | daily | `ohlcv-1d` uses the UTC day Databento reports |
| `trades`, `tbbo`, `tcbbo` | minute + daily | every record is a trade |
| `mbp-1`, `mbp-10`, `cmbp-1`, `mbo` | minute + daily | only records with `action == 'T'` |
| `cmbp-1`, `cbbo-1s`, `cbbo-1m`, `bbo-1s`, `bbo-1m` | `option_quote_minute`, `stock_quote_minute`, `future_quote_minute` | last top of book in each minute (see below) |
| `mbp-1`, `mbp-10` of a futures venue | `future_quote_minute` | the exchange's own book is the BBO |
| definition, statistics, status, imbalance | none | reference data |

In MBO, a `T` record is the execution and an `F` record is the passive side of
the same execution, so counting both would double the volume. Hidden-order
executions also arrive as `T`.

### Asset classes and symbols

- `OPRA.*` datasets become `option_minute` and `option_day`. OSI symbols such as
  `SPY   250117C00500000` become `O:SPY250117C00500000`. Underlying, expiry,
  strike and right are parsed with the same regular expression as the massive
  adapter.
- US equity datasets (`XNAS.ITCH`, `EQUS.*`, `DBEQ.*`, `XNYS.PILLAR`, `ARCX.PILLAR`, …)
  become `stock_minute` and `stock_daily`. A space in a symbol becomes a dot
  (`BRK B` → `BRK.B`).
- Futures venues (`GLBX.MDP3` for CME Globex, `IFUS.*`, `IFEU.*`, `IFLL.*`,
  `NDEX.*`) become `future_minute`, `future_daily` and `future_quote_minute`.
  An outright keeps its symbol (`ZNZ6`); a front-month continuous symbol
  (`ZN.v.0`, `ZN.c.0`, `ZN.n.0`) becomes the root (`ZN`), and `ZN.v.1` stays as
  it is. Calendar spreads (`ZNZ6-ZNH7`) and user-defined spreads are dropped.
  `root` is the product (`ESZ26` → `ES`, `M2KU6` → `M2K`).
- Other datasets are skipped.
- Parquet exports carry no dataset, so a dataset name in the path is used when
  present (for example `…/XNAS.ITCH/…`). Otherwise OSI-shaped symbols are treated
  as options.
- Instrument ids are mapped to symbols from the file's symbology, date by date,
  because OPRA reuses ids.

### Time rules

- Minute bars are bucketed on `ts_event`.
- Trade dates are US/Eastern.
- Stock daily open, high, low and close come from 09:30–16:00 ET when the
  session traded. Volume and transactions cover the whole day. This matches the
  massive day aggregates. Option daily bars use every trade.
- Fixed-point prices are divided by 1e9, so `56650000000` becomes exactly `56.65`.
- Futures sessions run from 18:00 ET to 17:00 ET the next day, so a bar from
  18:00 ET on belongs to the next trade date. A daily bar covers the whole
  session; `settle` is its last trade (exchange settlement prices from the
  `statistics` schema are not converted yet). Databento cuts files on UTC days,
  so a lone file also holds the first two hours of the next session: those
  minutes are kept, but that session gets a daily bar only when its 12:00–17:00
  ET part is present for the product.

### Quotes

Quote schemas fill two extra stores with the same contract:
`stock_quote_minute(ticker, window_start, bid_price, ask_price, bid_size,
ask_size, trade_date)` and `option_quote_minute`, which also has the option
columns. A row is the book at the end of the minute that starts at
`window_start`. Sampled schemas (`cbbo-*`, `bbo-*`) stamp the end of their
interval, so the stamp is shifted back into its minute. Minutes without an
update are not written; readers carry the last row forward. When several
sources quote a name, the order is consolidated feeds, then `cmbp-1` (every
update), then 1-second samples, then 1-minute samples. `cmbp-1` files yield
both trade bars and quotes.

**Sampling interval.** Each quote store can keep one book per 1, 5, 15, 30 or
60 minutes instead of every minute: the last book of each bucket (buckets are
aligned on ET clock time, so 15 minutes gives 09:30, 09:45, …). A coarser
interval makes a full-market OPRA day much smaller; readers carry the last row
forward either way. Set it per asset class in *Data setup* (*BBO sampling*),
with `qfz-data convert --quote-interval N` (or `--stock-quote-interval`,
`--option-quote-interval`, `--future-quote-interval`), or with
`QFZ_STOCK_QUOTE_INTERVAL`, `QFZ_OPTION_QUOTE_INTERVAL` and
`QFZ_FUTURE_QUOTE_INTERVAL`. The choice is saved in the data configuration
(`quotes.<asset>_interval_min`) so scheduled updates keep it, and changing it
rebuilds the affected partitions.

### Overnight

`OCEA.MEMOIR` (Blue Ocean ATS) trades 20:00–04:00 ET. Its minute bars are
added to `stock_minute` even when another vendor already wrote the daytime
bars of that ticker. In the overnight window only an identical (ticker,
minute) is skipped. Overnight trades never enter daily bars. Partitions stay
on ET calendar dates; PMB assigns the overnight session to the next trading
date.

### Choosing a source and avoiding double counts

- A *source* is one (dataset, schema) pair. All files of a source are unioned.
  Databento cuts files on UTC days, so 19:00–20:00 ET after-hours trades sit in
  the next day's file, and the union keeps them. A bar repeated by overlapping
  downloads is kept once.
- When several sources cover one ticker on one date, one source is picked per
  ticker: consolidated feeds (`EQUS`, `DBEQ`, `OPRA`) first, then the larger
  volume. For daily bars the order is `ohlcv-eod`, then bars aggregated from
  minutes, then `ohlcv-1d`, then `ohlcv-1h`.
- **Fill precedence:** Databento only writes tickers that no other vendor wrote
  into that partition. When massive later re-converts a partition, it re-filters
  the Databento part. To make Databento the primary source for some dates,
  convert it into a storage root without massive data for those dates.

### Incremental runs

- **Stage 1:** each raw file is extracted once into a staging parquet under
  `$STORAGE_ROOT/_staging/databento/`. The cache is keyed on file size, mtime and
  an extractor version, so a code change that alters bars rebuilds it.
  `--jobs N` extracts in parallel.
- **Stage 2:** each (store, date) partition is rebuilt only when the fingerprint
  of its inputs changes. The inputs are the staging files and the other vendors'
  parts.
- When a raw file is deleted, its partitions are rebuilt and parts left with no
  input are removed.
- A file that is unreadable now, or failed to extract, keeps its last good bars.
  Cleanup is skipped in that run, so a missing package or a bad download never
  deletes data.

On the reference server, converting all 3,816 convertible files (SPY/QQQ/SOXX
Nasdaq MBO, OPRA `tcbbo` and `cmbp-1`) took 28.5 minutes with `--jobs 12` and
produced 45 million rows. An unchanged re-run took one second.

### Commands

```bash
qfz-data status                                  # files by dataset/schema, convertible or not
qfz-data convert --vendor databento --jobs 8     # convert only Databento
qfz-data convert --all                           # massive, then Databento (fill), then corp actions
qfz-data update --source us_databento            # freshness-driven run

qfz-data config --set databento.api_key=db-…
qfz-data scan databento                          # datasets the key can query (free call)
qfz-data acquire databento --dataset OPRA.PILLAR --schema tcbbo \
    --symbols SPY.OPT --stype-in parent --start 2026-09-01 --end 2026-09-05
qfz-data acquire databento --dataset EQUS.MINI --schema ohlcv-1m \
    --symbols SPY,QQQ --start 2026-01-02 --end 2026-01-31 --max-cost 5 --run
```

`acquire` is a dry run unless `--run` is given. It prints the quoted cost first.
It refuses any request whose quote exceeds `--max-cost`, which defaults to 0, so
only free data downloads without an explicit ceiling. Files already on disk are
not quoted or fetched again. Downloads land in
`<dataset>/<schema>/<symbol>/<date>.dbn.zst`, with one file per weekday for tick
schemas and one file per range for OHLCV.

### Known limits

- A single-venue feed reports only that venue's volume. `XNAS.ITCH` SPY volume
  is about 17% of consolidated volume. Use `EQUS.*` for market-wide volume.
- Vendors can disagree. On one OPRA day the Databento trade count was about 5%
  higher than massive's own trade file. The `tcbbo` and `cmbp-1` adapters agree
  with each other exactly, and on another day both vendors matched exactly.
- Book depth beyond the top level is not converted, because UPQ has no store for it.
