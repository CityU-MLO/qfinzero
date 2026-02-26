# News Data Pipeline Scripts — Design

**Date:** 2026-02-24
**Status:** Approved

## Overview

A single shell script `scripts/news_data.sh` deployed via git to `/home/qlib/qfinzero/scripts/` on the qlib server. It wraps all existing Python scrapers in `/home/qlib/news/` and exposes four sub-commands.

## Sub-commands

| Command | Purpose |
|---|---|
| `init` | One-time full historical download of all data sources through today |
| `update` | Daily incremental update (idempotent, resume-safe) |
| `deploy-cron` | Install crontab entry to run `update` daily at 06:00 UTC |
| `status` | Show latest date / row count for each data source |

## Data Sources

| Script | Data | init | update |
|---|---|---|---|
| `massive_download_all.py` | Market news 2022→today | Full run (skips existing files) | Full run (same, resume-safe) |
| `insert_mongodb.py` | JSON → MongoDB `market_news.ticker_news` | Full upsert all JSON files | Full upsert (idempotent) |
| `scrape_nasdaq_econ_events.py` | NASDAQ econ calendar 2020→today | Full run | Full run (upsert) |
| `benzinga_calendar.py` | Benzinga earnings FY2011–2026 | Full run | Full run (upsert) |

## Config

- **Working dir for scripts:** `/home/qlib/news`
- **Python env:** `/home/qlib/miniconda3` base conda env
- **API Key:** `MASSIVE_API_KEY` hardcoded (consistent with existing scripts)
- **Log dir:** `/home/qlib/news/logs/`

## Cron Schedule

```
0 6 * * * /home/qlib/qfinzero/scripts/news_data.sh update >> /home/qlib/news/logs/cron.log 2>&1
```

`deploy-cron` is idempotent (checks for existing entry before adding).

## Style

Follows `test-env.sh` conventions: `set -euo pipefail`, colored output helpers (`info`, `warn`, `error`, `section`), heredoc-based remote shell execution pattern not needed (runs locally on qlib).
