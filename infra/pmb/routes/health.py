from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/v1/health")
async def health():
    return {"status": "ok", "service": "paper-broker", "version": "0.1.0"}
