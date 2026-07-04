import sys
import os
import logging
from contextlib import asynccontextmanager

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# Add pmb root to path for absolute imports
sys.path.insert(0, CURRENT_DIR)

from config import settings
from clients.upq_client import UPQClient
from qfinzero.runtime import qfinzero_version
from services.account_service import AccountService
from services.session_service import SessionService
from services.order_service import OrderService
from services.history_service import HistoryService
from routes import health, accounts, sessions, orders, market, config as config_route

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("pmb")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    upq = UPQClient(settings.upq_base_url)
    await upq.start()

    from services import config_store
    pmb_cfg = config_store.load()

    account_svc = AccountService(
        fee_per_share=float(pmb_cfg["fee_per_share"]),
        buying_power_multiplier=float(pmb_cfg["buying_power_multiplier"]),
    )
    session_svc = SessionService(upq)
    order_svc = OrderService(session_svc)
    history_svc = HistoryService(session_svc)

    app.state.upq = upq
    app.state.pmb_config = pmb_cfg
    app.state.account_service = account_svc
    app.state.session_service = session_svc
    app.state.order_service = order_svc
    app.state.history_service = history_svc

    logger.info(f"Paper Money Broker started on {settings.host}:{settings.port}")
    logger.info(f"UPQ endpoint: {settings.upq_base_url}")

    yield

    # Shutdown
    await upq.close()
    logger.info("Paper Money Broker stopped")


app = FastAPI(
    title="Paper Money Broker",
    version=qfinzero_version(),
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(
        status_code=500,
        content={"code": "internal_error", "message": str(exc)},
    )


from qfinzero.metrics import attach_metrics
attach_metrics(app, service_name="pmb")

app.include_router(health.router)
app.include_router(config_route.router)
app.include_router(accounts.router)
app.include_router(sessions.router)
app.include_router(orders.router)
app.include_router(market.router)


# ── Broker Terminal UI ───────────────────────────────────────────────
# Static, dependency-free single-page UI (modern + Windows 98 themes).
# Served same-origin so it talks to /v1 without CORS.
_STATIC_DIR = os.path.join(CURRENT_DIR, "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/ui", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/ui/")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
