# Changelog

All notable changes to QFinZero. Dates are release dates; versions follow
[Semantic Versioning](https://semver.org/) once 1.0 is reached.

## Unreleased: QFZView and the broker

Added:

- QFZView (`/view`): a TradingView-style viewer over the store for stocks,
  futures, crypto, FX and option contracts, with 1-minute to daily intervals,
  zoom and pan, paged history, MA/EMA/Bollinger/VWAP and a bid/ask overlay.
- The broker's chart uses the same component: history from before the session
  (time-locked), zoom, intervals, fill markers, working-order and average-price
  lines. Orders report their outcome, including fills on later bars.
- Live Greeks in the broker's option chain (IV, delta, gamma, theta, vega at the
  session clock from `/option/chain_snapshot`) and real bid/ask instead of a
  synthetic spread.
- Settings → Rates: load U.S. Treasury or FRED rate files; they are kept across
  updates and laid over the massive rates.
- Benzinga monthly news archives (`YYYY-MM.jsonl.gz`) load into ESP with the
  teaser, image and full article text; `/esp/news/{id}/body` returns `body` and
  accepts the `news_…` event id of a search result. Titles are HTML-unescaped.
- In-place reads (behind `UPQ_IN_PLACE`, off by default): UPQ reads
  `option_minute`, `option_day` and `stock_daily` straight from the massive raw
  files through views the index writes from the converter's own projection;
  other vendors' parts still join. 520 compared requests matched the converted
  store row for row.
- Raw-data index: *Data setup* → *Scan & index* and `qfz-data index` recognise
  massive, Databento, Tiingo and custom parquet (`qfz.dataset.yaml`) files in
  place and catalogue them under `_state/index/` (files, row groups, symbols,
  levels L0-L2), rescanning only changed files. Nothing is converted.
- Blue Ocean overnight session: the `OCEA.MEMOIR` order book is replayed into
  minute quotes (`stock_quote_minute`), and each 20:00-04:00 ET session becomes
  one bar in the new `stock_overnight_daily` store, dated by the trading day it
  precedes (trading calendar aware). UPQ `/stock/daily?session=overnight`, MCP
  `upq_stock_daily(trading_session="overnight")`, and an overnight level in
  the coverage map.
- Tiingo BOATS overnight data: a Tiingo vendor key, `qfz-data acquire tiingo`
  (minute bars from 2026-07-07; a once-a-minute top-of-book recorder) into
  `$RAW_TIINGO_DIR`, and `qfz-data convert --vendor tiingo`, which fills
  `stock_minute`, `stock_overnight_daily` and `stock_quote_minute` behind
  Databento for about 9,000 tickers. Two schedule groups, off by default.
- Settings → News storage: MongoDB connection and test, documents, disk and
  index size per collection, one collection per vendor (`news_benzinga`,
  `news_tushare`) copied out of the shared `ticker_news` (left unchanged), a
  switch between the two that ESP follows without a restart, and import of
  Benzinga files or `.zip` archives from the server.

Changed:

- Removed the Rust `upq-ingest` crate, `scripts/upq_flatfiles.sh`, the
  `us_prices` acquire target and the store-conversion design documents: the
  data pipeline (`qfz-data`) builds every store, and the raw-data index design
  (`docs/plans/2026-10-20-raw-index-design.md`) replaces them.
- QFinZero stops at consolidated BBO: Databento `cmbp-1` and market-by-order
  data outside Blue Ocean are indexed but no longer converted, and the
  download form refuses them (they only duplicated consolidated trades and
  quotes).
- UPQ shares one DuckDB database through a connection pool; a full queue
  answers 503 instead of failing with 500 (`UPQ_POOL_SIZE`,
  `UPQ_DUCKDB_THREADS`, `UPQ_QUEUE_TIMEOUT_S`).
- Greeks use the latest yield curve on or before the date instead of none.
- Day suggestions in the broker's date picker rank by traded value.

## Unreleased: data utility

Added:

- Two on-disk layouts made explicit: RAW libraries per vendor and the QFZ
  store. *Data setup → Directories* (and `POST /setup/layout/init`) saves the
  paths, creates the sub-directories and writes `.qfz-layout.json` markers;
  existing unmarked data is never initialised unless chosen explicitly.
- Several keys per vendor, each limited to products (Databento datasets,
  massive indices), with a live test against the vendor, Databento monthly
  budgets and a spend ledger (`_state/databento_spend.jsonl`).
- Download progress (files, bytes, rate, time left, cost so far), a stop
  button, an explicit charge confirmation for paid Databento requests, and a
  job history that survives restarts.
- Configurable store format and archive compaction at zstd 9
  (`qfz-data compact`): 3-6% smaller at the same read speed.
- API key distribution: scopes, read-only keys, expiry, per-key rate limits
  and daily usage; admins issue keys to other users; MCP tool calls are
  checked against the key's scopes; `qfz-auth create-key --scopes …`.
- Crypto and FX from massive's global flat files: `crypto_daily`,
  `crypto_minute`, `fx_daily`, `fx_minute` and `fx_quote_minute` (FX bid/ask),
  on UTC days; UPQ `/crypto`, `/crypto/daily`, `/fx`, `/fx/daily`,
  `/fx/quote`; five MCP tools; coverage map groups (`X:BTC-USD`, `C:EUR-USD`);
  downloads and *Update* for the global products.
- *Update* also fills gaps inside the last 120 days, and massive entitlement
  is checked by downloading (HEAD), not by listing.
