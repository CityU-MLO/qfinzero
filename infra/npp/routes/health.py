from fastapi import APIRouter, Request

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
