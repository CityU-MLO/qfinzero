import csv
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger("npp.export")

router = APIRouter(tags=["export"])

EXPORT_LIMIT = 10_000


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _stream_jsonl(rows):
    for row in rows:
        yield json.dumps(row, default=str) + "\n"


def _stream_csv(rows, fieldnames):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    yield buf.getvalue()
    buf.seek(0)
    buf.truncate(0)
    for row in rows:
        writer.writerow(row)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)


# ── News Export ──────────────────────────────────────────────────

@router.get("/npp/news/export")
async def export_news(
    request: Request,
    format: str = Query(default="jsonl", regex="^(jsonl|csv)$"),
    tickers: Optional[str] = Query(default=None),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
):
    ds = request.app.state.data_sources
    if not ds.news.available:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    coll = ds.news._coll
    now = datetime.now(timezone.utc)

    start_dt = _parse_dt(start) or (now - timedelta(days=7))
    end_dt = _parse_dt(end) or now

    query = {"published_utc": {"$gte": start_dt, "$lt": end_dt}}
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",")]
        query["tickers"] = {"$in": ticker_list}

    count = await coll.count_documents(query)
    if count > EXPORT_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Result set ({count}) exceeds export limit ({EXPORT_LIMIT}). Narrow your query.",
        )

    cursor = coll.find(query).sort([("published_utc", 1)]).limit(EXPORT_LIMIT)
    rows = []
    async for doc in cursor:
        pub = doc.get("published_utc")
        pub_iso = pub.isoformat() if hasattr(pub, "isoformat") else str(pub) if pub else None
        publisher = doc.get("publisher")
        pub_name = publisher.get("name") if isinstance(publisher, dict) else None
        rows.append({
            "id": str(doc.get("_id", "")),
            "title": doc.get("title", ""),
            "published_utc": pub_iso,
            "tickers": ",".join(doc.get("tickers") or []),
            "publisher": pub_name or "",
            "article_url": doc.get("article_url", ""),
            "author": doc.get("author", ""),
            "description": (doc.get("description") or "")[:500],
        })

    if format == "jsonl":
        return StreamingResponse(
            _stream_jsonl(rows),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=news_export.jsonl"},
        )
    else:
        fieldnames = ["id", "title", "published_utc", "tickers", "publisher", "article_url", "author", "description"]
        return StreamingResponse(
            _stream_csv(rows, fieldnames),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=news_export.csv"},
        )


# ── Earnings Export ──────────────────────────────────────────────

@router.get("/npp/calendar/earnings/export")
async def export_earnings(
    request: Request,
    format: str = Query(default="csv", regex="^(jsonl|csv)$"),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    ticker: Optional[str] = Query(default=None),
):
    ds = request.app.state.data_sources
    db = ds.earnings._db
    now = datetime.now(timezone.utc)

    start_date = start or (now - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = end or now.strftime("%Y-%m-%d")

    sql = "SELECT * FROM earnings WHERE date >= ? AND date <= ?"
    params: list = [start_date, end_date]

    if ticker:
        ticker_list = [t.strip().upper() for t in ticker.split(",")]
        placeholders = ",".join("?" for _ in ticker_list)
        sql += f" AND ticker IN ({placeholders})"
        params.extend(ticker_list)

    sql += " ORDER BY date ASC, time ASC"

    # Check count first
    count_sql = f"SELECT COUNT(*) FROM ({sql})"
    async with db.execute(count_sql, params) as cur:
        row = await cur.fetchone()
        count = row[0]

    if count > EXPORT_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Result set ({count}) exceeds export limit ({EXPORT_LIMIT}). Narrow your query.",
        )

    sql += f" LIMIT {EXPORT_LIMIT}"
    rows = []
    async with db.execute(sql, params) as cur:
        columns = [desc[0] for desc in cur.description]
        async for row in cur:
            rows.append(dict(zip(columns, row)))

    if format == "jsonl":
        return StreamingResponse(
            _stream_jsonl(rows),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=earnings_export.jsonl"},
        )
    else:
        fieldnames = columns if rows else ["benzinga_id", "ticker", "date", "time"]
        return StreamingResponse(
            _stream_csv(rows, fieldnames),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=earnings_export.csv"},
        )


# ── Economic Events Export ───────────────────────────────────────

@router.get("/npp/calendar/economic/export")
async def export_economic(
    request: Request,
    format: str = Query(default="csv", regex="^(jsonl|csv)$"),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    country: Optional[str] = Query(default=None),
):
    ds = request.app.state.data_sources
    db = ds.econ._db
    now = datetime.now(timezone.utc)

    start_date = start or (now - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = end or now.strftime("%Y-%m-%d")

    sql = "SELECT * FROM econ_events WHERE date >= ? AND date <= ?"
    params: list = [start_date, end_date]

    if country:
        sql += " AND country = ?"
        params.append(country)
    else:
        sql += " AND country = 'United States'"

    sql += " ORDER BY date ASC, gmt_time ASC"

    count_sql = f"SELECT COUNT(*) FROM ({sql})"
    async with db.execute(count_sql, params) as cur:
        row = await cur.fetchone()
        count = row[0]

    if count > EXPORT_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Result set ({count}) exceeds export limit ({EXPORT_LIMIT}). Narrow your query.",
        )

    sql += f" LIMIT {EXPORT_LIMIT}"
    rows = []
    async with db.execute(sql, params) as cur:
        columns = [desc[0] for desc in cur.description]
        async for row in cur:
            rows.append(dict(zip(columns, row)))

    if format == "jsonl":
        return StreamingResponse(
            _stream_jsonl(rows),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=economic_export.jsonl"},
        )
    else:
        fieldnames = columns if rows else ["event_id", "event_name", "date", "gmt_time"]
        return StreamingResponse(
            _stream_csv(rows, fieldnames),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=economic_export.csv"},
        )
