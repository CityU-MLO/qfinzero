# Data Platform Backend Enhancement Design

> **Date**: 2026-02-18
> **Scope**: Backend API only (no frontend — Next.js + shadcn/ui planned separately)
> **Approach**: In-place enhancement of existing services (方案 A)

---

## Overview

Enhance three high-priority backend capabilities across UPQ, NPP, and the Dashboard:

1. **UPQ Data Freshness** — New Rust endpoint returning timestamps, counts, and partition info
2. **NPP Query Enhancement** — Keyword/publisher filtering, statistics API, export, calendar coverage
3. **Dashboard Freshness Integration** — Aggregate freshness data from all services + minimal sanity checks

Design principle: each service owns its freshness data; consumers (Dashboard, future Next.js frontend) aggregate and render.

---

## 1. Unified Freshness Schema

Every service exposes a standardized `/health/freshness` endpoint. Response follows a common structure so any frontend can render all sources with a single component.

### Standard Response Shape

```json
{
  "service": "<service_name>",
  "checked_at": "<ISO 8601 UTC>",
  "sources": {
    "<source_name>": {
      "latest_timestamp": "<ISO 8601 UTC | null>",
      "latest_date": "<YYYY-MM-DD | null>",
      "record_count": 0,
      "unique_keys": 0,
      "unique_key_label": "<tickers|tenors|publishers|...>",
      "partition_count": null,
      "missing_dates": [],
      "metadata": {}
    }
  }
}
```

Fields are optional (omit if not applicable). `latest_timestamp` is used for minute-level data; `latest_date` for daily data.

---

## 2. UPQ Data Freshness Endpoint (Rust)

### Endpoint

```
GET /health/freshness
```

### Implementation

Storage layout (Hive-partitioned Parquet):
```
{STORAGE_ROOT}/stock_minute/trade_date=YYYY-MM-DD/*.parquet
{STORAGE_ROOT}/stock_daily/trade_date=YYYY-MM-DD/*.parquet
{STORAGE_ROOT}/option_minute/trade_date=YYYY-MM-DD/*.parquet
{STORAGE_ROOT}/option_day/trade_date=YYYY-MM-DD/*.parquet
{STORAGE_ROOT}/rates/rates.parquet
```

Steps per data source:
1. Scan partition directory names → extract max `trade_date` (filesystem only, no Parquet read)
2. On the latest partition, run DuckDB queries:
   - `MAX(window_start)` → `latest_timestamp` (minute data only)
   - `COUNT(DISTINCT ticker)` → `unique_keys`
   - `COUNT(*)` → `record_count`
3. Count total partition directories → `partition_count`
4. For rates: query `rates.parquet` for `MAX(date)` and `COUNT(DISTINCT tenor)`

All queries run via `spawn_blocking` to avoid blocking the async runtime. No caching needed (low call frequency).

### Response Example

```json
{
  "service": "upq",
  "checked_at": "2025-01-15T21:00:00Z",
  "sources": {
    "stock_minute": {
      "latest_timestamp": "2025-01-15T20:59:00Z",
      "latest_date": "2025-01-15",
      "record_count": 392000,
      "unique_keys": 1003,
      "unique_key_label": "tickers",
      "partition_count": 252
    },
    "stock_daily": {
      "latest_date": "2025-01-15",
      "record_count": 1003,
      "unique_keys": 1003,
      "unique_key_label": "tickers",
      "partition_count": 252
    },
    "option_minute": {
      "latest_timestamp": "2025-01-15T20:59:00Z",
      "latest_date": "2025-01-15",
      "record_count": 2500000,
      "unique_keys": 8500,
      "unique_key_label": "tickers",
      "partition_count": 252
    },
    "option_day": {
      "latest_date": "2025-01-15",
      "record_count": 8500,
      "unique_keys": 8500,
      "unique_key_label": "tickers",
      "partition_count": 252
    },
    "rates": {
      "latest_date": "2025-01-15",
      "unique_keys": 7,
      "unique_key_label": "tenors"
    }
  }
}
```

### Files Changed

- `infra/upq/crates/upq-service/src/app.rs` — New handler + route
- `clients/upq/client.py` — New `freshness()` method

---

## 3. NPP Query Enhancement

### 3.1 News Search with Keyword + Publisher Filtering

**New endpoint**: `POST /npp/news/search`

```json
// Request
{
  "tickers": ["AAPL"],
  "start_utc": "2025-01-01T00:00:00Z",
  "end_utc": "2025-01-03T23:59:59Z",
  "keyword": "earnings",
  "publisher": "Reuters",
  "limit": 50,
  "cursor": null
}

// Response: same PaginatedResponse as /npp/events/query
```

MongoDB query construction:
- `keyword` → `{"title": {"$regex": keyword, "$options": "i"}}`
- `publisher` → `{"publisher.name": {"$regex": publisher, "$options": "i"}}`
- Combined with existing time range and ticker filters

### 3.2 News Statistics API

**New endpoint**: `GET /npp/news/stats?days=7`

```json
{
  "total_count": 85000,
  "date_range": {
    "earliest": "2024-01-01T00:00:00Z",
    "latest": "2025-01-15T10:30:00Z"
  },
  "daily_counts": [
    {"date": "2025-01-15", "count": 320},
    {"date": "2025-01-14", "count": 285}
  ],
  "top_tickers": [
    {"ticker": "AAPL", "count": 1200},
    {"ticker": "TSLA", "count": 980}
  ],
  "top_publishers": [
    {"publisher": "Reuters", "count": 5000}
  ],
  "duplicate_stats": {
    "by_url": {"total": 85000, "unique": 83000, "duplicate_rate": 0.024},
    "by_title": {"total": 85000, "unique": 82000, "duplicate_rate": 0.035}
  }
}
```

