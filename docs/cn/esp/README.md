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

## 新闻存储

新闻存放在 MongoDB，每个数据商一个集合：

| 数据商 | 市场 | 集合 | id 前缀 |
|---|---|---|---|
| Benzinga | 美股 | `news_benzinga` | `bz_` |
| Tushare | A 股 | `news_tushare` | `ts_` |

旧的安装把所有数据商放在同一个共享集合（`ticker_news`）里，其他服务也可能读取它。
QFZ 不会修改它：**设置 → 新闻存储** 把各数据商的数据从中复制出来（在 MongoDB
服务器端执行，重复执行只会刷新），显示每个集合的文档数、磁盘和索引大小，并在共享集合
与数据商集合之间切换 QFZ 的读取来源。ESP 在 15 秒内生效，把各数据商集合当作一个来源读取
（结果按时间合并，分页和游标与之前一致）。切换之后，导入只写入数据商集合。

同一页面也可以从服务器上的路径导入 Benzinga 新闻：`YYYY-MM.jsonl[.gz]` 文件、包含这些
文件的文件夹，或 Benzinga `.zip` 压缩包（加载前对照清单校验 SHA-256）。

所有时间都以 UTC 存储。只有日期的 Tushare 公告存为北京时间午夜（前一天 16:00 UTC）。

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
