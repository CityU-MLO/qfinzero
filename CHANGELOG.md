# Changelog

All notable changes to QFinZero. Dates are release dates; versions follow
[Semantic Versioning](https://semver.org/) once 1.0 is reached.

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

## 0.1.0 (2026-10-16)

- First open-source release: UPQ, ESP, PMB, the MCP server, the data pipeline
  (massive, Tushare) and the unified hub.
- Databento adapter for DBN and parquet files (`qfz-data convert --vendor databento`).
