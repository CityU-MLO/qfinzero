import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request

logger = logging.getLogger("npp.health")

router = APIRouter(tags=["health"])


@router.get("/npp/health")
async def health(request: Request):
    freshness = await request.app.state.data_sources.get_freshness()
    return {
        "status": "ok",
        "service": "npp",
        "version": "0.1.0",
        "data_freshness": freshness,
    }


@router.get("/npp/health/freshness")
async def health_freshness(request: Request):
    ds = request.app.state.data_sources
    checked_at = datetime.now(timezone.utc).isoformat()

    # ── News (MongoDB) ───────────────────────────────────────────
    news_info = {"latest_timestamp": None, "record_count": 0, "unique_keys": 0, "unique_key_label": "tickers"}
    if ds.news.available:
        try:
            coll = ds.news._coll
            latest_doc = await coll.find_one(sort=[("published_utc", -1)])
            if latest_doc and latest_doc.get("published_utc"):
                pub = latest_doc["published_utc"]
                news_info["latest_timestamp"] = pub.isoformat() if hasattr(pub, "isoformat") else str(pub)
            news_info["record_count"] = await coll.count_documents({})
            distinct_tickers = await coll.distinct("tickers")
            news_info["unique_keys"] = len(distinct_tickers)
        except Exception as e:
            logger.warning("Error getting news freshness: %s", e)

    # ── Earnings (SQLite) ────────────────────────────────────────
    earnings_info = {"latest_date": None, "latest_timestamp": None, "record_count": 0}
    try:
        db = ds.earnings._db
        async with db.execute("SELECT MAX(last_updated), COUNT(*) FROM earnings") as cur:
            row = await cur.fetchone()
            if row:
                earnings_info["latest_timestamp"] = row[0]
                earnings_info["record_count"] = row[1]
        async with db.execute("SELECT MAX(date) FROM earnings") as cur:
            row = await cur.fetchone()
            if row:
                earnings_info["latest_date"] = row[0]
    except Exception as e:
        logger.warning("Error getting earnings freshness: %s", e)

    # ── Econ Events (SQLite) ─────────────────────────────────────
    econ_info = {"latest_timestamp": None, "record_count": 0}
    try:
        db = ds.econ._db
        async with db.execute(
            "SELECT MAX(fetched_at), COUNT(*) FROM econ_events WHERE country = 'United States'"
        ) as cur:
            row = await cur.fetchone()
            if row:
                econ_info["latest_timestamp"] = row[0]
                econ_info["record_count"] = row[1]
    except Exception as e:
        logger.warning("Error getting econ freshness: %s", e)

    return {
        "service": "npp",
        "checked_at": checked_at,
        "sources": {
            "news": news_info,
            "earnings": earnings_info,
            "econ_events": econ_info,
        },
    }
