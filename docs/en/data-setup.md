# Data setup utility

> 中文: [docs/cn/data-setup.md](../cn/data-setup.md)

*Data setup* (admins, console bar) brings Databento and massive data into
QFinZero. It does two things for each vendor:

- **Local files**: pick folders or files that are already on the server with a
  file browser, and import them.
- **Download**: describe what you want, look at the quote, and download with
  one of your vendor keys, following its progress and cost.

Both end with the same incremental conversion as `qfz-data convert`, so what
you import appears in *Data availability*, in UPQ and in every MCP tool.

## Where data goes: two layouts

QFinZero keeps data in two kinds of directory, and the **Directories** tab shows
both with their free space and state:

| layout | path (config key) | holds |
|---|---|---|
| RAW, massive | `raw_massive` (`RAW_MASSIVE_DIR`) | massive flat files as massive ships them: `<index>/YYYY/MM/YYYY-MM-DD.parquet` |
| RAW, Databento | `raw_databento` (`RAW_DATABENTO_DIR`) | DBN files: `<dataset>/<schema>/<symbol>/<date>.dbn.zst`; `imports/` holds links to imported files |
| RAW, Tushare | `raw_tushare` | Tushare dumps |
| QFZ store | `storage_root` (`STORAGE_ROOT`, default `$QFZ_DATA_ROOT/upq`) | the converted, query-ready layout UPQ serves: `<store>/trade_date=YYYY-MM-DD/*.parquet`, plus `_state` and `_staging` |

Downloads land in, and imports are linked into, the RAW libraries; the
pipeline reads them in place and never writes into them. Only the converter
writes the QFZ store.

**Initialise** saves the paths in the data configuration
(`$QFZ_DATA_ROOT/_state/qfz.config.json`, `dirs`), so every service and command
sees the same ones after a restart, creates the standard sub-directories and
writes a `.qfz-layout.json` marker into each root naming what it is. The
markers catch mistakes before anything is written: a directory initialised as
a RAW library cannot be chosen as the store, and two roles cannot share one
directory. An existing directory that already holds files but has no marker
(a shared data disk, say) is left alone unless you name it explicitly; the
result lists it under *skipped*.

## Vendor keys

Databento and massive sell many products separately, so one person may hold
several keys, each for some products, or one key for everything. The **Keys**
tab keeps a list per vendor:

- **products**: what the key may fetch, as patterns. Databento datasets
  (`OPRA.PILLAR`, `GLBX.*`, `XNAS.ITCH`), massive indices (`us_options_opra`,
  `us_stocks_sip`); `*` for all. A download uses the first key whose products
  match its dataset or index, or the key you pick in the request.
- **Test** checks a key against the vendor: the datasets Databento lets it
  list, or, for massive, which flat-file indices it can read. *Scope the key
  to these products* sets the key's products to what the test found.
- **monthly budget** (Databento): the key's spending limit per calendar month,
  in USD. A download whose quote exceeds what is left is refused.
- Secrets are stored by the data service and shown masked. Saving a key with
  the masked value (or blank) keeps the stored secret. A single key from an
  older configuration appears as `default`.

Every Databento download records what it cost in
`$QFZ_DATA_ROOT/_state/databento_spend.jsonl`. The tab shows spend per month
and key against the budgets, and the latest charges.

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
2. Add a key on the **Keys** tab first (see above). The request picks the
   matching key by default; choose another in *Key* if you hold several.
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
5. **Download and convert** starts a job. A Databento request that costs
   money needs the box *I accept a charge of up to $X to this Databento account*: ticking it sets the
   ceiling to the quote. Without it the ceiling is 0 and only free data is
   fetched. The key's monthly budget applies on top.

The job shows a progress bar (files and bytes, rate, time left, the file being
fetched), the stage (planned, downloading, converting) and, for Databento, the
cost so far. **Stop** ends it after the current file; what was already written
stays and a later download continues from there. Job history, including what
each download cost, is kept in `$QFZ_DATA_ROOT/_state/jobs/` and survives a
restart; a job that was running when the data service stopped shows as
*interrupted*.

Downloads use the same layout as the command line
(`qfz-data acquire databento …`), so either can continue what the other started.

## Store format and compression

The converter writes the QFZ store as zstd parquet, level 3, 122,880-row
groups. These can be changed in the data configuration (`format`:
`compression`, `level`, `row_group_rows`), but the defaults were chosen by
measurement on real partitions:

- zstd level 9 makes files 3-6% smaller and reads them as fast, but writes
  2-3x slower, so it is used only for partitions that no longer change.
- Larger row groups (500k rows) shrink files a little more but make
  single-ticker lookups 2-4x slower.
- Parquet format version 2 made `stock_minute` 66% larger.

**Compaction** rewrites partitions older than N days at zstd 9, checks each
file's row count against the original and swaps it in. Run it from the
**Directories** tab (*Estimate* shows the files and size first) or from the shell:

```bash
qfz-data compact --older-than 30 --dry-run
qfz-data compact --older-than 30 --stores option_minute,option_quote_minute
```

Compacted files are remembered in `_state/compact.json` by size and modification
time, so a re-run only touches new or reconverted partitions.

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
