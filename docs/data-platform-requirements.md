> **中文** (below) · [English](#english-version) (在下方)

# QFinZero 数据平台监控需求清单

> **文档用途**: 追踪数据平台监控、运维和数据浏览功能的开发进度
> **最后更新**: 2026-02-19
> **状态**: 进行中 🚧

---

## 📊 总体进度概览

| 功能模块 | 完成度 | 优先级 | 状态 |
|---------|-------|-------|------|
| 1. 组件状态页 (Health & Status) | 90% | 🔴 高 | ✅ 基础实现 + Freshness集成 |
| 2. 数据新鲜度与覆盖 | 90% | 🔴 高 | ✅ UPQ/ESP Freshness端点完成 |
| 3. MongoDB内容浏览器 (News) | 80% | 🟡 中 | ✅ Search/Stats/Export API完成 |
| 4. SQLite内容浏览器 (Calendar) | 80% | 🟡 中 | ✅ Coverage/Export API完成 |
| 5. 数据一致性检查 | 80% | 🟡 中 | ✅ Sanity Check API完成 |
| 6. 日志与抓取状态 | 20% | 🟢 低 | ❌ 未实现 |

**图例**: ✅ 完成 | 🚧 进行中 | ⚠️ 部分完成 | ❌ 未开始

---

## 1️⃣ 组件状态页 (Health & Status)

### 目标
对 UPQ / ESP / PMB + DB（Mongo/SQLite）做统一状态卡片：

- ✅ health check（/health 或 ping）
- ✅ 端口 / base url
- ⚠️ 当前版本（git commit 或 build time）
- ✅ uptime
- ✅ 最近 5min 请求数、错误数
- ⚠️ 最近一次数据更新时间
- 输出: Running / Down / Stale（数据陈旧）

### 当前实现状态

#### ✅ 已实现

**Health Check 端点**:
- **UPQ** (Rust): `GET /health` → `{"status": "ok"}`
- **ESP** (Python): `GET /esp/health` → 返回服务状态 + 数据新鲜度
- **PMB** (Python): `GET /v1/health` → 返回服务状态

**Dashboard 监控** (`infra/dashboard/main.py`):
- 实时状态卡片（PMB/ESP/UPQ）
- Uptime显示（格式: Xh Ym）
- 总请求数 / 总错误数 / 活跃请求数
- 端点级延迟统计（p50/p95/p99/RPM）
- 自动刷新（5秒间隔）
- 暗色主题UI

**Metrics 中间件** (`qfinzero/metrics.py`):
- 自动追踪所有FastAPI服务端点
- `_stats` 端点返回详细指标
- 延迟百分位统计（p50/p95/p99）
- 最近60秒RPM计算

**Dashboard Freshness集成** (`infra/dashboard/main.py`):
- ESP和UPQ的freshness数据自动拉取并展示
- Data Freshness表格: Source / Latest / Records / Keys
- 每5秒自动刷新freshness信息

#### ⚠️ 部分实现

| 需求 | 当前状态 | 缺失说明 |
|-----|---------|---------|
| 版本信息 | 仅ESP返回硬编码版本 | UPQ/PMB未返回，无git commit信息 |
| Stale状态 | 后端返回时间戳 | 前端需实现阈值判断和警告展示 |

#### ❌ 未实现

- 数据库连接状态显示
- 服务依赖关系图

### 相关文件

```
infra/dashboard/main.py          # Dashboard服务
qfinzero/metrics.py              # FastAPI metrics中间件
infra/esp/routes/health.py       # ESP health端点
infra/upq/crates/upq-service/src/app.rs  # UPQ health端点
infra/pmb/routes/health.py       # PMB health端点
```

---

## 2️⃣ 数据新鲜度与覆盖 (Data Freshness & Coverage)

### 2.1 UPQ (价格数据)

#### 需求
- 最新一分钟数据时间戳（按 ticker 或全局）
- 日线最新日期
- 缺失检测：某段时间 missing bars / missing trading days
- 数据量统计：bars 数、tickers 数、文件/分区数

#### 当前实现状态

**✅ 已实现**

`GET /health/freshness` 端点已添加 (Rust/Axum):
- 扫描4种Parquet分区数据集 (stock_minute, stock_daily, option_minute, option_day)
- 返回统一Freshness Schema: service, checked_at, sources
- 每个source包含: latest_date, latest_timestamp, record_count, unique_keys, unique_key_label, partition_count
- rates数据源: 读取CSV返回最新日期、record_count、tenor数量
- 26个API contract测试全部通过

**实现文件**:
- `infra/upq/crates/upq-service/src/app.rs` — `health_freshness` handler + `build_freshness_response`
- `infra/upq/crates/upq-service/tests/api_contract_tests.rs` — 3个freshness测试
- `clients/upq/client.py` — `freshness()` 客户端方法
- `docs/upq/openapi.yaml` — OpenAPI spec已更新

---

### 2.2 ESP (新闻数据)

#### 需求
- 最新 published_utc
- 每天新闻条数折线（用于发现抓取挂了）
- ticker 覆盖统计（Top tickers by count）
- 去重/重复率（同 url / 同标题的重复）

#### 当前实现状态

**✅ 已实现**

1. `GET /esp/health/freshness` — 统一Freshness Schema端点
   - news: latest_timestamp, record_count, unique_keys (tickers), unique_key_label
   - earnings: latest_date, latest_timestamp, record_count, unique_keys (tickers)
   - econ_events: latest_timestamp, record_count, unique_keys (event_types)

2. `GET /esp/news/stats` — 每日新闻统计
   - 按天统计新闻数量 (daily_counts)
   - Top tickers (前20), Top publishers (前10)
   - 去重率统计 (by_url, by_title)
   - 支持days参数 (1-90天回溯)

**实现文件**:
- `infra/esp/routes/health.py` — freshness端点
- `infra/esp/routes/stats.py` — stats端点
- `docs/esp/openapi.yaml` — OpenAPI spec已更新

---

### 2.3 Calendar (earnings/economic)

#### 需求
- 最新日期覆盖到哪一天
- 按国家/事件类型数量统计
- 缺失日期列表（哪些 date 没抓到）

#### 当前实现状态

**✅ 已实现**

1. `GET /esp/health/freshness` — 统一Freshness Schema
   - earnings: latest_date, record_count, unique_keys (tickers)
   - econ_events: latest_timestamp, record_count, unique_keys (event_types)

2. `GET /esp/calendar/coverage?days=30` — 覆盖分析
   - 按天统计事件数量 (daily_counts)
   - 缺失交易日检测 (missing_dates，基于工作日推算)
   - 按重要性统计 (HIGH/MEDIUM/LOW)
   - 按事件类型TOP10统计 (by_type_top10)

3. `GET /esp/calendar/earnings/export` — 财报数据导出 (JSONL/CSV)
4. `GET /esp/calendar/economic/export` — 经济事件导出 (JSONL/CSV)

**实现文件**:
- `infra/esp/routes/calendar.py` — coverage端点 + export端点
- `infra/esp/routes/health.py` — freshness端点

#### ⚠️ 部分缺失

- Web UI覆盖热力图（需前端实现）

---

## 3️⃣ MongoDB内容浏览器 (News / Ticker News)

### 需求

**查询条件**:
- ticker（单个/多个）
- 时间范围（published_utc gte/lt）
- publisher
- keyword（title contains）

**结果表字段**:
- published_utc / title / publisher / tickers / rating(if any) / url

**详情展开**:
- 全字段 JSON
- 原始链接跳转

**导出支持**:
- JSONL / CSV（当前查询结果）

### 当前实现状态

**✅ API层完成**

#### ✅ 已实现API

1. **单条新闻查询**
   ```
   GET /esp/news/{news_id}/body
   ```

2. **新闻搜索** (新增)
   ```
   POST /esp/news/search

   Request:
   {
     "tickers": ["AAPL"],
     "start_utc": "2025-01-01T00:00:00Z",
     "end_utc": "2025-01-31T23:59:59Z",
     "keyword": "earnings",
     "publisher": "Reuters",
     "limit": 50,
     "cursor": "..."
   }
   ```
   - 支持ticker、时间范围、keyword(标题搜索)、publisher过滤
   - Cursor分页（base64编码的keyset pagination）
   - ReDoS防护（re.escape用户输入）

3. **新闻统计** (新增)
   ```
   GET /esp/news/stats?days=7
   ```
   - daily_counts (按天新闻数)
   - top_tickers (前20), top_publishers (前10)
   - duplicate_stats (by_url, by_title去重率)

4. **新闻导出** (新增)
   ```
   GET /esp/news/export?format=jsonl&tickers=AAPL&start=...&end=...
   ```
   - 支持JSONL和CSV格式
   - StreamingResponse流式传输
   - 最大10,000条限制

5. **通用事件查询**
   ```
   POST /esp/events/query
   ```

#### ⚠️ 缺失功能

- **Web UI界面**: 没有可视化浏览器（计划用Next.js + shadcn/ui实现）

### 相关文件

```
infra/esp/routes/news.py           # News搜索 + 单条查询
infra/esp/routes/stats.py          # 新闻统计
infra/esp/routes/export.py         # JSONL/CSV导出
infra/esp/routes/events.py         # 通用事件查询
infra/esp/services/data_sources.py # MongoNewsSource (含search_news方法)
infra/esp/models.py                # NewsSearchRequest模型
```

---

## 4️⃣ SQLite内容浏览器 (Calendar Tables)

### 需求

**功能**:
- 表列表：earnings / economic
- 常用过滤：date range, country, importance/impact, event type
- 表格展示 + 行详情 JSON
- "覆盖热力图"：按日期统计每天事件数量

### 当前实现状态

**✅ API层完成**

#### ✅ 已实现API

1. **Earnings查询**
   ```
   POST /esp/calendar/earnings
   ```

2. **Economic Events查询**
   ```
   POST /esp/calendar/econ
   ```

3. **覆盖分析** (新增)
   ```
   GET /esp/calendar/coverage?days=30
   ```
   - earnings: daily_counts, missing_dates, total_count
   - econ_events: daily_counts, missing_dates, by_importance, by_type_top10, total_count

4. **数据导出** (新增)
   ```
   GET /esp/calendar/earnings/export?format=csv&start=2025-01-01&end=2025-01-31
   GET /esp/calendar/economic/export?format=jsonl
   ```
   - 支持JSONL和CSV格式
   - 最大10,000条限制

5. **时间线视图**
   ```
   POST /esp/timeline
   ```

#### ⚠️ 缺失功能

- **Web UI**: 没有可视化表格界面（计划用Next.js + shadcn/ui实现）
- **表结构浏览**: 无法查看表结构和字段说明

### 相关文件

```
infra/esp/routes/calendar.py       # Calendar路由 + coverage端点
infra/esp/routes/export.py         # 导出路由
infra/esp/routes/timeline.py       # Timeline路由
infra/esp/services/data_sources.py # SQLiteEarningsSource, SQLiteEconEventsSource
```

---

## 5️⃣ 数据一致性检查 (Sanity Checks)

### 需求

**检查项**:
- 时间戳字段格式是否统一（UTC / timezone）
- 明显异常检测：
  - published_utc 在未来
  - 价格 high < low / volume < 0
  - ticker 规范化（大小写、空格、无效 ticker）
- 主键/唯一键冲突（Mongo url 去重，SQLite primary key）

**输出**:
- ✅ pass / ⚠️ warn / ❌ fail
- 错误样例（前 N 条）

### 当前实现状态

**✅ API已实现**

`GET /esp/admin/sanity` — 数据质量检查端点

**检查项**:
1. **future_timestamps**: 检测published_utc在未来的新闻
2. **duplicate_urls**: 检测重复URL的新闻（30天窗口扫描）
3. **invalid_tickers**: 检测无效ticker格式（非大写字母、含空格等）
4. **missing_trading_days**: 检测缺失的交易日（基于工作日推算）

**输出格式**:
```json
{
  "checked_at": "2025-01-15T10:00:00",
  "summary": {"pass": 2, "warn": 1, "fail": 1},
  "checks": [
    {
      "name": "future_timestamps",
      "status": "pass",
      "count": 0,
      "detail": "No news with future timestamps",
      "samples": []
    }
  ]
}
```

**安全措施**:
- duplicate_urls扫描限制在最近30天，防止全表扫描
- 标题截断至80字符

### 相关文件

```
infra/esp/routes/admin.py            # Sanity check端点
clients/esp/client.py                # sanity_check() 客户端方法
docs/esp/openapi.yaml                # OpenAPI spec
```

---

## 6️⃣ 日志与抓取状态 (ETL监控)

### 需求

- 最近一次任务运行时间、耗时、是否成功
- 本次新增条数（news / events / bars）
- 失败原因（http 403/429、解析错误）
- 简单重跑按钮

### 当前实现状态

**❌ 未实现**

目前没有ETL任务监控机制。

#### 建议实现

1. **任务日志表**（SQLite或MongoDB）:
   ```python
   {
     "task_name": "fetch_nasdaq_earnings",
     "start_time": "2025-01-15T10:00:00Z",
     "end_time": "2025-01-15T10:05:30Z",
     "duration_seconds": 330,
     "status": "success",  # or "failed"
     "records_inserted": 150,
     "records_updated": 20,
     "errors": [],
     "error_details": "..."
   }
   ```

2. **监控API**:
   ```
   GET /esp/admin/etl_status
   ```

---

## 📁 相关文件索引

### Dashboard & 监控
```
infra/dashboard/
├── main.py              # Dashboard服务主文件
├── config.py            # Dashboard配置
└── requirements.txt     # 依赖

qfinzero/metrics.py      # FastAPI metrics中间件
```

### Health端点
```
infra/esp/routes/health.py       # ESP health
infra/pmb/routes/health.py       # PMB health
infra/upq/crates/upq-service/src/app.rs  # UPQ health
```

### 数据服务
```
infra/esp/
├── main.py                        # ESP主服务
├── routes/
│   ├── news.py                    # News查询 + 搜索
│   ├── stats.py                   # 新闻统计 (新增)
│   ├── export.py                  # JSONL/CSV导出 (新增)
│   ├── admin.py                   # Sanity check (新增)
│   ├── events.py                  # 事件查询
│   ├── calendar.py                # Calendar查询 + coverage
│   ├── timeline.py                # 时间线
│   └── health.py                  # Health检查 + freshness
├── services/
│   ├── data_sources.py            # 数据源连接 (含search_news)
│   └── event_service.py           # 事件服务
└── models.py                      # 数据模型 (含NewsSearchRequest)

infra/upq/
├── crates/upq-service/src/app.rs  # UPQ服务
└── ...
```

### 客户端
```
clients/
├── esp/client.py          # ESP Python客户端
├── upq/client.py          # UPQ Python客户端
└── pmb/client.py          # PMB Python客户端
```

---

## 🎯 下一步开发建议

### 🔴 高优先级

1. **前端Dashboard (Next.js + shadcn/ui)**
   - News浏览器UI（搜索、过滤、导出）
   - Calendar浏览器UI（覆盖热力图）
   - Stale状态判断（前端根据时间戳计算阈值警告）
   - Sanity check结果展示

2. **版本信息增强**
   - UPQ/PMB返回git commit或build time
   - Dashboard展示版本信息

### 🟡 中优先级

3. **UPQ数据一致性检查**
   - 价格异常检测: high < low, volume < 0
   - 缺失交易日检测
   - 通过API或脚本实现

4. **Calendar缺失日期增强**
   - 对接真实交易日历（而非简单的工作日推算）

### 🟢 低优先级

5. **ETL任务监控**
   - 任务日志记录
   - 状态查询API
   - 重跑按钮

### ✅ 已完成（本轮）

- ~~UPQ `/health/freshness` 端点~~ ✅
- ~~Dashboard展示freshness数据~~ ✅
- ~~ESP新闻搜索/统计/导出API~~ ✅
- ~~ESP Calendar coverage + 导出~~ ✅
- ~~ESP Sanity check API~~ ✅
- ~~ESP/UPQ Freshness统一Schema~~ ✅
- ~~客户端方法更新~~ ✅
- ~~OpenAPI spec更新~~ ✅

---

## 📝 变更日志

| 日期 | 变更内容 | 作者 |
|-----|---------|------|
| 2026-02-19 | 后端API全面更新：UPQ freshness、ESP search/stats/export/coverage/sanity、Dashboard freshness集成、OpenAPI spec重写 | Atlas |
| 2025-02-18 | 初始版本：分析当前实现状态，记录需求清单 | Atlas |

---

## 🤝 使用说明

**给其他Agent的提示**:

1. 本文档位于 `docs/data-platform-requirements.md`
2. 开发新功能前请阅读相关文件索引
3. 更新实现状态后请同步更新本文档
4. 优先级标记: 🔴 高 / 🟡 中 / 🟢 低

**状态标记规范**:
- ✅ = 已完成
- 🚧 = 进行中
- ⚠️ = 部分完成
- ❌ = 未开始

---

*本文档由 Atlas 于 2025-02-18 创建，2026-02-19 更新*

---

<a id="english-version"></a>

# English Version

# QFinZero Data Platform Monitoring Requirements

> **Purpose**: Track development progress of data platform monitoring, operations, and data-browsing features
> **Last updated**: 2026-02-19
> **Status**: In progress 🚧

---

## 📊 Overall Progress Overview

| Feature Module | Completion | Priority | Status |
|---------|-------|-------|------|
| 1. Component Status Page (Health & Status) | 90% | 🔴 High | ✅ Basic implementation + Freshness integration |
| 2. Data Freshness & Coverage | 90% | 🔴 High | ✅ UPQ/ESP Freshness endpoints done |
| 3. MongoDB Content Browser (News) | 80% | 🟡 Medium | ✅ Search/Stats/Export API done |
| 4. SQLite Content Browser (Calendar) | 80% | 🟡 Medium | ✅ Coverage/Export API done |
| 5. Data Consistency Checks | 80% | 🟡 Medium | ✅ Sanity Check API done |
| 6. Logs & Fetch Status | 20% | 🟢 Low | ❌ Not implemented |

**Legend**: ✅ Done | 🚧 In progress | ⚠️ Partially done | ❌ Not started

---

## 1️⃣ Component Status Page (Health & Status)

### Goal
Provide unified status cards for UPQ / ESP / PMB + DB (Mongo/SQLite):

- ✅ health check (/health or ping)
- ✅ port / base url
- ⚠️ current version (git commit or build time)
- ✅ uptime
- ✅ requests / errors in the last 5min
- ⚠️ time of last data update
- Output: Running / Down / Stale (data is stale)

### Current Implementation Status

#### ✅ Implemented

**Health Check endpoints**:
- **UPQ** (Rust): `GET /health` → `{"status": "ok"}`
- **ESP** (Python): `GET /esp/health` → returns service status + data freshness
- **PMB** (Python): `GET /v1/health` → returns service status

**Dashboard monitoring** (`infra/dashboard/main.py`):
- Real-time status cards (PMB/ESP/UPQ)
- Uptime display (format: Xh Ym)
- Total requests / total errors / active requests
- Endpoint-level latency stats (p50/p95/p99/RPM)
- Auto refresh (5-second interval)
- Dark-theme UI

**Metrics middleware** (`qfinzero/metrics.py`):
- Automatically tracks all FastAPI service endpoints
- `_stats` endpoint returns detailed metrics
- Latency percentile stats (p50/p95/p99)
- RPM computed over the last 60 seconds

**Dashboard Freshness integration** (`infra/dashboard/main.py`):
- Freshness data for ESP and UPQ is automatically pulled and displayed
- Data Freshness table: Source / Latest / Records / Keys
- Freshness info auto-refreshes every 5 seconds

#### ⚠️ Partially Implemented

| Requirement | Current Status | Missing |
|-----|---------|---------|
| Version info | Only ESP returns a hard-coded version | UPQ/PMB do not return one; no git commit info |
| Stale status | Backend returns timestamps | Frontend needs to implement threshold logic and warning display |

#### ❌ Not Implemented

- Database connection status display
- Service dependency graph

### Related Files

```
infra/dashboard/main.py          # Dashboard服务
qfinzero/metrics.py              # FastAPI metrics中间件
infra/esp/routes/health.py       # ESP health端点
infra/upq/crates/upq-service/src/app.rs  # UPQ health端点
infra/pmb/routes/health.py       # PMB health端点
```

---

## 2️⃣ Data Freshness & Coverage

### 2.1 UPQ (Price Data)

#### Requirements
- Latest minute-data timestamp (per ticker or global)
- Latest daily-bar date
- Gap detection: missing bars / missing trading days over a time range
- Data volume stats: number of bars, number of tickers, number of files/partitions

#### Current Implementation Status

**✅ Implemented**

`GET /health/freshness` endpoint added (Rust/Axum):
- Scans 4 Parquet partitioned datasets (stock_minute, stock_daily, option_minute, option_day)
- Returns a unified Freshness Schema: service, checked_at, sources
- Each source contains: latest_date, latest_timestamp, record_count, unique_keys, unique_key_label, partition_count
- rates data source: reads CSV to return latest date, record_count, tenor count
- All 26 API contract tests pass

**Implementation files**:
- `infra/upq/crates/upq-service/src/app.rs` — `health_freshness` handler + `build_freshness_response`
- `infra/upq/crates/upq-service/tests/api_contract_tests.rs` — 3 freshness tests
- `clients/upq/client.py` — `freshness()` client method
- `docs/upq/openapi.yaml` — OpenAPI spec updated

---

### 2.2 ESP (News Data)

#### Requirements
- Latest published_utc
- Daily news-count line chart (to detect a stalled crawler)
- Ticker coverage stats (Top tickers by count)
- Dedup / duplicate rate (duplicates by same url / same title)

#### Current Implementation Status

**✅ Implemented**

1. `GET /esp/health/freshness` — unified Freshness Schema endpoint
   - news: latest_timestamp, record_count, unique_keys (tickers), unique_key_label
   - earnings: latest_date, latest_timestamp, record_count, unique_keys (tickers)
   - econ_events: latest_timestamp, record_count, unique_keys (event_types)

2. `GET /esp/news/stats` — daily news statistics
   - Daily news counts (daily_counts)
   - Top tickers (top 20), Top publishers (top 10)
   - Dedup rate stats (by_url, by_title)
   - Supports days parameter (1–90 day lookback)

**Implementation files**:
- `infra/esp/routes/health.py` — freshness endpoint
- `infra/esp/routes/stats.py` — stats endpoint
- `docs/esp/openapi.yaml` — OpenAPI spec updated

---

### 2.3 Calendar (earnings/economic)

#### Requirements
- What is the latest date covered
- Counts by country / event type
- List of missing dates (which dates were not fetched)

#### Current Implementation Status

**✅ Implemented**

1. `GET /esp/health/freshness` — unified Freshness Schema
   - earnings: latest_date, record_count, unique_keys (tickers)
   - econ_events: latest_timestamp, record_count, unique_keys (event_types)

2. `GET /esp/calendar/coverage?days=30` — coverage analysis
   - Daily event counts (daily_counts)
   - Missing trading-day detection (missing_dates, based on business-day inference)
   - Counts by importance (HIGH/MEDIUM/LOW)
   - Top 10 by event type (by_type_top10)

3. `GET /esp/calendar/earnings/export` — earnings data export (JSONL/CSV)
4. `GET /esp/calendar/economic/export` — economic event export (JSONL/CSV)

**Implementation files**:
- `infra/esp/routes/calendar.py` — coverage endpoint + export endpoint
- `infra/esp/routes/health.py` — freshness endpoint

#### ⚠️ Partially Missing

- Web UI coverage heatmap (requires frontend implementation)

---

## 3️⃣ MongoDB Content Browser (News / Ticker News)

### Requirements

**Query conditions**:
- ticker (single/multiple)
- Time range (published_utc gte/lt)
- publisher
- keyword (title contains)

**Result table fields**:
- published_utc / title / publisher / tickers / rating(if any) / url

**Detail expansion**:
- Full-field JSON
- Jump to original link

**Export support**:
- JSONL / CSV (current query result)

### Current Implementation Status

**✅ API layer done**

#### ✅ Implemented APIs

1. **Single news query**
   ```
   GET /esp/news/{news_id}/body
   ```

2. **News search** (new)
   ```
   POST /esp/news/search

   Request:
   {
     "tickers": ["AAPL"],
     "start_utc": "2025-01-01T00:00:00Z",
     "end_utc": "2025-01-31T23:59:59Z",
     "keyword": "earnings",
     "publisher": "Reuters",
     "limit": 50,
     "cursor": "..."
   }
   ```
   - Supports ticker, time range, keyword (title search), publisher filters
   - Cursor pagination (base64-encoded keyset pagination)
   - ReDoS protection (re.escape on user input)

3. **News statistics** (new)
   ```
   GET /esp/news/stats?days=7
   ```
   - daily_counts (news count per day)
   - top_tickers (top 20), top_publishers (top 10)
   - duplicate_stats (by_url, by_title dedup rate)

4. **News export** (new)
   ```
   GET /esp/news/export?format=jsonl&tickers=AAPL&start=...&end=...
   ```
   - Supports JSONL and CSV formats
   - StreamingResponse streaming
   - Max 10,000-record limit

5. **Generic event query**
   ```
   POST /esp/events/query
   ```

#### ⚠️ Missing Features

- **Web UI**: no visual browser (planned with Next.js + shadcn/ui)

### Related Files

```
infra/esp/routes/news.py           # News搜索 + 单条查询
infra/esp/routes/stats.py          # 新闻统计
infra/esp/routes/export.py         # JSONL/CSV导出
infra/esp/routes/events.py         # 通用事件查询
infra/esp/services/data_sources.py # MongoNewsSource (含search_news方法)
infra/esp/models.py                # NewsSearchRequest模型
```

---

## 4️⃣ SQLite Content Browser (Calendar Tables)

### Requirements

**Features**:
- Table list: earnings / economic
- Common filters: date range, country, importance/impact, event type
- Table display + row detail JSON
- "Coverage heatmap": event count per day by date

### Current Implementation Status

**✅ API layer done**

#### ✅ Implemented APIs

1. **Earnings query**
   ```
   POST /esp/calendar/earnings
   ```

2. **Economic Events query**
   ```
   POST /esp/calendar/econ
   ```

3. **Coverage analysis** (new)
   ```
   GET /esp/calendar/coverage?days=30
   ```
   - earnings: daily_counts, missing_dates, total_count
   - econ_events: daily_counts, missing_dates, by_importance, by_type_top10, total_count

4. **Data export** (new)
   ```
   GET /esp/calendar/earnings/export?format=csv&start=2025-01-01&end=2025-01-31
   GET /esp/calendar/economic/export?format=jsonl
   ```
   - Supports JSONL and CSV formats
   - Max 10,000-record limit

5. **Timeline view**
   ```
   POST /esp/timeline
   ```

#### ⚠️ Missing Features

- **Web UI**: no visual table interface (planned with Next.js + shadcn/ui)
- **Table schema browsing**: cannot view table schema and field descriptions

### Related Files

```
infra/esp/routes/calendar.py       # Calendar路由 + coverage端点
infra/esp/routes/export.py         # 导出路由
infra/esp/routes/timeline.py       # Timeline路由
infra/esp/services/data_sources.py # SQLiteEarningsSource, SQLiteEconEventsSource
```

---

## 5️⃣ Data Consistency Checks (Sanity Checks)

### Requirements

**Check items**:
- Whether timestamp field formats are consistent (UTC / timezone)
- Obvious anomaly detection:
  - published_utc in the future
  - price high < low / volume < 0
  - ticker normalization (case, whitespace, invalid ticker)
- Primary/unique key conflicts (Mongo url dedup, SQLite primary key)

**Output**:
- ✅ pass / ⚠️ warn / ❌ fail
- Error samples (first N)

### Current Implementation Status

**✅ API implemented**

`GET /esp/admin/sanity` — data quality check endpoint

**Check items**:
1. **future_timestamps**: detect news with published_utc in the future
2. **duplicate_urls**: detect news with duplicate URLs (30-day window scan)
3. **invalid_tickers**: detect invalid ticker formats (non-uppercase letters, containing whitespace, etc.)
4. **missing_trading_days**: detect missing trading days (based on business-day inference)

**Output format**:
```json
{
  "checked_at": "2025-01-15T10:00:00",
  "summary": {"pass": 2, "warn": 1, "fail": 1},
  "checks": [
    {
      "name": "future_timestamps",
      "status": "pass",
      "count": 0,
      "detail": "No news with future timestamps",
      "samples": []
    }
  ]
}
```

**Safeguards**:
- duplicate_urls scan limited to the last 30 days to prevent a full-table scan
- Titles truncated to 80 characters

### Related Files

```
infra/esp/routes/admin.py            # Sanity check端点
clients/esp/client.py                # sanity_check() 客户端方法
docs/esp/openapi.yaml                # OpenAPI spec
```

---

## 6️⃣ Logs & Fetch Status (ETL Monitoring)

### Requirements

- Last task run time, duration, and whether it succeeded
- Records added this run (news / events / bars)
- Failure reason (http 403/429, parse error)
- Simple rerun button

### Current Implementation Status

**❌ Not Implemented**

There is currently no ETL task monitoring mechanism.

#### Suggested Implementation

1. **Task log table** (SQLite or MongoDB):
   ```python
   {
     "task_name": "fetch_nasdaq_earnings",
     "start_time": "2025-01-15T10:00:00Z",
     "end_time": "2025-01-15T10:05:30Z",
     "duration_seconds": 330,
     "status": "success",  # or "failed"
     "records_inserted": 150,
     "records_updated": 20,
     "errors": [],
     "error_details": "..."
   }
   ```

2. **Monitoring API**:
   ```
   GET /esp/admin/etl_status
   ```

---

## 📁 Related File Index

### Dashboard & Monitoring
```
infra/dashboard/
├── main.py              # Dashboard服务主文件
├── config.py            # Dashboard配置
└── requirements.txt     # 依赖

qfinzero/metrics.py      # FastAPI metrics中间件
```

### Health Endpoints
```
infra/esp/routes/health.py       # ESP health
infra/pmb/routes/health.py       # PMB health
infra/upq/crates/upq-service/src/app.rs  # UPQ health
```

### Data Services
```
infra/esp/
├── main.py                        # ESP主服务
├── routes/
│   ├── news.py                    # News查询 + 搜索
│   ├── stats.py                   # 新闻统计 (新增)
│   ├── export.py                  # JSONL/CSV导出 (新增)
│   ├── admin.py                   # Sanity check (新增)
│   ├── events.py                  # 事件查询
│   ├── calendar.py                # Calendar查询 + coverage
│   ├── timeline.py                # 时间线
│   └── health.py                  # Health检查 + freshness
├── services/
│   ├── data_sources.py            # 数据源连接 (含search_news)
│   └── event_service.py           # 事件服务
└── models.py                      # 数据模型 (含NewsSearchRequest)

infra/upq/
├── crates/upq-service/src/app.rs  # UPQ服务
└── ...
```

### Clients
```
clients/
├── esp/client.py          # ESP Python客户端
├── upq/client.py          # UPQ Python客户端
└── pmb/client.py          # PMB Python客户端
```

---

## 🎯 Next Development Suggestions

### 🔴 High Priority

1. **Frontend Dashboard (Next.js + shadcn/ui)**
   - News browser UI (search, filter, export)
   - Calendar browser UI (coverage heatmap)
   - Stale status logic (frontend computes threshold warnings from timestamps)
   - Sanity check result display

2. **Version info enhancement**
   - UPQ/PMB return git commit or build time
   - Dashboard displays version info

### 🟡 Medium Priority

3. **UPQ data consistency checks**
   - Price anomaly detection: high < low, volume < 0
   - Missing trading-day detection
   - Implement via API or script

4. **Calendar missing-date enhancement**
   - Integrate a real trading calendar (instead of simple business-day inference)

### 🟢 Low Priority

5. **ETL task monitoring**
   - Task log recording
   - Status query API
   - Rerun button

### ✅ Completed (this round)

- ~~UPQ `/health/freshness` endpoint~~ ✅
- ~~Dashboard displays freshness data~~ ✅
- ~~ESP news search/stats/export APIs~~ ✅
- ~~ESP Calendar coverage + export~~ ✅
- ~~ESP Sanity check API~~ ✅
- ~~ESP/UPQ Freshness unified Schema~~ ✅
- ~~Client method updates~~ ✅
- ~~OpenAPI spec updates~~ ✅

---

## 📝 Changelog

| Date | Change | Author |
|-----|---------|------|
| 2026-02-19 | Full backend API update: UPQ freshness, ESP search/stats/export/coverage/sanity, Dashboard freshness integration, OpenAPI spec rewrite | Atlas |
| 2025-02-18 | Initial version: analyzed current implementation status, recorded requirements | Atlas |

---

## 🤝 Usage Notes

**Tips for other agents**:

1. This document lives at `docs/data-platform-requirements.md`
2. Read the related file index before developing new features
3. After updating implementation status, please keep this document in sync
4. Priority markers: 🔴 High / 🟡 Medium / 🟢 Low

**Status marker conventions**:
- ✅ = Done
- 🚧 = In progress
- ⚠️ = Partially done
- ❌ = Not started

---

*This document was created by Atlas on 2025-02-18 and updated on 2026-02-19*
