# Configuration

> 中文: [docs/cn/configuration.md](../cn/configuration.md)

QFinZero is configured with environment variables. Each process reads, in this
order of precedence:

1. the process environment;
2. `.env` in the repository root (copy `.env.example`; not committed);
3. `config/qfinzero.env` (committed defaults).

A value set earlier is never overridden by a later source. The hub passes its
environment to the services it starts, so setting a variable for `qfz-server`
sets it everywhere. Data-vendor credentials can also be stored by the data
console in `$QFZ_DATA_ROOT/_state/qfz.config.json` (`QFZ_CONFIG_FILE` moves it).

## Hub and ports

| variable | default | meaning |
|---|---|---|
| `QFZ_SERVER_PORT` | `19777` | the hub's port: web UI, `/svc/*`, `/mcp`, `/auth` |
| `QFZ_SERVER_HOST` | `0.0.0.0` | the hub's bind address |
| `QFZ_HOST` | `127.0.0.1` | address the services bind to and are reached at |
| `UPQ_PORT`, `ESP_PORT`, `PMB_PORT` | `19350`, `19330`, `19380` | internal service ports |
| `PLAYGROUND_PORT`, `DATA_ADMIN_PORT`, `DASHBOARD_PORT` | `19390`, `19340`, `19300` | internal ports of the chat backend, data console and web UI |
| `QFZ_SUPERVISE` | `1` | `0` makes the hub proxy to services you run yourself instead of starting them |
| `QFZ_SERVE_UI` | `auto` | start the web UI when `infra/dashboard-web/.next` exists; `0` never |
| `UPQ_BIN` | build in the repo | path of the `upq-service` binary |
| `UPQ_HOST` | `127.0.0.1` | UPQ's bind address; set `0.0.0.0` only to expose it without the hub |

A service already listening on its port is adopted rather than started again.

## Data

| variable | default | meaning |
|---|---|---|
| `QFZ_DATA_ROOT` | `/data/qfinzero` | root of everything QFinZero owns: `upq/`, `esp/`, `_state/` |
| `STORAGE_ROOT` | `$QFZ_DATA_ROOT/upq` | UPQ price storage |
| `EARNINGS_DB` | `$QFZ_DATA_ROOT/esp/benzinga_earnings.sqlite3` | earnings calendar |
| `ECON_EVENTS_DB` | `$QFZ_DATA_ROOT/esp/nasdaq_econ_events.sqlite3` | macro calendar |
| `NEWS_DB` | `$QFZ_DATA_ROOT/esp/news.sqlite3` | SQLite news store |
| `RAW_MASSIVE_DIR`, `RAW_TUSHARE_DIR`, `RAW_DATABENTO_DIR` | `/data/massive_data`, `/data/tushare_data`, `/data/databento` | vendor files, read in place by `qfz-data` |
| `QFZ_DATABENTO_JOBS` | `1` | default parallelism of `qfz-data convert --vendor databento` |
| `QFZ_BROWSE_ROOTS` | the raw directories, `QFZ_DATA_ROOT`, `/data` | `:`-separated directories the data setup file browser may show |
| `QFZ_STOCK_QUOTE_INTERVAL`, `QFZ_OPTION_QUOTE_INTERVAL`, `QFZ_FUTURE_QUOTE_INTERVAL` | the *BBO sampling* setting, else `1` | minutes between kept books in the quote stores: 1, 5, 15, 30 or 60 |

Leave the derived paths unset unless a store lives outside the data root.

## Accounts and sign-in

