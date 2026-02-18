from fastapi import APIRouter, Request

from models import TimelineRequest

router = APIRouter(tags=["timeline"])


@router.post("/npp/timeline")
async def timeline(req: TimelineRequest, request: Request):
    svc = request.app.state.event_service
    result = await svc.build_timeline(req)
    return result.model_dump()
