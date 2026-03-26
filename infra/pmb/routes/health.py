from fastapi import APIRouter
from qfinzero.runtime import qfinzero_version

router = APIRouter(tags=["health"])


@router.get("/v1/health")
async def health():
    return {"status": "ok", "service": "pmb", "version": qfinzero_version()}
