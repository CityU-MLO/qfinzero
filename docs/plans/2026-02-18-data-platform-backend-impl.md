# Data Platform Backend Enhancement — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add data freshness APIs to UPQ (Rust) and ESP (Python), enhance ESP with news search/stats/export/calendar coverage, integrate freshness into Dashboard, and add basic sanity checks.

**Architecture:** Each service owns its freshness endpoint (`/health/freshness`). ESP gets new route files for stats, export, and admin. Dashboard aggregates freshness from all services. All changes are in-place on existing services — no new services.

**Tech Stack:** Rust/Axum/DuckDB (UPQ), Python/FastAPI/MongoDB/SQLite (ESP), Python/FastAPI/httpx (Dashboard), pytest (Python tests), cargo test (Rust tests)

**Branch:** `feat/data-platform-backend` (already created, design doc committed)

---

## Task 1: UPQ — `/health/freshness` Endpoint (Rust)

**Files:**
- Modify: `infra/upq/crates/upq-service/src/app.rs:94-120` (add route + handler)
- Test: `infra/upq/crates/upq-service/tests/api_contract_tests.rs` (add freshness tests)

### Step 1: Write the failing test

Add to `infra/upq/crates/upq-service/tests/api_contract_tests.rs`:

```rust
#[tokio::test]
async fn freshness_endpoint_returns_sources_for_empty_storage() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/health/freshness")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    assert_eq!(payload.get("service"), Some(&Value::String("upq".to_string())));
    assert!(payload.get("checked_at").is_some());
    assert!(payload.get("sources").is_some());
    Ok(())
}

#[tokio::test]
async fn freshness_endpoint_detects_latest_partition_date() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;

    // Create two stock_minute partitions
    let p1 = tmp.path().join("stock_minute").join("trade_date=2025-01-06");
    let p2 = tmp.path().join("stock_minute").join("trade_date=2025-01-07");
    fs::create_dir_all(&p1)?;
    fs::create_dir_all(&p2)?;

    let conn = Connection::open_in_memory()?;
    for (dir, date) in [(&p1, "2025-01-06"), (&p2, "2025-01-07")] {
        let path = dir.join("sample.parquet");
        let sql = format!(
            "COPY (\
                SELECT 'AAPL' AS ticker, \
                    1736155800000000000::BIGINT AS window_start, \
                    100.0::DOUBLE AS open, 101.0::DOUBLE AS high, \
                    99.0::DOUBLE AS low, 100.5::DOUBLE AS close, \
                    1000::BIGINT AS volume, 10::BIGINT AS transactions, \
                    DATE '{date}' AS trade_date\
             ) TO '{}' (FORMAT PARQUET)",
            path.to_string_lossy().replace('\'', "''")
        );
        conn.execute_batch(&sql)?;
    }

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/health/freshness")
        .body(Body::empty())?;
    let response = unwrap_infallible(app.oneshot(request).await);

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let sources = payload.get("sources").unwrap();
    let sm = sources.get("stock_minute").unwrap();
    assert_eq!(sm.get("latest_date"), Some(&Value::String("2025-01-07".to_string())));
    assert!(sm.get("record_count").is_some());
    assert!(sm.get("unique_keys").is_some());
    assert!(sm.get("partition_count").unwrap().as_u64().unwrap() >= 2);
    Ok(())
}
```

### Step 2: Run test to verify it fails

Run: `cd infra/upq && cargo test --package upq-service freshness -- --nocapture`
Expected: FAIL — no route matches `/health/freshness`

### Step 3: Implement the freshness handler

In `infra/upq/crates/upq-service/src/app.rs`:

1. Add `.route("/health/freshness", get(health_freshness))` to the router in `build_router_with_storage_root` (line ~107).

2. Add a helper to scan partition directories and find the max date:

```rust
fn scan_latest_partition(dataset_dir: &Path) -> Option<String> {
    let entries = fs::read_dir(dataset_dir).ok()?;
    let mut max_date: Option<String> = None;
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if let Some(date) = name_str.strip_prefix("trade_date=") {
            if !has_any_parquet_file(&entry.path()) {
                continue;
            }
            match &max_date {
                Some(current) if date <= current.as_str() => {}
                _ => max_date = Some(date.to_string()),
            }
        }
    }
    max_date
}

fn count_partitions(dataset_dir: &Path) -> usize {
    let entries = match fs::read_dir(dataset_dir) {
        Ok(e) => e,
        Err(_) => return 0,
    };
    entries
        .flatten()
        .filter(|e| {
            e.file_name()
                .to_string_lossy()
                .starts_with("trade_date=")
                && has_any_parquet_file(&e.path())
        })
        .count()
}
```

3. Add the freshness query function that runs DuckDB on the latest partition:

```rust
fn query_partition_stats(
    dataset_dir: &Path,
    latest_date: &str,
    has_window_start: bool,
) -> Result<Value, ServiceError> {
    let partition_path = dataset_dir
        .join(format!("trade_date={latest_date}"))
        .join("*.parquet")
        .to_string_lossy()
        .to_string();

    let timestamp_select = if has_window_start {
        ", MAX(window_start) AS max_ts"
    } else {
        ""
    };

    let sql = format!(
        "SELECT COUNT(*) AS record_count, COUNT(DISTINCT ticker) AS unique_keys{timestamp_select} \
         FROM read_parquet('{path}')",
        path = sql_escape_literal(&partition_path),
    );

    with_thread_local_connection(|conn| {
        let mut stmt = conn.prepare(&sql)?;
        let mut rows = stmt.query([])?;
        if let Some(row) = rows.next()? {
            let record_count = row.get_ref(0).map(value_ref_to_json).unwrap_or(json!(0));
            let unique_keys = row.get_ref(1).map(value_ref_to_json).unwrap_or(json!(0));
            let mut result = json!({
                "latest_date": latest_date,
                "record_count": record_count,
                "unique_keys": unique_keys,
                "unique_key_label": "tickers",
            });
            if has_window_start {
                let max_ts = row.get_ref(2).map(value_ref_to_json).unwrap_or(Value::Null);
                result.as_object_mut().unwrap().insert("latest_timestamp".to_string(), max_ts);
            }
            Ok(result)
        } else {
            Ok(json!({"latest_date": latest_date}))
        }
    })
}
```

