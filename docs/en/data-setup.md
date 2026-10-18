# Data setup utility

> 中文: [docs/cn/data-setup.md](../cn/data-setup.md)

*Data setup* (admins, console bar) brings Databento and massive data into
QFinZero. It does two things for each vendor:

- **Local files**: pick folders or files that are already on the server with a
  file browser, and import them.
- **Download**: save your key, describe what you want, look at the quote, and
  download.

Both end with the same incremental conversion as `qfz-data convert`, so what
you import appears in *Data availability*, in UPQ and in every MCP tool.

## Where data goes

| path | role |
|---|---|
| `RAW_DATABENTO_DIR`, `RAW_MASSIVE_DIR` | the *raw library* of each vendor; downloads land here and imports are linked here |
| `STORAGE_ROOT` (default `$QFZ_DATA_ROOT/upq`) | converted QFinZero storage that UPQ serves |

The strip at the top of the page shows the three paths and whether each vendor
has a key.

## Importing local files

1. Choose **Databento** or **massive**, then the **Local files** tab.
2. Browse the server. The browser shows only the allowed roots: the raw
   libraries, `QFZ_DATA_ROOT` and `/data`, or the directories in
   `QFZ_BROWSE_ROOTS` (`:`-separated). Paths are resolved, so symlinks and `..`
   cannot leave them. Badges mark what was recognised (DBN, massive parquet,
   massive csv.gz, a Databento dataset folder).
3. Tick folders or files (or *Select this folder*) and press **Inspect**:
   - massive: the datasets found (`us_stocks_sip/day_aggs_v1`, `…/minute_aggs_v1`,
     `us_options_opra/…`), the number of days, the date range, and how many
     `.csv.gz` files will be converted to parquet;
   - Databento: each (dataset, schema) with its date range and whether it
     converts into bars or quotes (definition, statistics and status files are
     reference data).
4. Press **Import and convert**. A job starts; follow its log under *Jobs*.

What import does:

- massive day files are linked into `RAW_MASSIVE_DIR/<dataset>/YYYY/MM/`;
  `.csv.gz` flat files are converted to zstd parquet there. Then each dataset
  is converted for the date range that was imported.
- Databento selections are linked under `RAW_DATABENTO_DIR/imports/`, and the
  Databento conversion runs over the whole library. Because every import stays
  in the library, a later import never drops what an earlier one brought in.
  Files are linked, not copied; keep the originals where they are.
- Re-importing the same selection links nothing new, and the conversion skips
  partitions whose inputs did not change.

## Quotes (BBO) and the sampling interval

Both vendors can fill the minute quote stores that PMB fills orders against
and that option-chain snapshots read their bid and ask from:

- Databento: `cbbo-1m`, `cbbo-1s`, `bbo-*`, `cmbp-1` (stocks and OPRA), and
  `mbp-1` / `mbp-10` from a futures venue.
- massive: `us_options_opra/quotes_v1` and `us_stocks_sip/quotes_v1` flat
  files (tick by tick, very large), the REST quotes samples (`*.jsonl.gz`) and
  30-minute snapshot parquet files. Inspect shows how many files of each kind
  it found.

*BBO sampling* sets, per asset class (stocks, options, futures), whether every
minute's book is kept or only the last one of each 5, 15, 30 or 60 minutes.
15 minutes keeps a full-market OPRA day small enough for a laptop; the broker
and the chain snapshot carry the last book forward in between. The setting is
saved and later conversions and scheduled updates use it; changing it rebuilds
the quote partitions that are converted next.

## Futures

Databento files from CME Globex (`GLBX.MDP3`) and the ICE and Nodal venues
convert into `future_minute`, `future_daily` and `future_quote_minute`. Import
an `mbo`, `trades`, `ohlcv-1m` or `mbp-1` folder like any other Databento
data. Continuous symbols (`CL.v.0`) become the product root (`CL`); outright
contracts keep their symbol. Trade dates follow the CME session (18:00 ET the
evening before to 17:00 ET). *Data availability* has the three futures levels,
and the broker trades them with exchange-style margin (see the PMB guide).

## Downloading

1. Choose the vendor and the **Download** tab.
2. Enter the credentials once; they are stored by the data service in
   `$QFZ_DATA_ROOT/_state/qfz.config.json` and never shown again.
   - Databento: the API key from the Databento portal.
   - massive: the S3 access key ID and secret from the massive dashboard (flat
     files), and the endpoint (`https://files.massive.com`, the default
     `https://files.polygon.io` also works).
3. Fill in the request:
   - Databento: dataset (for example `EQUS.MINI`, `XNAS.ITCH`, `OPRA.PILLAR`,
     `OCEA.MEMOIR`), schema, symbols (`SPY,QQQ`, or `SPY.OPT` with symbol type
     *parent* for a whole option chain), dates and a cost ceiling in USD.
   - massive: one of the aggregate or quotes datasets and the dates.
4. **Get quote** / **Plan** shows what would be fetched: the Databento cost and
   billable size (the quote is free), or the number of missing massive days and
   their size. Files already on disk are excluded.
5. **Download and convert** starts a job. Databento refuses a request whose
   quote exceeds the ceiling, which defaults to 0 so that only free data is
   fetched without an explicit amount.

Downloads use the same layout as the command line
(`qfz-data acquire databento …`), so either can continue what the other started.

## Storage status

The **Storage status** tab is the former *Data* page: raw data against converted
storage per source, with *Plan* and *Update* for the scheduled conversions.
Data checks for the event stores are linked from there.

## Requirements and limits

- Databento downloads need `pip install -e ".[databento]"`; massive downloads
  need `pip install -e ".[massive]"` (boto3). The Docker image includes both.
- massive trades flat files are not converted (no adapter yet). Quotes flat
  files are tens to hundreds of GB a day for OPRA; plan before downloading.
- Jobs run on the server; leaving the page does not stop them, and their logs
  stay under *Jobs*.
