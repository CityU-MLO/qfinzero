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


@router.get("/esp/news/counts")
async def news_counts(
    request: Request,
    tickers: str = Query(..., description="comma-separated symbols, at most 100"),
    start: str = Query(..., description="first US/Eastern date, YYYY-MM-DD"),
    end: str = Query(..., description="last US/Eastern date, YYYY-MM-DD"),
):
    """Articles per ticker and US/Eastern date: ``{counts: [{ticker, date, count}]}``."""
    from zoneinfo import ZoneInfo
    ds = request.app.state.data_sources
    if not ds.news.available:
        raise HTTPException(status_code=503, detail="News store unavailable")
    syms = [t.strip().upper() for t in tickers.split(",") if t.strip()][:100]
    et = ZoneInfo("America/New_York")
    try:
        lo = datetime.fromisoformat(start).replace(tzinfo=et)
        hi = datetime.fromisoformat(end).replace(tzinfo=et) + timedelta(days=1)
    except ValueError:
        raise HTTPException(status_code=400, detail="start/end must be YYYY-MM-DD")
    rows = await ds.news.daily_counts(lo.astimezone(timezone.utc), hi.astimezone(timezone.utc), syms)
    return {"counts": rows}