4. Add the rates freshness query:

```rust
fn query_rates_stats(rates_path: &Path) -> Result<Value, ServiceError> {
    if !rates_path.exists() {
        return Ok(Value::Null);
    }
    let path_str = rates_path.to_string_lossy().to_string();
    let sql = format!(
        "SELECT MAX(date) AS latest_date, \
         COUNT(DISTINCT (CASE WHEN yield_1_month IS NOT NULL THEN '1M' END, \
               CASE WHEN yield_3_month IS NOT NULL THEN '3M' END, \
               CASE WHEN yield_1_year IS NOT NULL THEN '1Y' END, \
               CASE WHEN yield_2_year IS NOT NULL THEN '2Y' END, \
               CASE WHEN yield_5_year IS NOT NULL THEN '5Y' END, \
               CASE WHEN yield_10_year IS NOT NULL THEN '10Y' END, \
               CASE WHEN yield_30_year IS NOT NULL THEN '30Y' END)) AS dummy \
         FROM read_parquet('{path}')",
        path = sql_escape_literal(&path_str),
    );
    // Simpler approach: just count the 7 known tenors
    let sql = format!(
        "SELECT MAX(date) AS latest_date FROM read_parquet('{path}')",
        path = sql_escape_literal(&path_str),
    );
    with_thread_local_connection(|conn| {
        let mut stmt = conn.prepare(&sql)?;
        let mut rows = stmt.query([])?;
        if let Some(row) = rows.next()? {
            let latest = row.get_ref(0).map(value_ref_to_json).unwrap_or(Value::Null);
            Ok(json!({
                "latest_date": latest,
                "unique_keys": 7,
                "unique_key_label": "tenors",
            }))
        } else {
            Ok(Value::Null)
        }
    })
}
```

5. Add the handler:

```rust
async fn health_freshness(State(state): State<AppState>) -> axum::response::Response {
    let storage = state.storage_root.clone();
    let result = tokio::task::spawn_blocking(move || -> Result<Value, ServiceError> {
        let mut sources = Map::new();

        let datasets = [
            ("stock_minute", "stock_minute", true),
            ("stock_daily", "stock_daily", false),
            ("option_minute", "option_minute", true),
            ("option_day", "option_day", false),
        ];

        for (key, dir_name, has_window_start) in datasets {
            let dataset_dir = storage.join(dir_name);
            if let Some(latest_date) = scan_latest_partition(&dataset_dir) {
                let partition_count = count_partitions(&dataset_dir);
                let mut stats = query_partition_stats(&dataset_dir, &latest_date, has_window_start)?;
                stats.as_object_mut().unwrap().insert(
                    "partition_count".to_string(),
                    json!(partition_count),
                );
                sources.insert(key.to_string(), stats);
            }
        }

        // Rates
        let rates_path = storage.join("rates").join("rates.parquet");
        if let Ok(rates) = query_rates_stats(&rates_path) {
            if !rates.is_null() {
                sources.insert("rates".to_string(), rates);
            }
        }

        Ok(json!({
            "service": "upq",
            "checked_at": chrono::Utc::now().to_rfc3339(),
            "sources": sources,
        }))
    })
    .await;

    match result {
        Ok(Ok(value)) => (StatusCode::OK, Json(value)).into_response(),
        Ok(Err(error)) => internal_error(error),
        Err(join_error) => internal_error(ServiceError::Join(join_error.to_string())),
    }
}
```

Note: Add `use serde_json::Map;` to imports if not already present. Also add `use chrono::Utc;` to imports.

### Step 4: Run tests to verify they pass

Run: `cd infra/upq && cargo test --package upq-service freshness -- --nocapture`
Expected: PASS

### Step 5: Run all existing tests to verify no regressions

Run: `cd infra/upq && cargo test --package upq-service`
Expected: All tests PASS

### Step 6: Commit

```bash
git add infra/upq/crates/upq-service/src/app.rs infra/upq/crates/upq-service/tests/api_contract_tests.rs
git commit -m "feat(upq): add /health/freshness endpoint with partition scanning"
```

---

## Task 2: UPQ Client — `freshness()` Method

**Files:**
- Modify: `clients/upq/client.py:72-73` (after health method)

### Step 1: Add `freshness()` method

In `clients/upq/client.py`, after the `health()` method (line 73):

```python
    def freshness(self) -> dict:
        """Data freshness — returns latest timestamps, record counts, and partition info per data source."""
        return self._get("/health/freshness")
```

### Step 2: Commit

```bash
git add clients/upq/client.py
git commit -m "feat(upq-client): add freshness() method"
```

---

## Task 3: ESP — News Search Endpoint with Keyword + Publisher Filtering

**Files:**
- Modify: `infra/esp/services/data_sources.py:168-203` (MongoNewsSource.query_window — add keyword/publisher support)
- Modify: `infra/esp/models.py` (add NewsSearchRequest model)
- Modify: `infra/esp/routes/news.py` (add POST /esp/news/search)
- Modify: `infra/esp/main.py` (no change needed — news router already registered)

### Step 1: Add the `NewsSearchRequest` model

In `infra/esp/models.py`, after the `EarningsCalendarRequest` class (line ~113):

```python
class NewsSearchRequest(BaseModel):
    tickers: Optional[list[str]] = None
    start_utc: Optional[str] = None
    end_utc: Optional[str] = None
    keyword: Optional[str] = None
    publisher: Optional[str] = None
    limit: int = 50
    cursor: Optional[str] = None
    now_utc: Optional[str] = None
```

### Step 2: Add `search_news()` method to `MongoNewsSource`

In `infra/esp/services/data_sources.py`, add a new method to `MongoNewsSource` after `query_window` (line ~203):