Implementation: MongoDB aggregation pipelines — `$group` by date/ticker/publisher + duplicate detection via `$group` by url/title.

### 3.3 Export Endpoints

**New endpoints**:
```
GET /npp/news/export?tickers=AAPL&start=2025-01-01&end=2025-01-03&format=jsonl
GET /npp/news/export?tickers=AAPL&start=2025-01-01&end=2025-01-03&format=csv
GET /npp/calendar/earnings/export?start=2025-01-01&end=2025-01-31&format=csv
GET /npp/calendar/economic/export?start=2025-01-01&end=2025-01-31&format=csv
```

Returns `StreamingResponse` with appropriate `Content-Type` and `Content-Disposition` headers.
- JSONL: one JSON object per line
- CSV: header row + data rows

Hard limit: 10,000 records per export request. Returns 400 if exceeded.

### 3.4 Calendar Coverage Statistics

**New endpoint**: `GET /npp/calendar/coverage`

```json
{
  "earnings": {
    "date_range": {"start": "2024-06-01", "end": "2025-03-15"},
    "total_records": 12000,
    "daily_counts": [{"date": "2025-01-15", "count": 45}],
    "missing_dates": ["2025-01-20"],
    "by_importance": {"HIGH": 3000, "MEDIUM": 5000, "LOW": 4000}
  },
  "econ_events": {
    "date_range": {"start": "2024-01-01", "end": "2025-01-15"},
    "total_records": 5000,
    "daily_counts": [{"date": "2025-01-15", "count": 12}],
    "missing_dates": [],
    "by_country": {"US": 3000, "EU": 1200},
    "by_type_top10": [
      {"event_type": "Interest Rate Decision", "count": 120}
    ]
  }
}
```

Missing date detection: compare against US trading calendar (exclude weekends + federal holidays).

### 3.5 NPP Freshness Endpoint

**New endpoint**: `GET /npp/health/freshness`

Extends existing `/npp/health` data_freshness into the standardized schema. Includes `daily_counts`, `top_tickers`, and `duplicate_rate` from the stats pipeline.

### Files Changed

```
infra/npp/routes/news.py            # New POST /npp/news/search
infra/npp/routes/stats.py           # New file: GET /npp/news/stats
infra/npp/routes/export.py          # New file: export endpoints
infra/npp/routes/calendar.py        # New GET /npp/calendar/coverage
infra/npp/routes/health.py          # New GET /npp/health/freshness
infra/npp/services/data_sources.py  # MongoNewsSource: keyword/publisher query support
infra/npp/models.py                 # New request/response models
infra/npp/main.py                   # Register new routers
clients/npp/client.py               # New methods: search, stats, export, coverage, freshness
```

---

## 4. Dashboard Freshness Integration

### `/api/status` Enhancement

Add freshness data to the existing status response:

```json
{
  "services": {
    "pmb": {"status": "up", "metrics": {...}},
    "npp": {"status": "up", "metrics": {...}},
    "upq": {"status": "up", "metrics": {...}}
  },
  "freshness": {
    "upq": {"sources": {"stock_minute": {...}, ...}},
    "npp": {"sources": {"news": {...}, "earnings": {...}, ...}}
  }
}
```

Dashboard fetches each service's `/health/freshness` endpoint in parallel (with timeout fallback). The existing HTML page adds a "Data Freshness" section below service cards showing latest timestamps.

### Files Changed

```
infra/dashboard/main.py    # Fetch freshness, add to /api/status, render in HTML
infra/dashboard/config.py  # Add freshness endpoint URLs to service config
```

---

## 5. NPP Sanity Check API (Minimal)

**New endpoint**: `GET /npp/admin/sanity`

Runs a set of predefined data quality checks against MongoDB and SQLite:

| Check | Description | Source |
|-------|-------------|--------|
| `future_timestamps` | News with `published_utc` in the future | MongoDB |
| `duplicate_urls` | Duplicate `article_url` values | MongoDB |
| `invalid_tickers` | Empty or malformed ticker arrays | MongoDB |
| `missing_trading_days` | Trading days with zero earnings/events | SQLite |

```json
{
  "checked_at": "2025-01-15T21:00:00Z",
  "checks": [
    {
      "name": "future_timestamps",
      "description": "News with published_utc in the future",
      "status": "pass",
      "count": 0,
      "samples": []
    }
  ],
  "summary": {
    "total": 4,
    "pass": 2,
    "warn": 1,
    "fail": 1
  }
}
```

Status thresholds: `count == 0` → pass, `count <= 10` → warn, `count > 10` → fail.

### Files Changed

```
infra/npp/routes/admin.py   # New file: GET /npp/admin/sanity
infra/npp/main.py           # Register admin router
```

---

## Out of Scope (for this iteration)

- Next.js + shadcn/ui frontend (separate branch/session)
- UPQ sanity checks (price anomaly detection in Rust)
- PMB freshness (not applicable — no persistent market data)
- ETL task monitoring (low priority, module 6)
- Service dependency graph
- Database connection status display

---

## Client Library Updates Summary

| Client | New Methods |
|--------|------------|
| `clients/upq/client.py` | `freshness()` |
| `clients/npp/client.py` | `search_news()`, `news_stats()`, `export_news()`, `export_earnings()`, `export_economic()`, `calendar_coverage()`, `freshness()`, `sanity_check()` |
