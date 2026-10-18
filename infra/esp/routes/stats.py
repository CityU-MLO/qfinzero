import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger("esp.stats")

router = APIRouter(tags=["stats"])


@router.get("/esp/news/stats")
async def news_stats(request: Request, days: int = Query(default=7, ge=1, le=90)):
    ds = request.app.state.data_sources

    if not ds.news.available:
        raise HTTPException(status_code=503, detail="News store unavailable")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        return await ds.news.stats(since)
    except Exception:
        logger.exception("Error computing news stats")
        raise HTTPException(status_code=500, detail="Internal error computing stats")