```python
    async def search_news(
        self,
        start_utc: datetime,
        end_utc: datetime,
        tickers: Optional[list[str]],
        keyword: Optional[str],
        publisher: Optional[str],
        limit: int,
        cursor: Optional[tuple[str, str]],
        now_utc: datetime,
    ) -> list[Event]:
        if not self.available:
            return []

        query: dict[str, Any] = {
            "published_utc": {"$gte": start_utc, "$lt": end_utc},
        }
        if tickers:
            query["tickers"] = {"$in": [t.upper() for t in tickers]}
        if keyword:
            query["title"] = {"$regex": keyword, "$options": "i"}
        if publisher:
            query["publisher.name"] = {"$regex": publisher, "$options": "i"}
        if cursor:
            cursor_time = _parse_utc(cursor[0])
            cursor_id = cursor[1].removeprefix("news_")
            query["$or"] = [
                {"published_utc": {"$gt": cursor_time}},
                {"published_utc": cursor_time, "_id": {"$gt": cursor_id}},
            ]
            query["published_utc"] = {"$gte": start_utc, "$lt": end_utc}

        docs = (
            self._coll.find(query)
            .sort([("published_utc", 1), ("_id", 1)])
            .limit(limit)
        )
        events = []
        async for doc in docs:
            events.append(self._to_event(doc, now_utc))
        return events
```

### Step 3: Add the route

In `infra/esp/routes/news.py`, add:

```python
from models import NewsSearchRequest, PaginatedResponse
from datetime import datetime, timezone, timedelta
import base64, json


def _decode_cursor(cursor_str: str) -> tuple[str, str]:
    raw = base64.b64decode(cursor_str)
    return tuple(json.loads(raw))


def _encode_cursor(time_utc: str, event_id: str) -> str:
    return base64.b64encode(json.dumps([time_utc, event_id]).encode()).decode()


@router.post("/esp/news/search")
async def search_news(req: NewsSearchRequest, request: Request):
    ds = request.app.state.data_sources
    now = datetime.fromisoformat(req.now_utc) if req.now_utc else datetime.now(timezone.utc)

    start = datetime.fromisoformat(req.start_utc) if req.start_utc else now - timedelta(days=7)
    end = datetime.fromisoformat(req.end_utc) if req.end_utc else now

    cursor = _decode_cursor(req.cursor) if req.cursor else None
    fetch_limit = req.limit + 1

    events = await ds.news.search_news(
        start_utc=start,
        end_utc=end,
        tickers=req.tickers,
        keyword=req.keyword,
        publisher=req.publisher,
        limit=fetch_limit,
        cursor=cursor,
        now_utc=now,
    )

    next_cursor = None
    if len(events) > req.limit:
        events = events[:req.limit]
        last = events[-1]
        next_cursor = _encode_cursor(last.time_utc, last.event_id)

    return PaginatedResponse(
        server_time_utc=now.isoformat(),
        events=events,
        next_cursor=next_cursor,
    ).model_dump()
```

### Step 4: Run ESP locally and test with curl

Run: `cd infra/esp && python main.py` (in another terminal)

```bash
curl -X POST http://127.0.0.1:19702/esp/news/search \
  -H "Content-Type: application/json" \
  -d '{"keyword":"earnings","limit":5}'
```

Expected: 200 with paginated news results (or empty if MongoDB is not available)

### Step 5: Commit

```bash
git add infra/esp/models.py infra/esp/services/data_sources.py infra/esp/routes/news.py
git commit -m "feat(esp): add POST /esp/news/search with keyword and publisher filtering"
```

---

## Task 4: ESP — News Statistics API

**Files:**
- Create: `infra/esp/routes/stats.py`
- Modify: `infra/esp/main.py:29,91-96` (import and register router)

### Step 1: Create the stats route

Create `infra/esp/routes/stats.py`:

```python
from fastapi import APIRouter, Request, Query

router = APIRouter(tags=["stats"])


@router.get("/esp/news/stats")
async def news_stats(request: Request, days: int = Query(default=7, ge=1, le=90)):
    ds = request.app.state.data_sources
    if not ds.news.available:
        return {"error": "MongoDB unavailable", "total_count": 0}

    coll = ds.news._coll
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # Total count
    total_count = await coll.count_documents({})

    # Date range
    earliest_doc = await coll.find_one(sort=[("published_utc", 1)])
    latest_doc = await coll.find_one(sort=[("published_utc", -1)])
    earliest = earliest_doc["published_utc"].isoformat() if earliest_doc and earliest_doc.get("published_utc") else None
    latest = latest_doc["published_utc"].isoformat() if latest_doc and latest_doc.get("published_utc") else None

    # Daily counts (last N days)
    daily_pipeline = [
        {"$match": {"published_utc": {"$gte": since}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$published_utc"}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": -1}},
    ]
    daily_counts = []
    async for doc in coll.aggregate(daily_pipeline):
        daily_counts.append({"date": doc["_id"], "count": doc["count"]})

    # Top tickers
    ticker_pipeline = [
        {"$unwind": "$tickers"},
        {"$group": {"_id": "$tickers", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    top_tickers = []
    async for doc in coll.aggregate(ticker_pipeline):
        top_tickers.append({"ticker": doc["_id"], "count": doc["count"]})

    # Top publishers
    publisher_pipeline = [
        {"$match": {"publisher.name": {"$exists": True}}},
        {"$group": {"_id": "$publisher.name", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    top_publishers = []
    async for doc in coll.aggregate(publisher_pipeline):
        top_publishers.append({"publisher": doc["_id"], "count": doc["count"]})

    # Duplicate stats
    url_dup_pipeline = [
        {"$group": {"_id": "$article_url", "count": {"$sum": 1}}},
        {"$group": {"_id": None, "total": {"$sum": "$count"}, "unique": {"$sum": 1}}},
    ]
    url_dup = await coll.aggregate(url_dup_pipeline).to_list(1)
    url_total = url_dup[0]["total"] if url_dup else total_count
    url_unique = url_dup[0]["unique"] if url_dup else total_count
    url_dup_rate = round(1 - url_unique / url_total, 4) if url_total > 0 else 0

    title_dup_pipeline = [
        {"$group": {"_id": "$title", "count": {"$sum": 1}}},
        {"$group": {"_id": None, "total": {"$sum": "$count"}, "unique": {"$sum": 1}}},
    ]
    title_dup = await coll.aggregate(title_dup_pipeline).to_list(1)
    title_total = title_dup[0]["total"] if title_dup else total_count
    title_unique = title_dup[0]["unique"] if title_dup else total_count
    title_dup_rate = round(1 - title_unique / title_total, 4) if title_total > 0 else 0

    return {
        "total_count": total_count,
        "date_range": {"earliest": earliest, "latest": latest},
        "daily_counts": daily_counts,
        "top_tickers": top_tickers,
        "top_publishers": top_publishers,
        "duplicate_stats": {
            "by_url": {"total": url_total, "unique": url_unique, "duplicate_rate": url_dup_rate},
            "by_title": {"total": title_total, "unique": title_unique, "duplicate_rate": title_dup_rate},
        },
    }
```

