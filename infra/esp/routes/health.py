import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from qfinzero.runtime import qfinzero_version

logger = logging.getLogger("esp.health")

router = APIRouter(tags=["health"])


@router.get("/esp/health")
async def health(request: Request):
    freshness = await request.app.state.data_sources.get_freshness()
    return {
        "status": "ok",
        "service": "esp",
        "version": qfinzero_version(),
        "data_freshness": freshness,
    }


@router.get("/esp/health/freshness")
async def health_freshness(request: Request):
    ds = request.app.state.data_sources
    checked_at = datetime.now(timezone.utc).isoformat()

    # ── News (MongoDB or SQLite) ─────────────────────────────────
    news_info = {"latest_timestamp": None, "record_count": 0, "unique_keys": 0, "unique_key_label": "tickers"}
    try:
        news_info.update(await ds.news.info())
    except Exception as e:
        logger.warning("Error getting news freshness: %s", e)

    # ── Earnings (SQLite) ────────────────────────────────────────
    earnings_info = {"latest_date": None, "latest_timestamp": None, "record_count": 0, "unique_keys": 0, "unique_key_label": "tickers"}
    try:
        db = ds.earnings._db
        if db is None:
            raise RuntimeError("earnings DB not connected")
        async with db.execute("SELECT MAX(last_updated), COUNT(*) FROM earnings") as cur:
            row = await cur.fetchone()
            if row:
                earnings_info["latest_timestamp"] = row[0]
                earnings_info["record_count"] = row[1]
        async with db.execute("SELECT MAX(date) FROM earnings") as cur:
            row = await cur.fetchone()
            if row:
                earnings_info["latest_date"] = row[0]
        async with db.execute("SELECT COUNT(DISTINCT ticker) FROM earnings") as cur:
            row = await cur.fetchone()
            if row:
                earnings_info["unique_keys"] = row[0]
    except Exception as e:
        logger.warning("Error getting earnings freshness: %s", e)

    # ── Econ Events (SQLite) ─────────────────────────────────────
    econ_info = {"latest_timestamp": None, "record_count": 0, "unique_keys": 0, "unique_key_label": "event_types"}
    try:
        db = ds.econ._db
        if db is None:
            raise RuntimeError("econ DB not connected")
        async with db.execute(
            "SELECT MAX(fetched_at), COUNT(*) FROM econ_events WHERE country = 'United States'"
        ) as cur:
            row = await cur.fetchone()
            if row:
                econ_info["latest_timestamp"] = row[0]
                econ_info["record_count"] = row[1]
        async with db.execute(
            "SELECT COUNT(DISTINCT event_name) FROM econ_events WHERE country = 'United States'"
        ) as cur:
            row = await cur.fetchone()
            if row:
                econ_info["unique_keys"] = row[0]
    except Exception as e:
        logger.warning("Error getting econ freshness: %s", e)

    return {
        "service": "esp",
        "checked_at": checked_at,
        "sources": {
            "news": news_info,
            "earnings": earnings_info,
            "econ_events": econ_info,
        },
    }
