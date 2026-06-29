# Unified Data Pipeline + Port Unification + MCP Modernization

**Date:** 2026-06-29
**Status:** Design approved (decisions locked), implementation in progress

## Goal

Make QFinZero ship with a formal, out-of-the-box **data pipeline** that:

1. Manages two raw market-data sources — **massive** (Polygon-style US: stocks, options,
   rates, corporate actions) and **tushare** (CN A-shares + HK via the Assay downloader) —
   read **in place** from a shared raw-data root, with no re-download or copy.
2. **Converts** raw quotes into the UPQ on-disk storage format, handling splits & dividends
   (referencing Assay's corporate-action math, but simplified: we only stream quotes, no
   factor backtesting).

Plus two cross-cutting cleanups:

3. **Unify service ports** to the 193xx block.
4. **Modernize the MCP server**.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Ports | All five services in 193xx (see map below) |
| Raw data | Read `/data/massive_data` + `/data/tushare_data` **in place**; qfinzero adds a registry + converter, no copy |
| Scope v1 | US equities (daily+minute), US options + rates, **CN A-shares**. HK deferred. |
| Adjustment | Store **raw/unadjusted** bars + a unified corporate-actions table; UPQ applies adjustment **on read** (`adjust=none\|split\|total`), exposing both raw and adjusted |

## Port map (193xx)

| Service | Old | New | Env override |
|---------|-----|-----|--------------|
| Dashboard Web | 19700 | **19300** | `DASHBOARD_PORT` |
| ESP | 19702 | **19330** | `ESP_PORT` |
| UPQ | 19703 | **19350** | `UPQ_PORT` (service reads `PORT`) |
| PMB | 19701 | **19380** | `PMB_PORT` |
| Playground | 19704 | **19390** | `PLAYGROUND_PORT` |

(ESP=19330 and UPQ=19350 already match the existing test fixtures.)

## Architecture

```
 RAW SOURCES (read in place, shared)              qfinzero/pipeline/ (NEW, Python)
 ┌───────────────────────────┐                    ┌────────────────────────────┐
 │ /data/massive_data        │   registry.py ───▶ │ scan + manifest of what     │
 │   us_stocks_sip/*.parquet │                    │ raw data exists (markets,   │
 │   us_options_opra/*.parquet│                   │ date ranges, symbol counts) │
 │   corporate_actions/*.jsonl│                   ├────────────────────────────┤
 │   economy/treasury_*.jsonl │   sources/        │ readers normalize each      │
 │ /data/tushare_data        │   massive.py ────▶ │ source to a common frame    │
 │   cn/daily/*.parquet      │   tushare.py       ├────────────────────────────┤
 │   cn/dividend/*.parquet   │   corporate_       │ unify splits + dividends    │
 │   cn/adj_factor/*.parquet │   actions.py ────▶ │ (float ratios, precomputed  │
 └───────────────────────────┘                    │ dividend price ratio)       │
                                  convert.py ────▶ ├────────────────────────────┤
                                  cli.py           │ write UPQ STORAGE_ROOT      │
                                                   └─────────────┬──────────────┘
                                                                 ▼
                                          UPQ STORAGE_ROOT/ (parquet, partitioned)
                                            stock_daily/  stock_minute/
                                            option_day/   option_minute/
                                            rates/rates.parquet
                                            corporate_actions/corporate_actions.parquet
                                                                 ▼
                                          UPQ service (Rust) — adjust on read ──▶ MCP / clients
```

## Component design

### 1. Config additions (`qfinzero/config.py`, `config/qfinzero.env`)

```
RAW_MASSIVE_DIR   = env("RAW_MASSIVE_DIR", "/data/massive_data")
RAW_TUSHARE_DIR   = env("RAW_TUSHARE_DIR", "/data/tushare_data")
UPQ_STORAGE_ROOT  = env("STORAGE_ROOT", "<repo>/storage")   # matches UPQ service
```

### 2. Raw-data registry (`qfinzero/pipeline/registry.py`)

Scans the raw roots and produces a JSON/sqlite manifest: per (market, asset, resolution)
the available date range, file count, and symbol count; plus what has already been
converted (idempotent re-runs). Surfaced via `qfz-data status`.

### 3. Source readers (`sources/massive.py`, `sources/tushare.py`)

Normalize each vendor to a common in-memory frame (polars) before writing:

- **massive stocks/options**: already `ticker, window_start(ns), open, high, low, close,
  volume, transactions`. Daily uses `trade_date` derived from filename; options parse the
  OPRA ticker (`O:UND YYMMDD C/P 8-digit-strike/1000`) into `underlying/expiry/strike/right`
  (same regex as `upq-ingest`).
- **tushare CN daily**: `trade_date` (YYYYMMDD string) → DATE; `ts_code` → `ticker`;
  `vol` (手 / 100-share lots) → `volume = vol*100` (shares); `transactions` → null. CN is
  daily-only (no minute in tushare).

### 4. Unified corporate actions (`sources/corporate_actions.py`)

One canonical table written to `STORAGE_ROOT/corporate_actions/corporate_actions.parquet`:

| column | type | meaning |
|--------|------|---------|
| `symbol` | str | ticker / ts_code |
| `ex_date` | date | ex / effective date |
| `split_ratio` | f64 | forward share ratio (1.0 = none) |
| `dividend_cash` | f64 | cash per share in local ccy (0.0 = none) |
| `div_price_ratio` | f64 | **precomputed** `1 - cash/close_prev` (1.0 = none) |
| `currency` | str | USD / CNY |
| `source` | str | provenance |