### Step 2: Register the router

In `infra/esp/main.py`, add import and registration:

```python
# In the imports section (line ~29):
from routes import health, events, triggers, calendar, news, timeline, stats

# In the router registration section (line ~96):
app.include_router(stats.router)
```

### Step 3: Verify

Run: `curl http://127.0.0.1:19702/esp/news/stats?days=7`
Expected: 200 with statistics JSON

### Step 4: Commit

```bash
git add infra/esp/routes/stats.py infra/esp/main.py
git commit -m "feat(esp): add GET /esp/news/stats with daily counts, top tickers, and duplicate detection"
```

---

## Task 5: ESP — Export Endpoints

**Files:**
- Create: `infra/esp/routes/export.py`
- Modify: `infra/esp/main.py` (register router)

### Step 1: Create the export route

Create `infra/esp/routes/export.py`:

```python
import csv
import io
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["export"])

EXPORT_LIMIT = 10_000


@router.get("/esp/news/export")
async def export_news(
    request: Request,
    format: str = Query(..., regex="^(jsonl|csv)$"),
    tickers: Optional[str] = Query(default=None),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
):
    ds = request.app.state.data_sources
    if not ds.news.available:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    now = datetime.now(timezone.utc)
    start_utc = datetime.fromisoformat(start) if start else now - timedelta(days=7)
    end_utc = datetime.fromisoformat(end) if end else now
    ticker_list = [t.strip().upper() for t in tickers.split(",")] if tickers else None

    coll = ds.news._coll
    query = {"published_utc": {"$gte": start_utc, "$lt": end_utc}}
    if ticker_list:
        query["tickers"] = {"$in": ticker_list}

    count = await coll.count_documents(query)
    if count > EXPORT_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Result set ({count}) exceeds export limit ({EXPORT_LIMIT}). Narrow your query.",
        )

    docs_cursor = coll.find(query).sort([("published_utc", 1)]).limit(EXPORT_LIMIT)

    if format == "jsonl":
        async def generate_jsonl():
            async for doc in docs_cursor:
                doc["_id"] = str(doc["_id"])
                if hasattr(doc.get("published_utc"), "isoformat"):
                    doc["published_utc"] = doc["published_utc"].isoformat()
                yield json.dumps(doc, default=str) + "\n"

        return StreamingResponse(
            generate_jsonl(),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=news_export.jsonl"},
        )
    else:
        fields = ["_id", "published_utc", "title", "article_url", "tickers", "author", "publisher"]

        async def generate_csv():
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

            async for doc in docs_cursor:
                doc["_id"] = str(doc["_id"])
                if hasattr(doc.get("published_utc"), "isoformat"):
                    doc["published_utc"] = doc["published_utc"].isoformat()
                doc["tickers"] = ",".join(doc.get("tickers") or [])
                pub = doc.get("publisher")
                doc["publisher"] = pub.get("name") if isinstance(pub, dict) else str(pub or "")
                writer.writerow(doc)
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)

        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=news_export.csv"},
        )


@router.get("/esp/calendar/earnings/export")
async def export_earnings(
    request: Request,
    format: str = Query(default="csv", regex="^(jsonl|csv)$"),
    start: str = Query(...),
    end: str = Query(...),
    ticker: Optional[str] = Query(default=None),
):
    ds = request.app.state.data_sources
    db = ds.earnings._db

    sql = "SELECT * FROM earnings WHERE date >= ? AND date <= ?"
    params = [start, end]
    if ticker:
        sql += " AND ticker = ?"
        params.append(ticker.upper())
    sql += " ORDER BY date, ticker LIMIT ?"
    params.append(EXPORT_LIMIT + 1)

    rows = []
    async with db.execute(sql, params) as cur:
        columns = [desc[0] for desc in cur.description] if cur.description else []
        async for row in cur:
            rows.append(dict(zip(columns, row)))

    if len(rows) > EXPORT_LIMIT:
        raise HTTPException(status_code=400, detail=f"Result exceeds {EXPORT_LIMIT} rows.")
    if not rows:
        raise HTTPException(status_code=404, detail="No data found for the given range.")

    if format == "jsonl":
        content = "\n".join(json.dumps(r, default=str) for r in rows) + "\n"
        return StreamingResponse(
            iter([content]),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=earnings_export.jsonl"},
        )
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=earnings_export.csv"},
        )


@router.get("/esp/calendar/economic/export")
async def export_economic(
    request: Request,
    format: str = Query(default="csv", regex="^(jsonl|csv)$"),
    start: str = Query(...),
    end: str = Query(...),
    country: Optional[str] = Query(default=None),
):
    ds = request.app.state.data_sources
    db = ds.econ._db

    sql = "SELECT * FROM econ_events WHERE date >= ? AND date <= ?"
    params = [start, end]
    if country:
        sql += " AND country = ?"
        params.append(country)
    sql += " ORDER BY date, gmt_time LIMIT ?"
    params.append(EXPORT_LIMIT + 1)

    rows = []
    async with db.execute(sql, params) as cur:
        columns = [desc[0] for desc in cur.description] if cur.description else []
        async for row in cur:
            rows.append(dict(zip(columns, row)))

    if len(rows) > EXPORT_LIMIT:
        raise HTTPException(status_code=400, detail=f"Result exceeds {EXPORT_LIMIT} rows.")
    if not rows:
        raise HTTPException(status_code=404, detail="No data found for the given range.")

    if format == "jsonl":
        content = "\n".join(json.dumps(r, default=str) for r in rows) + "\n"
        return StreamingResponse(
            iter([content]),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=economic_export.jsonl"},
        )
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=economic_export.csv"},
        )
```

