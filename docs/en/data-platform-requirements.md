> 中文: [../cn/data-platform-requirements.md](../cn/data-platform-requirements.md)

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