Mapping (reference: Assay `adjust.py` / `ingest.py`, simplified):
- **massive splits**: `split_ratio = split_to / split_from` (supports fractional).
- **massive dividends**: `dividend_cash = cash_amount`, `ex_date = ex_dividend_date`.
- **tushare 送转**: `split_ratio = 1 + stk_div` (e.g. "10转15" → 1.5); only `div_proc=="实施"`.
- **tushare cash**: `dividend_cash = cash_div_tax or cash_div` (pre-tax priority).
- `div_price_ratio` is computed **at conversion time** from the prior trading close
  (`1 - cash/close_prev`, guarded for gaps/zeros, like Assay). Precomputing it keeps UPQ's
  on-read math purely multiplicative — no query-time close lookup.

### 5. Converter (`convert.py`) → UPQ storage

Writes ZSTD parquet into the exact layout UPQ reads (verified against `upq-ingest`):
`{stock_daily,stock_minute,option_day,option_minute}/trade_date=YYYY-MM-DD/part-*.parquet`,
plus `rates/rates.parquet` and `corporate_actions/corporate_actions.parquet`. CN regrouping
(3,472 per-symbol files → per-date partitions) done with polars/duckdb. CN and US coexist in
one store (ticker namespaces are disjoint: `AAPL` vs `000001.SZ`).

**Known gaps to flag:** massive `treasury_yields.jsonl` has only 1Y/5Y/10Y of UPQ's 7
tenors → other tenors written null. HK deferred. Options are US-only (no CN/HK options).

### 6. UPQ Rust changes (`infra/upq`)

- Load `corporate_actions/corporate_actions.parquet` (extend/replace the integer-only
  `splits.json` model with float `split_ratio` + `div_price_ratio`).
- Add `adjust` query param to `/stock` and `/stock/daily` (`none` default, `split`, `total`):
  for a bar at date `d`, multiply price by `Π(ratios for ex_date > d)` and volume inversely.
  `split` uses `1/split_ratio`; `total` also multiplies `div_price_ratio`.
- Keep `dividends/dividends.parquet` (option Greeks + `/dividends/query`) derived from the
  unified table for backward compatibility.
- Default port → 19350.

### 7. Pipeline UX (`qfz-data` CLI + `scripts/`)

Console entry point `qfz-data`:
- `qfz-data status` — print the raw-data registry + conversion state.
- `qfz-data convert --market {us,cn} --asset {stock,option,rates} [--resolution daily|minute] [--start --end | --all]`
- `qfz-data validate` — schema/row-count/freshness checks against UPQ.
Idempotent manifest so re-runs are incremental. `scripts/data_pipeline.sh` wraps it.
New deps: `polars`, `pyarrow` (+ optional `duckdb`).

### 8. MCP modernization (`mcp/`)

Current state is already modern FastMCP (`mcp[cli]>=1.0.0`, stdio, 37 tools delegating to
the HTTP clients). Modernization:
- Add **streamable-HTTP** transport alongside stdio (2025 standard).
- **Modularize** `server.py` (1085 lines) into `tools/{upq,esp,pmb}.py`.
- Add **resources** (data freshness, symbol universe, port map) and **prompts** (trading
  workflow template).
- Add a `data_*` tool surfacing the pipeline registry/freshness.
- Pin latest MCP SDK; add structured-output return types.

## Phasing

1. **Ports** — unify to 193xx (config, services, scripts, tests). *Foundational, low-risk.*
2. **Registry + config** — RAW_*/STORAGE_ROOT + `qfz-data status`.
3. **Converter: US** — stocks (daily+minute), options, rates → validates against existing UPQ.
4. **Corporate actions + UPQ on-read adjust (Rust) + CN A-shares** — the main new work.
5. **MCP modernization**.
6. **Docs/README/tests** sweep.

## Implementation status (2026-06-29)

All phases implemented and validated against the real `/data/massive_data` and
`/data/tushare_data` sources:

- Ports unified to 193xx across config/services/scripts/tests/docs.
- `qfinzero/pipeline/` package + `qfz-data` CLI (status/convert/validate); DuckDB engine.
- US stocks/options/rates + CN A-shares convert to byte-compatible UPQ parquet; OPRA
  parsed; 783k-row corporate_actions table built (splits, 送转, gap-guarded dividend ratios).
- UPQ Rust: `corporate_actions.rs` + `adjust=none|split|total` on `/stock` and `/stock/daily`
  (raw by default), with legacy `splits.json` fallback. Built and live-verified
  (AAPL dividend ×0.99890; BTAI reverse split price ×16 / volume ×0.0625).
- MCP: streamable-HTTP transport option, `qfinzero://{ports,data/freshness,health}` resources,
  `trading_session` prompt; 37 tools unchanged.

### Running (env note)

Use a dedicated Python 3.10+ venv — the repo's checked-in `.venv` is a stale 3.8 and the
shared conda base has a self-conflicting fastapi/starlette/sse-starlette pin:

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[pipeline]" -r mcp/requirements.txt -r requirements.txt
# Data defaults under QFZ_DATA_ROOT=/data/qfinzero (upq/ esp/ raw/); override if needed.
qfz-data convert --all            # -> /data/qfinzero/upq
(cd infra/upq && STORAGE_ROOT=/data/qfinzero/upq PORT=19350 ./target/release/upq-service)
```