### Step 2: Register the router

In `infra/esp/main.py`:

```python
from routes import health, events, triggers, calendar, news, timeline, stats, export

app.include_router(export.router)
```

### Step 3: Verify

```bash
curl "http://127.0.0.1:19702/esp/news/export?format=jsonl&start=2025-01-01T00:00:00Z&end=2025-01-03T00:00:00Z"
curl "http://127.0.0.1:19702/esp/calendar/earnings/export?start=2025-01-01&end=2025-01-31&format=csv"
```

### Step 4: Commit

```bash
git add infra/esp/routes/export.py infra/esp/main.py
git commit -m "feat(esp): add export endpoints for news, earnings, and economic events (JSONL/CSV)"
```

---

## Task 6: ESP — Calendar Coverage Statistics

**Files:**
- Modify: `infra/esp/routes/calendar.py` (add GET /esp/calendar/coverage)

### Step 1: Add the coverage endpoint

In `infra/esp/routes/calendar.py`, add:

```python
from fastapi import Query
from datetime import datetime, timedelta, date


def _us_trading_days(start_date: str, end_date: str) -> set[str]:
    """Generate set of weekday dates (excluding weekends). Not a full holiday calendar."""
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    days = set()
    current = start
    while current <= end:
        if current.weekday() < 5:  # Mon-Fri
            days.add(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


@router.get("/esp/calendar/coverage")
async def calendar_coverage(request: Request, days: int = Query(default=30, ge=1, le=365)):
    ds = request.app.state.data_sources
    result = {}

    # Earnings coverage
    earn_db = ds.earnings._db
    async with earn_db.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM earnings") as cur:
        row = await cur.fetchone()
        earn_start, earn_end, earn_total = row[0], row[1], row[2]

    earn_daily = []
    async with earn_db.execute(
        "SELECT date, COUNT(*) AS cnt FROM earnings GROUP BY date ORDER BY date DESC LIMIT ?",
        [days],
    ) as cur:
        async for row in cur:
            earn_daily.append({"date": row[0], "count": row[1]})

    earn_importance = {}
    async with earn_db.execute(
        "SELECT CASE WHEN importance >= 4 THEN 'HIGH' WHEN importance >= 2 THEN 'MEDIUM' ELSE 'LOW' END AS imp, COUNT(*) FROM earnings GROUP BY imp"
    ) as cur:
        async for row in cur:
            earn_importance[row[0]] = row[1]

    # Detect missing dates for earnings
    earn_missing = []
    if earn_start and earn_end:
        earn_dates_with_data = set()
        async with earn_db.execute("SELECT DISTINCT date FROM earnings") as cur:
            async for row in cur:
                earn_dates_with_data.add(row[0])
        trading_days = _us_trading_days(earn_start, earn_end)
        earn_missing = sorted(trading_days - earn_dates_with_data)[-days:]  # last N

    result["earnings"] = {
        "date_range": {"start": earn_start, "end": earn_end},
        "total_records": earn_total,
        "daily_counts": earn_daily,
        "missing_dates": earn_missing,
        "by_importance": earn_importance,
    }

    # Econ events coverage
    econ_db = ds.econ._db
    async with econ_db.execute(
        "SELECT MIN(date), MAX(date), COUNT(*) FROM econ_events WHERE country = 'United States'"
    ) as cur:
        row = await cur.fetchone()
        econ_start, econ_end, econ_total = row[0], row[1], row[2]

    econ_daily = []
    async with econ_db.execute(
        "SELECT date, COUNT(*) AS cnt FROM econ_events WHERE country = 'United States' GROUP BY date ORDER BY date DESC LIMIT ?",
        [days],
    ) as cur:
        async for row in cur:
            econ_daily.append({"date": row[0], "count": row[1]})

    econ_by_country = {}
    async with econ_db.execute(
        "SELECT country, COUNT(*) FROM econ_events GROUP BY country ORDER BY COUNT(*) DESC"
    ) as cur:
        async for row in cur:
            econ_by_country[row[0]] = row[1]

    econ_by_type = []
    async with econ_db.execute(
        "SELECT event_name, COUNT(*) AS cnt FROM econ_events WHERE country = 'United States' GROUP BY event_name ORDER BY cnt DESC LIMIT 10"
    ) as cur:
        async for row in cur:
            econ_by_type.append({"event_type": row[0], "count": row[1]})

    econ_missing = []
    if econ_start and econ_end:
        econ_dates_with_data = set()
        async with econ_db.execute(
            "SELECT DISTINCT date FROM econ_events WHERE country = 'United States'"
        ) as cur:
            async for row in cur:
                econ_dates_with_data.add(row[0])
        trading_days = _us_trading_days(econ_start, econ_end)
        econ_missing = sorted(trading_days - econ_dates_with_data)[-days:]

    result["econ_events"] = {
        "date_range": {"start": econ_start, "end": econ_end},
        "total_records": econ_total,
        "daily_counts": econ_daily,
        "missing_dates": econ_missing,
        "by_country": econ_by_country,
        "by_type_top10": econ_by_type,
    }

    return result
```

### Step 2: Verify

