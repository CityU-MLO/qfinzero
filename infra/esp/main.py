"""
ESP — News Pushing Pipeline server.

Unified event query API over three data sources:
  - MongoDB (market news)
  - SQLite (benzinga earnings)
  - SQLite (nasdaq economic events)

Start:
    cd infra/esp
    python main.py
"""

import sys
import os
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Allow imports from this directory
sys.path.insert(0, CURRENT_DIR)

from config import settings
from qfinzero.runtime import qfinzero_version
from services.data_sources import DataSourceManager
from services.event_service import EventService
from routes import health, events, triggers, calendar, news, timeline, stats, export, admin

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("esp")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _news_config() -> dict:
    """MongoDB news settings from the data configuration (Settings -> News
    storage), falling back to the ESP environment. ``ESP_MONGO_*`` set
    explicitly still win, as documented."""
    try:
        from qfinzero.admin import news_store
        s = news_store.settings()
        targets = news_store.read_targets(s)
        if os.environ.get("ESP_MONGO_COLLECTION"):
            targets = [("shared", os.environ["ESP_MONGO_COLLECTION"])]
        return {"mongo_uri": os.environ.get("ESP_MONGO_URI") or s["mongo_uri"],
                "mongo_db": os.environ.get("ESP_MONGO_DB") or s["mongo_db"],
                "collections": targets,
                "prefixes": {x["id"]: x.get("prefix") or "" for x in s["sources"]}}
    except Exception as e:  # noqa: BLE001 - no data configuration: the environment
        logger.debug("news settings unavailable (%s); using ESP_MONGO_*", e)
        return {"mongo_uri": settings.mongo_uri, "mongo_db": settings.mongo_db,
                "collections": [("shared", settings.mongo_collection)], "prefixes": {}}


async def _watch_news_config(ds, current: dict, interval: float = 15.0):
    """Swap the news source when its settings change (no restart needed)."""
    from services.data_sources import MongoNewsSource, MultiMongoNewsSource
    while True:
        await asyncio.sleep(interval)
        if ds.news.kind != "mongo":
            continue
        new = _news_config()
        if new == current:
            continue
        if len(new["collections"]) > 1:
            src = MultiMongoNewsSource(new["mongo_uri"], new["mongo_db"], new["collections"], new["prefixes"])
        else:
            src = MongoNewsSource(new["mongo_uri"], new["mongo_db"], new["collections"][0][1])
        await src.connect()
        old, ds.news, current = ds.news, src, new
        await old.close()
        logger.info("News now reads %s/%s", new["mongo_db"], ", ".join(c for _, c in new["collections"]))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Resolve DB paths relative to repo root
    earnings_path = str(REPO_ROOT / settings.earnings_db)
    econ_path = str(REPO_ROOT / settings.econ_events_db)

    news_cfg = _news_config()
    ds = DataSourceManager(
        mongo_uri=news_cfg["mongo_uri"],
        mongo_db=news_cfg["mongo_db"],
        mongo_collection=settings.mongo_collection,
        earnings_db=earnings_path,
        econ_events_db=econ_path,
        news_backend=settings.news_backend,
        news_db=str(REPO_ROOT / settings.news_db),
        news_collections=news_cfg["collections"],
        news_prefixes=news_cfg["prefixes"],
    )
    await ds.connect()
    reconnect = asyncio.create_task(ds.keep_connected())
    watcher = asyncio.create_task(_watch_news_config(ds, news_cfg))

    event_svc = EventService(ds)

    app.state.data_sources = ds
    app.state.event_service = event_svc

    logger.info("ESP started on %s:%s", settings.host, settings.port)
    if ds.news.kind == "mongo":
        logger.info("News: MongoDB %s/%s.%s", settings.mongo_uri, settings.mongo_db, settings.mongo_collection)
    else:
        logger.info("News: SQLite %s", settings.news_db)
    logger.info("Earnings DB: %s", earnings_path)
    logger.info("Econ Events DB: %s", econ_path)

    yield

    reconnect.cancel()
    watcher.cancel()
    await ds.close()
    logger.info("ESP stopped")


app = FastAPI(
    title="News Pushing Pipeline",
    version=qfinzero_version(),
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(
        status_code=500,
        content={"code": "internal_error", "message": "Internal server error"},
    )


from qfinzero.metrics import attach_metrics
attach_metrics(app, service_name="esp")

# Register routes
app.include_router(health.router)
app.include_router(events.router)
app.include_router(triggers.router)
app.include_router(calendar.router)
app.include_router(news.router)
app.include_router(timeline.router)
app.include_router(stats.router)
app.include_router(export.router)
app.include_router(admin.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
