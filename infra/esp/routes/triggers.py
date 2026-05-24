from fastapi import APIRouter, Request

from models import TriggerNextRequest

router = APIRouter(tags=["triggers"])


@router.post("/esp/triggers/next")
async def triggers_next(req: TriggerNextRequest, request: Request):
    svc = request.app.state.event_service
    result = await svc.get_next_triggers(req)
    return result.model_dump()
