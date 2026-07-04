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
