> 中文: [../../cn/esp/README.md](../../cn/esp/README.md)


# ESP — News Pushing Pipeline

A flexible pipeline for collecting, parsing, and broadcasting financial news events into downstream trading or modeling systems.

## Server

- **Language**: Python
- **Entry Points**: Multiple ingestion scripts in `infra/esp/`

```bash
cd infra/esp
pip install -r requirements.txt
python massive_news.py
```

## Components

### Ingestion Scripts

| Script | Description |
|--------|-------------|
| `massive_news.py` | Bulk news ingestion from multiple sources |
| `stockbench_news.py` | StockBench-specific news feed |
| `economic_events.py` | Economic calendar events |
| `fomc_scraper.py` | FOMC meeting minutes and decisions |
| `nasdaq_earnings.py` | NASDAQ earnings announcements |

### Utility Scripts (`scripts/`)

| Script | Description |
|--------|-------------|
| `monitor_fetcher.py` | Monitor running fetch jobs |
| `fetch_nasdaq_earnings.py` | Fetch NASDAQ earnings data |
| `fetch_massive_news.py` | Batch news fetch orchestrator |

### Client

| Module | Description |
|--------|-------------|
| `massive_client.py` | Client for querying ingested news |

## API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/news/push` | POST | Push a news item to downstream consumers |
| `/news/query` | GET | Query stored news by ticker, date range, source |
| `/news/sources` | GET | List available news sources |

## Data Flow

```
Sources (RSS, APIs, scrapers)
        │
        v
   Ingestion Scripts
        │
        v
   Cleaning + Normalization
        │
        v
   Entity Tagging + Priority Scoring
        │
        v
   Push Service → Agents / DB / Factor Generators
```

## News storage

News lives in MongoDB, one collection per vendor:

| vendor | market | collection | id prefix |
|---|---|---|---|
| Benzinga | US | `news_benzinga` | `bz_` |
| Tushare | CN | `news_tushare` | `ts_` |

Older installs keep every vendor in one shared collection (`ticker_news`),
which other services may also read. QFZ never modifies it: **Settings → News
storage** copies each vendor out of it (server side; re-running only
refreshes), shows documents, disk and index size per collection, and switches
QFZ between the shared collection and the vendor collections. ESP picks up a
change within 15 seconds and reads the vendor collections as one source
(results merged in time order, so limits and cursors behave as before). Once
switched, imports write to the vendor collection only.

The same page imports Benzinga news from a path on the server: a
`YYYY-MM.jsonl[.gz]` file, a folder of them, or a Benzinga `.zip` archive,
which is checked against its manifest's SHA-256 before loading.

All times are stored in UTC. Tushare announcements that carry only a date are
stored as midnight China time (16:00 UTC the day before).

**How much text an article has.** Every news document carries
`content_level`: `full` (the article text, `body_text`; Benzinga archive
deliveries), `summary` (a teaser, or a flash item's text, in `description`)
or `headline` (the title only, as in massive's Benzinga drop and Tushare
announcements), and `content_chars`, the length of that text. News events
return both; `/esp/news/search` and `/esp/events/query` take
`min_content: "summary" | "full"` to keep only articles with that much, and
the MCP tools `esp_search_news` and `esp_query_events` pass it through. The
full text is read with `/esp/news/{id}/body` (`esp_news_body`). Documents
loaded before content levels existed are judged from their text fields; set
the fields on them with `python -m qfinzero.update.loaders.news
--backfill-content`.

**Query performance.** ESP reads news in (`published_utc`, `_id`) order. The
vendor collections carry the indexes `(published_utc, _id, content_level,
title)`, `(tickers, published_utc, _id, content_level)` and `(content_level,
published_utc, _id)`, so a page stops
after its `limit` rows instead of sorting the whole window, and the content
and keyword filters are applied to index keys (only matching documents are
read from disk). Each collection is searched at once, for at most
`ESP_NEWS_SEARCH_MAX_MS` (20 s); one that runs out leaves a `warnings` entry.

## Quick Example

```bash
# Query recent news for a ticker
curl "http://127.0.0.1:<port>/news/query?ticker=AAPL&start=2025-01-01&end=2025-01-31"
```

## References

- [OpenAPI Specification](openapi.yaml)
- [Server Implementation](../../infra/esp/)
- [Client Library](../../clients/esp/)
- [Demos](../../demos/esp/)
