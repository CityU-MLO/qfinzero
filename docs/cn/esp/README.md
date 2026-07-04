> English: [../../en/esp/README.md](../../en/esp/README.md)

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
