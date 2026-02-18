import base64
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from models import NewsSearchRequest, PaginatedResponse

router = APIRouter(tags=["news"])


def _encode_cursor(time_utc: str, event_id: str) -> str:
    return base64.urlsafe_b64encode(
        json.dumps([time_utc, event_id]).encode()
    ).decode()


def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return (raw[0], raw[1])
    except (ValueError, IndexError, KeyError):
        raise HTTPException(status_code=400, detail="Invalid cursor")


def _parse_now(now_utc: str | None) -> datetime:
    if now_utc:
        s = now_utc.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return datetime.now(timezone.utc)


@router.get("/npp/news/{news_id}/body")
async def news_body(news_id: str, request: Request):
    ds = request.app.state.data_sources
    doc = await ds.news.get_by_id(news_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "news article not found"},
        )

    pub = doc.get("published_utc")
    pub_iso = pub.isoformat() if hasattr(pub, "isoformat") else str(pub) if pub else None

    return {
        "news_id": news_id,
        "title": doc.get("title"),
        "description": doc.get("description"),
        "article_url": doc.get("article_url"),
        "published_utc": pub_iso,
        "tickers": doc.get("tickers") or [],
        "author": doc.get("author"),
        "keywords": doc.get("keywords") or [],
        "image_url": doc.get("image_url"),
        "publisher": doc.get("publisher"),
        "insights": doc.get("insights"),
    }


@router.post("/npp/news/search")
async def news_search(req: NewsSearchRequest, request: Request):
    ds = request.app.state.data_sources
    now = _parse_now(req.now_utc)

    if req.start_utc:
        try:
            start = datetime.fromisoformat(req.start_utc.replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_utc format")
    else:
        start = now - timedelta(days=7)

    if req.end_utc:
        try:
            end = datetime.fromisoformat(req.end_utc.replace("Z", "+00:00"))
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_utc format")
    else:
        end = now

    cursor = _decode_cursor(req.cursor)
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

    has_more = len(events) > req.limit
    page = events[: req.limit]
    next_cursor = (
        _encode_cursor(page[-1].time_utc, page[-1].event_id)
        if has_more and page
        else None
    )

    return PaginatedResponse(
        server_time_utc=datetime.now(timezone.utc).isoformat(),
        events=page,
        next_cursor=next_cursor,
    ).model_dump()