- A new documentation hub: home page, guides with a live table of contents,
  ⌘K search over guides, endpoints and tools, an API reference for UPQ, ESP
  and PMB with code samples and in-page requests, and an MCP tool reference,
  generated by `python -m qfinzero.docsgen` (`docs/api/reference.json`).

Changed:

- Viewers may send ESP and UPQ queries as `POST` (they are reads); before,
  every viewer `POST` was refused.
- `/docs` now always opens the documentation hub; the hub's FastAPI schema
  page moved from `/docs` to `/svc/openapi`.
- `docs/upq/openapi.yaml` documents `/dividends/query`.

## Unreleased: intraday platform

Upgrade notes:

- **Sign-in is on by default.** Create an admin before the first start
  (`QFZ_ADMIN_PASSWORD`, `qfz-auth create-user`, or `/setup`), and give agents
  API keys. `QFZ_AUTH_MODE=off` restores the old open behaviour for local use.
- `config/qfinzero.env` no longer pins `STORAGE_ROOT` and the ESP database
  paths; they follow `QFZ_DATA_ROOT`. If you relied on the old values with a
  different data root, set them explicitly.
- ESP now hides earnings and macro results until their release time relative
  to `now_utc`. Clients that read results "from the future" in replays now get
  `null`, which is the intended behaviour.

Added:

- Point-in-time caps in UPQ (`as_of`, `UPQ_AS_OF`) and a time lock that binds
  MCP data tools to a PMB session (`X-QFZ-Session`).
- Trading sessions in PMB: overnight, pre-market, regular and after-hours
  segments, `trading_hours` on orders, DAY/GTD expiry, partial fills,
  `step_until`, and option fills against the NBBO.
- Minute quote stores (`stock_quote_minute`, `option_quote_minute`) and
  intraday option-chain snapshots; Databento overnight (OCEA) and quote schemas.
- Intraday factor research: a factor language, IC/rank IC evaluation and
  cost-aware backtests (`qfz-research`, `research_*` MCP tools).
- Users, roles, API keys and an authenticating hub for the UI, REST and MCP
  (`qfz-auth`).
- A synthetic, redistributable sample dataset (`qfz-sample`) and an agent
  benchmark on it with an oracle and an OpenAI-compatible runner (`qfz-bench`).
- SQLite news backend for ESP, used automatically when `esp/news.sqlite3` exists.
- NYSE holiday and early-close calendar used by PMB.
- Docker image, `docker-compose.yml` and a GitHub Actions workflow running the
  Python, Rust, web and end-to-end suites.
- A documentation hub in the web UI (`/docs`) and an English / Chinese UI.
- A data setup utility (`/data-setup`, admins): import Databento and massive
  files from the server through a confined file browser, or download with a
  key (Databento quoted and capped, massive flat files planned), then convert
  automatically; `pip install -e ".[massive]"` adds the massive downloader.
- A data availability dashboard (`/availability`): data levels per ticker and day (daily, minute
  by session, quotes, option EOD / minute / quotes) with news, earnings and
  macro releases on the same time axis; ESP `GET /esp/news/counts`.
- Minute BBO at a chosen sampling interval (1, 5, 15, 30 or 60 minutes per
  asset class), from Databento quote schemas and massive quotes flat files,
  REST samples and snapshots.
- Futures: Databento futures venues (CME Globex `GLBX.MDP3`, ICE, Nodal) convert
  into `future_minute`, `future_daily` (with `settle`) and `future_quote_minute`
  on CME session dates; UPQ `/future`, `/future/daily`, `/future/quote` and the
  `upq_future_*` tools; PMB futures with contract specs, per-contract initial
  and maintenance margin, daily variation margin, margin calls met at initial
  margin and liquidation of unmet calls (`pmb_trade_future`, `universe.futures`,
  `add_futures`); futures in the broker terminal and the availability map;
  exchange settlement prices from Databento `statistics`, and rolls of
  continuous series (by `instrument_id`) that move positions without booking
  the spread.
- Chat conversations stored per user (new, rename, delete, search), the context
  rebuilt from the history each turn with tool-result trimming and automatic or
  manual compaction, a context meter, stopping an answer (kept as interrupted),
  answers that survive closing the page, Markdown export, and a run inspector
  with the tool-call record, a flow graph and a timeline.
- Data availability on a continuous calendar with stock and futures groups
  (futures as `/ROOT`), expandable layers (stock data, options, news, company
  events), a macro lane, a draggable overview of the whole history and an
  asset panel; broker accounts with futures margin settings and a session
  calendar that marks the days with data.
- Model groups for Chat: OpenAI, Claude and Gemini via Antigravity endpoints,
  model lists fetched from `/models`, import of Claude Code settings, export
  lines or Codex `config.toml`, and JSON import / export.

Changed:

- One plain visual style across the site, console and PMB's own page; the
  broker terminal runs inside the console.
- `upq_stock_daily` and `upq_stock_minute` accept `adjust` (`none`, `split`, `total`).

Fixed:

- ESP leaked earnings and macro results before their release time in replays.
- The PMB page embedded `:19380` directly, which failed behind the hub.
- `esp_get_event`, `esp_news_body` and `esp_search_news` ignored the session clock.
- ESP connected to its news and event sources only at start-up; it now
  reconnects when one comes back.
- Rewinding a PMB session dropped its partial-fill, trading-hours and option
  fill settings.
- The data setup and availability components, the coverage route and the
  shipped benchmark tasks were excluded from the repository by `.gitignore`.

## 0.1.0 (2026-10-16)

- First open-source release: UPQ, ESP, PMB, the MCP server, the data pipeline
  (massive, Tushare) and the unified hub.
- Databento adapter for DBN and parquet files (`qfz-data convert --vendor databento`).