| variable | default | meaning |
|---|---|---|
| `QFZ_AUTH_MODE` | `required` | `off` disables all checks (local development only) |
| `QFZ_ADMIN_USERNAME`, `QFZ_ADMIN_PASSWORD` | `admin`, unset | create this admin on the first start if no user exists |
| `QFZ_SECRET_KEY` | generated into `_state/auth_secret` | key that signs session cookies; set it when several hubs share users |
| `QFZ_SESSION_DAYS` | `7` | browser session lifetime |
| `QFZ_COOKIE_SECURE` | `auto` | `Secure` cookies when the request came over HTTPS; `1`/`0` force it |
| `QFZ_STATE_DIR` | `$QFZ_DATA_ROOT/_state` | where the auth database, secret and setup token live |
| `QFZ_AUTH_DB` | `$QFZ_STATE_DIR/auth.sqlite3` | users and API keys |
| `QFZ_PUBLIC_HOSTS` | unset | comma-separated public host names allowed to reach `/mcp` (MCP's DNS-rebinding protection) |

## Time lock and research

| variable | default | meaning |
|---|---|---|
| `QFZ_REQUIRE_SESSION` | unset | `1` refuses any MCP data query that is not bound to a PMB session |
| `QFZ_TIME_LOCK_SESSION` | unset | bind every MCP call of this process to one session |
| `UPQ_AS_OF` | unset | hard ceiling for every UPQ query (ISO time or nanoseconds); an invalid value serves nothing |
| `QFZ_RESEARCH_MAX_DAYS` | `40` | trading days a `research_*` call may cover |
| `QFZ_RESEARCH_MAX_UNIVERSE` | `1000` | stocks a `research_*` call may rank |

## ESP (news and events)

ESP reads settings with the `ESP_` prefix.

| variable | default | meaning |
|---|---|---|
| `ESP_NEWS_BACKEND` | `auto` | `auto` uses `NEWS_DB` when the file exists, else MongoDB; `sqlite` or `mongo` force one |
| `ESP_MONGO_URI` or `MONGO_URI` | `mongodb://localhost:27018` | MongoDB holding the news collection |
| `ESP_MONGO_DB` or `MONGO_DB` | `market_news` | database |
| `ESP_MONGO_COLLECTION` or `MONGO_COLLECTION` | `ticker_news` | collection |
| `ESP_DEFAULT_PAGE_SIZE`, `ESP_MAX_PAGE_SIZE` | `50`, `500` | pagination limits |
| `ESP_LOG_LEVEL` | `INFO` | log level |

## PMB (paper broker)

| variable | default | meaning |
|---|---|---|
| `PMB_UPQ_BASE_URL` | the UPQ service | where PMB loads prices from (set by the hub) |
| `PMB_LOG_LEVEL` | `INFO` | log level |

Broker defaults (initial cash, fees, slippage, margin, fill model) are edited
under *Broker → Broker settings* or with `pmb_get_config`/`PUT /v1/config`, and
persist on the server.

## MCP server outside the hub

`python mcp/server.py` runs the tools on their own, for a local client.

| variable | default | meaning |
|---|---|---|
| `QFINZERO_MCP_TRANSPORT` | `stdio` | `stdio`, `streamable-http` or `sse` |
| `QFINZERO_MCP_HOST`, `QFINZERO_MCP_PORT` | `127.0.0.1`, `19360` | address for the HTTP transports |
| `QFINZERO_UPQ_URL`, `QFINZERO_ESP_URL`, `QFINZERO_PMB_URL` | the local services | service URLs |

## Chat, models and vendors

| variable | meaning |
|---|---|
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | default model provider for Chat and `qfz-bench run` |
| `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY` | detected by the Chat settings page |
| `LLM_PROXY` | HTTP proxy for outbound model calls only (falls back to `HTTPS_PROXY`/`HTTP_PROXY`) |
| `PLAYGROUND_TIMEOUT_S` | model request time-out of the chat backend, default 120 |
| `PLAYGROUND_DB` | chat history database, default `$QFZ_STATE_DIR/playground.sqlite3` |
| `MASSIVE_REST_API_KEY`, `POLYGON_S3_ACCESS_KEY_ID`, `POLYGON_S3_SECRET_ACCESS_KEY` | massive (Polygon) REST and flat files |
| `DATABENTO_API_KEY` | Databento historical API (`qfz-data acquire databento`) |
| `TUSHARE_TOKEN` | Tushare |
| `BENZINGA_API_KEY` | Benzinga earnings collector |

## Web UI

| variable | meaning |
|---|---|
| `NEXT_PUBLIC_REPO_URL` | repository linked from the site and the docs' *View source* links |
| `NEXT_PUBLIC_STATUS_REFRESH_MS` | refresh interval of service status cards |

The UI's language follows the `qfz_lang` cookie set by the EN / 中文 switch, or
the browser's language on the first visit.
