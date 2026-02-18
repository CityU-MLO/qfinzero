import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request

logger = logging.getLogger("npp.stats")

router = APIRouter(tags=["stats"])


@router.get("/npp/news/stats")
async def news_stats(request: Request, days: int = Query(default=7, ge=1, le=90)):
    ds = request.app.state.data_sources

    if not ds.news.available:
        return {"error": "MongoDB unavailable", "total_count": 0}

    coll = ds.news._coll
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    try:
        # Total count
        total_count = await coll.count_documents({"published_utc": {"$gte": since}})

        # Date range
        earliest_doc = await coll.find_one(
            {"published_utc": {"$gte": since}},
            sort=[("published_utc", 1)],
        )
        latest_doc = await coll.find_one(
            {"published_utc": {"$gte": since}},
            sort=[("published_utc", -1)],
        )
        earliest = earliest_doc["published_utc"].isoformat() if earliest_doc else None
        latest = latest_doc["published_utc"].isoformat() if latest_doc else None

        # Daily counts
        daily_pipeline = [
            {"$match": {"published_utc": {"$gte": since}}},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$published_utc"}},
                "count": {"$sum": 1},
            }},
            {"$sort": {"_id": 1}},
        ]
        daily_counts = {}
        async for doc in coll.aggregate(daily_pipeline):
            daily_counts[doc["_id"]] = doc["count"]

        # Top tickers
        ticker_pipeline = [
            {"$match": {"published_utc": {"$gte": since}}},
            {"$unwind": "$tickers"},
            {"$group": {"_id": "$tickers", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20},
        ]
        top_tickers = []
        async for doc in coll.aggregate(ticker_pipeline):
            top_tickers.append({"ticker": doc["_id"], "count": doc["count"]})

        # Top publishers
        pub_pipeline = [
            {"$match": {"published_utc": {"$gte": since}}},
            {"$group": {"_id": "$publisher.name", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        top_publishers = []
        async for doc in coll.aggregate(pub_pipeline):
            top_publishers.append({"publisher": doc["_id"], "count": doc["count"]})

        # Duplicate stats - by URL
        dup_url_pipeline = [
            {"$match": {"published_utc": {"$gte": since}}},
            {"$group": {"_id": "$article_url", "count": {"$sum": 1}}},
            {"$group": {
                "_id": None,
                "total": {"$sum": "$count"},
                "unique": {"$sum": 1},
                "duplicates": {"$sum": {"$cond": [{"$gt": ["$count", 1]}, {"$subtract": ["$count", 1]}, 0]}},
            }},
        ]
        dup_url = {"total": 0, "unique": 0, "duplicate_rate": 0.0}
        async for doc in coll.aggregate(dup_url_pipeline):
            total = doc["total"]
            unique = doc["unique"]
            dup_url = {
                "total": total,
                "unique": unique,
                "duplicate_rate": round((total - unique) / total, 4) if total > 0 else 0.0,
            }

        # Duplicate stats - by title
        dup_title_pipeline = [
            {"$match": {"published_utc": {"$gte": since}}},
            {"$group": {"_id": "$title", "count": {"$sum": 1}}},
            {"$group": {
                "_id": None,
                "total": {"$sum": "$count"},
                "unique": {"$sum": 1},
                "duplicates": {"$sum": {"$cond": [{"$gt": ["$count", 1]}, {"$subtract": ["$count", 1]}, 0]}},
            }},
        ]
        dup_title = {"total": 0, "unique": 0, "duplicate_rate": 0.0}
        async for doc in coll.aggregate(dup_title_pipeline):
            total = doc["total"]
            unique = doc["unique"]
            dup_title = {
                "total": total,
                "unique": unique,
                "duplicate_rate": round((total - unique) / total, 4) if total > 0 else 0.0,
            }

        return {
            "total_count": total_count,
            "date_range": {"earliest": earliest, "latest": latest},
            "daily_counts": daily_counts,
            "top_tickers": top_tickers,
            "top_publishers": top_publishers,
            "duplicate_stats": {
                "by_url": dup_url,
                "by_title": dup_title,
            },
        }

    except Exception as e:
        logger.exception("Error computing news stats")
        return {"error": str(e), "total_count": 0}