```bash
curl http://127.0.0.1:19702/esp/calendar/coverage?days=30
```

### Step 3: Commit

```bash
git add infra/esp/routes/calendar.py
git commit -m "feat(esp): add GET /esp/calendar/coverage with daily counts, missing dates, and breakdowns"
```

---

## Task 7: ESP — `/esp/health/freshness` Endpoint

**Files:**
- Modify: `infra/esp/routes/health.py`

### Step 1: Add the freshness endpoint

In `infra/esp/routes/health.py`:

```python
from datetime import datetime, timezone


@router.get("/esp/health/freshness")
async def health_freshness(request: Request):
    ds = request.app.state.data_sources
    now = datetime.now(timezone.utc)

    sources = {}

    # News (MongoDB)
    if ds.news.available:
        coll = ds.news._coll
        latest_doc = await coll.find_one(sort=[("published_utc", -1)])
        latest_ts = None
        if latest_doc and latest_doc.get("published_utc"):
            pub = latest_doc["published_utc"]
            latest_ts = pub.isoformat() if hasattr(pub, "isoformat") else str(pub)
        total = await coll.count_documents({})

        # Distinct tickers count
        ticker_count = len(await coll.distinct("tickers"))

        sources["news"] = {
            "latest_timestamp": latest_ts,
            "record_count": total,
            "unique_keys": ticker_count,
            "unique_key_label": "tickers",
        }

    # Earnings (SQLite)
    earn_db = ds.earnings._db
    async with earn_db.execute("SELECT MAX(last_updated), COUNT(*) FROM earnings") as cur:
        row = await cur.fetchone()
        if row and row[0]:
            sources["earnings"] = {
                "latest_date": row[0][:10] if row[0] else None,
                "latest_timestamp": row[0],
                "record_count": row[1],
            }

    # Econ events (SQLite)
    econ_db = ds.econ._db
    async with econ_db.execute(
        "SELECT MAX(fetched_at), COUNT(*) FROM econ_events WHERE country = 'United States'"
    ) as cur:
        row = await cur.fetchone()
        if row and row[0]:
            sources["econ_events"] = {
                "latest_timestamp": row[0],
                "record_count": row[1],
            }

    return {
        "service": "esp",
        "checked_at": now.isoformat(),
        "sources": sources,
    }
```

### Step 2: Verify

```bash
curl http://127.0.0.1:19702/esp/health/freshness
```

### Step 3: Commit

```bash
git add infra/esp/routes/health.py
git commit -m "feat(esp): add GET /esp/health/freshness with standardized schema"
```

---

## Task 8: ESP — Sanity Check API

**Files:**
- Create: `infra/esp/routes/admin.py`
- Modify: `infra/esp/main.py` (register router)

### Step 1: Create admin route

Create `infra/esp/routes/admin.py`:

```python
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request

router = APIRouter(tags=["admin"])


def _status(count: int) -> str:
    if count == 0:
        return "pass"
    if count <= 10:
        return "warn"
    return "fail"


@router.get("/esp/admin/sanity")
async def sanity_check(request: Request):
    ds = request.app.state.data_sources
    now = datetime.now(timezone.utc)
    checks = []

    # Check 1: Future timestamps in news
    if ds.news.available:
        coll = ds.news._coll
        future_count = await coll.count_documents({"published_utc": {"$gt": now}})
        future_samples = []
        if future_count > 0:
            async for doc in coll.find({"published_utc": {"$gt": now}}).limit(5):
                future_samples.append({
                    "id": str(doc["_id"]),
                    "published_utc": doc["published_utc"].isoformat() if hasattr(doc["published_utc"], "isoformat") else str(doc["published_utc"]),
                    "title": (doc.get("title") or "")[:80],
                })
        checks.append({
            "name": "future_timestamps",
            "description": "News with published_utc in the future",
            "status": _status(future_count),
            "count": future_count,
            "samples": future_samples,
        })

        # Check 2: Duplicate URLs
        dup_pipeline = [
            {"$group": {"_id": "$article_url", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]
        dup_count_pipeline = [
            {"$group": {"_id": "$article_url", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
            {"$count": "total"},
        ]
        dup_count_result = await coll.aggregate(dup_count_pipeline).to_list(1)
        dup_count = dup_count_result[0]["total"] if dup_count_result else 0
        dup_samples = []
        async for doc in coll.aggregate(dup_pipeline):
            dup_samples.append({"url": doc["_id"], "count": doc["count"]})
        checks.append({
            "name": "duplicate_urls",
            "description": "Duplicate article URLs",
            "status": _status(dup_count),
            "count": dup_count,
            "samples": dup_samples,
        })

        # Check 3: Invalid tickers
        invalid_ticker_count = await coll.count_documents({
            "$or": [
                {"tickers": {"$exists": False}},
                {"tickers": []},
                {"tickers": None},
            ]
        })
        checks.append({
            "name": "invalid_tickers",
            "description": "News with empty or missing ticker arrays",
            "status": _status(invalid_ticker_count),
            "count": invalid_ticker_count,
            "samples": [],
        })

    # Check 4: Missing trading days in earnings
    earn_db = ds.earnings._db
    async with earn_db.execute("SELECT MIN(date), MAX(date) FROM earnings") as cur:
        row = await cur.fetchone()
        if row and row[0] and row[1]:
            dates_with_data = set()
            async with earn_db.execute("SELECT DISTINCT date FROM earnings") as cur2:
                async for r in cur2:
                    dates_with_data.add(r[0])

            start = datetime.strptime(row[0], "%Y-%m-%d").date()
            end = datetime.strptime(row[1], "%Y-%m-%d").date()
            # Check last 30 days of the range
            check_start = max(start, end - timedelta(days=30))
            missing = []
            current = check_start
            while current <= end:
                if current.weekday() < 5:
                    ds_str = current.strftime("%Y-%m-%d")
                    if ds_str not in dates_with_data:
                        missing.append({"date": ds_str})
                current += timedelta(days=1)

            checks.append({
                "name": "missing_trading_days",
                "description": "Weekdays with zero earnings data (last 30 days of range)",
                "status": _status(len(missing)),
                "count": len(missing),
                "samples": missing[:10],
            })

    summary = {
        "total": len(checks),
        "pass": sum(1 for c in checks if c["status"] == "pass"),
        "warn": sum(1 for c in checks if c["status"] == "warn"),
        "fail": sum(1 for c in checks if c["status"] == "fail"),
    }

    return {
        "checked_at": now.isoformat(),
        "checks": checks,
        "summary": summary,
    }
```

