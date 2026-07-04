> **English** (below) · [中文](#中文文档) (在下方)

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

---

<a id="中文文档"></a>

# 中文文档

# ESP — 新闻推送流水线

一个灵活的流水线，用于采集、解析并将金融新闻事件广播到下游交易或建模系统。

## Server

- **语言**: Python
- **入口点**: 位于 `infra/esp/` 中的多个采集脚本

```bash
cd infra/esp
pip install -r requirements.txt
python massive_news.py
```

## 组件

### 采集脚本

| Script | 描述 |
|--------|-------------|
| `massive_news.py` | 从多个来源批量采集新闻 |
| `stockbench_news.py` | StockBench 专用新闻源 |
| `economic_events.py` | 经济日历事件 |
| `fomc_scraper.py` | FOMC 会议纪要与决议 |
| `nasdaq_earnings.py` | NASDAQ 财报公告 |

### 工具脚本 (`scripts/`)

| Script | 描述 |
|--------|-------------|
| `monitor_fetcher.py` | 监控正在运行的抓取任务 |
| `fetch_nasdaq_earnings.py` | 抓取 NASDAQ 财报数据 |
| `fetch_massive_news.py` | 批量新闻抓取编排器 |

### Client

| Module | 描述 |
|--------|-------------|
| `massive_client.py` | 用于查询已采集新闻的客户端 |

## API 概览

| Endpoint | Method | 描述 |
|----------|--------|-------------|
| `/health` | GET | 健康检查 |
| `/news/push` | POST | 将一条新闻推送给下游消费者 |
| `/news/query` | GET | 按股票代码、日期范围、来源查询已存储的新闻 |
| `/news/sources` | GET | 列出可用的新闻来源 |

## 数据流

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

## 快速示例

```bash
# Query recent news for a ticker
curl "http://127.0.0.1:<port>/news/query?ticker=AAPL&start=2025-01-01&end=2025-01-31"
```

## 参考资料

- [OpenAPI Specification](openapi.yaml)
- [Server Implementation](../../infra/esp/)
- [Client Library](../../clients/esp/)
- [Demos](../../demos/esp/)
