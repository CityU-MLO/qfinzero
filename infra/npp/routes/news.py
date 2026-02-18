from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["news"])


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