### Step 2: Register the router

In `infra/esp/main.py`:

```python
from routes import health, events, triggers, calendar, news, timeline, stats, export, admin

app.include_router(admin.router)
```

### Step 3: Verify

```bash
curl http://127.0.0.1:19702/esp/admin/sanity
```

### Step 4: Commit

```bash
git add infra/esp/routes/admin.py infra/esp/main.py
git commit -m "feat(esp): add GET /esp/admin/sanity with data quality checks"
```

---

## Task 9: Dashboard — Freshness Integration

**Files:**
- Modify: `infra/dashboard/config.py` (add freshness endpoint paths)
- Modify: `infra/dashboard/main.py:28-78,86-212` (fetch freshness + render section)

### Step 1: Update config

In `infra/dashboard/config.py`, the service URLs are already configured. No changes needed — freshness endpoints use the same base URLs.

### Step 2: Add freshness fetching to Dashboard

In `infra/dashboard/main.py`, update `SERVICES` dict to include freshness paths:

```python
SERVICES = {
    "PMB": {"url": settings.pmb_url, "stats": "/_stats", "health": "/v1/health", "freshness": None},
    "ESP": {"url": settings.esp_url, "stats": "/_stats", "health": "/esp/health", "freshness": "/esp/health/freshness"},
    "UPQ": {"url": settings.upq_url, "stats": None, "health": "/health", "freshness": "/health/freshness"},
}
```

Update `_fetch_service` to also fetch freshness:

```python
async def _fetch_service(http: httpx.AsyncClient, name: str, svc: dict) -> dict:
    base = svc["url"]
    result = {"name": name, "status": "down", "stats": None, "health": None, "freshness": None}

    try:
        r = await http.get(f"{base}{svc['health']}")
        if r.status_code < 400:
            result["status"] = "up"
            result["health"] = r.json()
    except Exception:
        pass

    if svc["stats"]:
        try:
            r = await http.get(f"{base}{svc['stats']}")
            if r.status_code < 400:
                result["stats"] = r.json()
                result["status"] = "up"
        except Exception:
            pass

    if svc.get("freshness"):
        try:
            r = await http.get(f"{base}{svc['freshness']}")
            if r.status_code < 400:
                result["freshness"] = r.json()
        except Exception:
            pass

    return result
```

### Step 3: Add freshness rendering to the HTML template

In the `DASHBOARD_HTML` string, add a freshness section to `renderCard()`. After the endpoint table section, before `html += '</div>'`:

```javascript
  // Freshness section
  if (svc.freshness && svc.freshness.sources) {
    const sources = Object.entries(svc.freshness.sources);
    if (sources.length > 0) {
      html += '<div class="section-label">Data Freshness</div>';
      html += '<table class="endpoint-table">';
      html += '<tr><th>Source</th><th>Latest</th><th>Records</th><th>Keys</th></tr>';
      for (const [name, info] of sources) {
        const latest = info.latest_timestamp || info.latest_date || '-';
        const displayLatest = latest.length > 19 ? latest.substring(0, 19) : latest;
        const records = info.record_count != null ? info.record_count.toLocaleString() : '-';
        const keys = info.unique_keys != null ? `${info.unique_keys} ${info.unique_key_label || ''}` : '-';
        html += `<tr><td>${name}</td><td>${displayLatest}</td><td>${records}</td><td>${keys}</td></tr>`;
      }
      html += '</table>';
    }
  }
```

### Step 4: Verify

Run the Dashboard and check the rendered page shows freshness data for UPQ and ESP.

### Step 5: Commit

```bash
git add infra/dashboard/main.py
git commit -m "feat(dashboard): integrate data freshness from UPQ and ESP into status page"
```

---

## Task 10: ESP Client — New Methods

**Files:**
- Modify: `clients/esp/client.py` (add search_news, news_stats, export_news, calendar_coverage, freshness, sanity_check)

### Step 1: Add all new methods

In `clients/esp/client.py`, add after the `news_body` method (line ~278):

```python
    def search_news(
        self,
        tickers: list[str] = None,
        start_utc: str = None,
        end_utc: str = None,
        keyword: str = None,
        publisher: str = None,
        limit: int = 50,
        cursor: str = None,
    ) -> dict:
        """Search news with keyword and publisher filtering."""
        body = {"limit": limit}
        if tickers:
            body["tickers"] = tickers
        if start_utc:
            body["start_utc"] = start_utc
        if end_utc:
            body["end_utc"] = end_utc
        if keyword:
            body["keyword"] = keyword
        if publisher:
            body["publisher"] = publisher
        if cursor:
            body["cursor"] = cursor
        return self._post("/esp/news/search", body)

    def news_stats(self, days: int = 7) -> dict:
        """Get news statistics — daily counts, top tickers, duplicate rates."""
        return self._get("/esp/news/stats", {"days": days})

    def export_news(
        self,
        format: str = "jsonl",
        tickers: str = None,
        start: str = None,
        end: str = None,
    ) -> bytes:
        """Export news data as JSONL or CSV. Returns raw bytes."""
        params = {"format": format}
        if tickers:
            params["tickers"] = tickers
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        resp = self._session.get(
            f"{self.base_url}/esp/news/export",
            params=params,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise ESPError(resp.text, resp.status_code)
        return resp.content

    def calendar_coverage(self, days: int = 30) -> dict:
        """Get calendar coverage statistics — daily counts, missing dates, breakdowns."""
        return self._get("/esp/calendar/coverage", {"days": days})

    def freshness(self) -> dict:
        """Data freshness — standardized schema with latest timestamps and record counts."""
        return self._get("/esp/health/freshness")

    def sanity_check(self) -> dict:
        """Run data quality checks — future timestamps, duplicates, missing days."""
        return self._get("/esp/admin/sanity")
```

