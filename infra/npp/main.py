"""
NPP — News Pushing Pipeline server.

Unified event query API over three data sources:
  - MongoDB (market news)
  - SQLite (benzinga earnings)
  - SQLite (nasdaq economic events)

Start:
    cd infra/npp
    python main.py
"""

import sys
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Allow imports from this directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import settings
from services.data_sources import DataSourceManager
from services.event_service import EventService
from routes import health, events, triggers, calendar, news, timeline, stats, export, admin

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("npp")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Resolve DB paths relative to repo root
    earnings_path = str(REPO_ROOT / settings.earnings_db)
    econ_path = str(REPO_ROOT / settings.econ_events_db)

    ds = DataSourceManager(
        mongo_uri=settings.mongo_uri,
        mongo_db=settings.mongo_db,
        mongo_collection=settings.mongo_collection,
        earnings_db=earnings_path,
        econ_events_db=econ_path,
    )
    await ds.connect()

    event_svc = EventService(ds)

    app.state.data_sources = ds
    app.state.event_service = event_svc

    logger.info("NPP started on %s:%s", settings.host, settings.port)
    logger.info("MongoDB: %s/%s.%s", settings.mongo_uri, settings.mongo_db, settings.mongo_collection)
    logger.info("Earnings DB: %s", earnings_path)
    logger.info("Econ Events DB: %s", econ_path)

    yield

    await ds.close()
    logger.info("NPP stopped")


app = FastAPI(
    title="News Pushing Pipeline",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(
        status_code=500,
        content={"code": "internal_error", "message": str(exc)},
    )


from qfinzero.metrics import attach_metrics
attach_metrics(app, service_name="npp")

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
