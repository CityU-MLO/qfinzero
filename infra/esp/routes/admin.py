import logging
from datetime import datetime, timedelta, date, timezone

from fastapi import APIRouter, Request

logger = logging.getLogger("esp.admin")

router = APIRouter(tags=["admin"])


def _check_status(count: int) -> str:
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

    # ── 1. Future timestamps (MongoDB) ───────────────────────────
    future_check = {
        "name": "future_timestamps",
        "description": "News articles with published_utc in the future",
        "status": "pass",
        "count": 0,
        "samples": [],
    }
    if ds.news.available:
        try:
            coll = ds.news._coll
            future_count = await coll.count_documents({"published_utc": {"$gt": now}})
            future_check["count"] = future_count
            future_check["status"] = _check_status(future_count)
            if future_count > 0:
                cursor = coll.find({"published_utc": {"$gt": now}}).sort([("published_utc", -1)]).limit(5)
                async for doc in cursor:
                    pub = doc.get("published_utc")
                    pub_iso = pub.isoformat() if hasattr(pub, "isoformat") else str(pub)
                    future_check["samples"].append({
                        "id": str(doc["_id"]),
                        "title": doc.get("title", "")[:80],
                        "published_utc": pub_iso,
                    })
        except Exception as e:
            logger.warning("Error checking future timestamps: %s", e)
    checks.append(future_check)

    # ── 2. Duplicate URLs (MongoDB) ──────────────────────────────
    dup_check = {
        "name": "duplicate_urls",
        "description": "Duplicate article_url values in news collection",
        "status": "pass",
        "count": 0,
        "samples": [],
    }
    if ds.news.available:
        try:
            coll = ds.news._coll
            since = now - timedelta(days=30)
            dup_pipeline = [
                {"$match": {"published_utc": {"$gte": since}}},
                {"$group": {"_id": "$article_url", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 5},
            ]
            samples = []
            async for doc in coll.aggregate(dup_pipeline):
                samples.append({
                    "url": doc["_id"],
                    "count": doc["count"],
                })
            # Count number of URLs that have duplicates
            count_pipeline = [
                {"$match": {"published_utc": {"$gte": since}}},
                {"$group": {"_id": "$article_url", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}},
                {"$count": "total"},
            ]
            dup_url_count = 0
            async for doc in coll.aggregate(count_pipeline):
                dup_url_count = doc["total"]
            dup_check["count"] = dup_url_count
            dup_check["status"] = _check_status(dup_url_count)
            dup_check["samples"] = samples
        except Exception as e:
            logger.warning("Error checking duplicate URLs: %s", e)
    checks.append(dup_check)

    # ── 3. Invalid tickers (MongoDB) ─────────────────────────────
    invalid_check = {
        "name": "invalid_tickers",
        "description": "News articles with empty or missing ticker arrays",
        "status": "pass",
        "count": 0,
        "samples": [],
    }
    if ds.news.available:
        try:
            coll = ds.news._coll
            invalid_query = {"$or": [
                {"tickers": {"$exists": False}},
                {"tickers": []},
                {"tickers": None},
            ]}
            invalid_count = await coll.count_documents(invalid_query)
            invalid_check["count"] = invalid_count
            invalid_check["status"] = _check_status(invalid_count)
            if invalid_count > 0:
                cursor = coll.find(invalid_query).sort([("published_utc", -1)]).limit(5)
                async for doc in cursor:
                    pub = doc.get("published_utc")
                    pub_iso = pub.isoformat() if hasattr(pub, "isoformat") else str(pub)
                    invalid_check["samples"].append({
                        "id": str(doc["_id"]),
                        "title": doc.get("title", "")[:80],
                        "published_utc": pub_iso,
                    })
        except Exception as e:
            logger.warning("Error checking invalid tickers: %s", e)
    checks.append(invalid_check)

    # ── 4. Missing trading days (SQLite) ─────────────────────────
    missing_check = {
        "name": "missing_trading_days",
        "description": "Weekdays with zero earnings data in the last 30 days",
        "status": "pass",
        "count": 0,
        "samples": [],
    }
    try:
        db = ds.earnings._db
        start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")

        # Build weekday set
        d_start = date.fromisoformat(start_date)
        d_end = date.fromisoformat(end_date)
        all_weekdays = set()
        d = d_start
        while d <= d_end:
            if d.weekday() < 5:
                all_weekdays.add(d.isoformat())
            d += timedelta(days=1)

        # Get dates with data
        dates_with_data = set()
        async with db.execute(
            "SELECT DISTINCT date FROM earnings WHERE date >= ? AND date <= ?",
            [start_date, end_date],
        ) as cur:
            async for row in cur:
                dates_with_data.add(row[0])

        missing_dates = sorted(all_weekdays - dates_with_data)
        missing_check["count"] = len(missing_dates)
        missing_check["status"] = _check_status(len(missing_dates))
        missing_check["samples"] = [{"date": d} for d in missing_dates[:10]]
    except Exception as e:
        logger.warning("Error checking missing trading days: %s", e)
    checks.append(missing_check)

    # ── Summary ──────────────────────────────────────────────────
    total = len(checks)
    pass_count = sum(1 for c in checks if c["status"] == "pass")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    fail_count = sum(1 for c in checks if c["status"] == "fail")

    return {
        "checked_at": now.isoformat(),
        "summary": {
            "total": total,
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
        },
        "checks": checks,
    }