### Step 2: Commit

```bash
git add clients/esp/client.py
git commit -m "feat(esp-client): add search_news, news_stats, export, coverage, freshness, sanity_check methods"
```

---

## Task 11: Update UPQ OpenAPI Spec

**Files:**
- Modify: `docs/upq/openapi.yaml` (add /health/freshness)
- Modify: `infra/upq/docs/openapi.yaml` (keep in sync)

### Step 1: Add freshness endpoint and schema to `docs/upq/openapi.yaml`

After the `/health` path, add:

```yaml
  /health/freshness:
    get:
      summary: Data Freshness
      description: |
        Returns freshness metadata for all data sources: latest dates/timestamps,
        record counts, unique ticker/tenor counts, and partition counts.
        Scans Parquet partition directories and queries the latest partition via DuckDB.
      operationId: getHealthFreshness
      responses:
        '200':
          description: Freshness info per data source
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/FreshnessResponse'
        '500':
          description: Internal error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
```

Add to `components/schemas`:

```yaml
    FreshnessResponse:
      type: object
      properties:
        service:
          type: string
          example: "upq"
        checked_at:
          type: string
          format: date-time
        sources:
          type: object
          additionalProperties:
            $ref: '#/components/schemas/FreshnessSource'

    FreshnessSource:
      type: object
      properties:
        latest_timestamp:
          type: string
          format: date-time
          nullable: true
          description: Most recent data timestamp (minute-level sources)
        latest_date:
          type: string
          format: date
          nullable: true
          description: Most recent partition date
        record_count:
          type: integer
          description: Number of records in latest partition
        unique_keys:
          type: integer
          description: Distinct tickers or tenors in latest partition
        unique_key_label:
          type: string
          description: Label for unique_keys (e.g. "tickers", "tenors")
          example: "tickers"
        partition_count:
          type: integer
          nullable: true
          description: Total number of date partitions
```

### Step 2: Copy to `infra/upq/docs/openapi.yaml`

Keep the two copies in sync.

### Step 3: Commit

```bash
git add docs/upq/openapi.yaml infra/upq/docs/openapi.yaml
git commit -m "docs(upq): add /health/freshness to OpenAPI spec"
```

---

## Task 12: Update ESP OpenAPI Spec

**Files:**
- Modify: `docs/esp/openapi.yaml` (rewrite to match actual API)

The current ESP OpenAPI doc is outdated (uses old paths like `/health`, `/news/push`, `/news/query`). It needs a full rewrite to match the actual `/esp/*` routes.

### Step 1: Rewrite `docs/esp/openapi.yaml`

Replace the entire file with a spec that covers all current + new endpoints:

**Existing endpoints to document:**
- `GET /esp/health`
- `POST /esp/events/query`
- `GET /esp/events/{event_id}`
- `POST /esp/events/stream`
- `POST /esp/triggers/next`
- `POST /esp/calendar/econ`
- `POST /esp/calendar/earnings`
- `POST /esp/timeline`
- `GET /esp/news/{news_id}/body`

**New endpoints to document:**
- `GET /esp/health/freshness`
- `POST /esp/news/search`
- `GET /esp/news/stats`
- `GET /esp/news/export`
- `GET /esp/calendar/earnings/export`
- `GET /esp/calendar/economic/export`
- `GET /esp/calendar/coverage`
- `GET /esp/admin/sanity`

Include schemas for all request/response models: `Event`, `EventQueryRequest`, `NewsSearchRequest`, `PaginatedResponse`, `TriggerResponse`, `TimelineResponse`, `FreshnessResponse`, `SanityResponse`, etc.

### Step 2: Commit

```bash
git add docs/esp/openapi.yaml
git commit -m "docs(esp): rewrite OpenAPI spec to match actual API routes and add new endpoints"
```

---

## Task 13: Update Requirements Doc

**Files:**
- Modify: `docs/data-platform-requirements.md` (update status markers)

### Step 1: Update the status in the requirements tracking doc

Update the progress overview table and individual section statuses to reflect implementation.

### Step 2: Commit

```bash
git add docs/data-platform-requirements.md
git commit -m "docs: update data platform requirements tracking with implementation status"
```

---

---

## Summary of All Commits

| # | Commit Message | Files |
|---|------|-------|
| 1 | `feat(upq): add /health/freshness endpoint` | `app.rs`, `api_contract_tests.rs` |
| 2 | `feat(upq-client): add freshness() method` | `clients/upq/client.py` |
| 3 | `feat(esp): add POST /esp/news/search` | `models.py`, `data_sources.py`, `news.py` |
| 4 | `feat(esp): add GET /esp/news/stats` | `routes/stats.py`, `main.py` |
| 5 | `feat(esp): add export endpoints` | `routes/export.py`, `main.py` |
| 6 | `feat(esp): add GET /esp/calendar/coverage` | `routes/calendar.py` |
| 7 | `feat(esp): add GET /esp/health/freshness` | `routes/health.py` |
| 8 | `feat(esp): add GET /esp/admin/sanity` | `routes/admin.py`, `main.py` |
| 9 | `feat(dashboard): integrate freshness` | `dashboard/main.py` |
| 10 | `feat(esp-client): add new methods` | `clients/esp/client.py` |
| 11 | `docs(upq): add /health/freshness to OpenAPI spec` | `docs/upq/openapi.yaml`, `infra/upq/docs/openapi.yaml` |
| 12 | `docs(esp): rewrite OpenAPI spec` | `docs/esp/openapi.yaml` |
| 13 | `docs: update requirements tracking` | `data-platform-requirements.md` |
