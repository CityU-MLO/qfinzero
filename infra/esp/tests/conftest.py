"""ESP tests run against the synthetic sample's SQLite stores (no MongoDB).

Run from infra/esp:  python -m pytest tests -q
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

ESP_DIR = Path(__file__).resolve().parents[1]
REPO = ESP_DIR.parents[1]
for p in (str(ESP_DIR), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(scope="session")
def sample():
    from qfinzero.sample import market
    from qfinzero.sample.universe import Universe
    u = Universe()
    return u, market.simulate(u)


@pytest.fixture(scope="session")
def esp_dir(sample, tmp_path_factory):
    from qfinzero.sample.events import write_esp
    root = tmp_path_factory.mktemp("esp")
    write_esp(*sample, root)
    return root


def make_app(esp_dir: Path, news_backend: str = "auto", news_db: str | None = None):
    from fastapi import FastAPI

    from routes import admin, calendar, events, export, health, news, stats, timeline, triggers
    from services.data_sources import DataSourceManager
    from services.event_service import EventService

    @asynccontextmanager
    async def lifespan(app):
        ds = DataSourceManager(
            mongo_uri="mongodb://127.0.0.1:1", mongo_db="x", mongo_collection="x",
            earnings_db=str(esp_dir / "benzinga_earnings.sqlite3"),
            econ_events_db=str(esp_dir / "nasdaq_econ_events.sqlite3"),
            news_backend=news_backend,
            news_db=news_db if news_db is not None else str(esp_dir / "news.sqlite3"))
        await ds.connect()
        app.state.data_sources = ds
        app.state.event_service = EventService(ds)
        yield
        await ds.close()

    app = FastAPI(lifespan=lifespan)
    for r in (health, events, triggers, calendar, news, timeline, stats, export, admin):
        app.include_router(r.router)
    return app


@pytest.fixture
def client(esp_dir):
    from fastapi.testclient import TestClient
    with TestClient(make_app(esp_dir)) as c:
        yield c
