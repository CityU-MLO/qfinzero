from fastapi import APIRouter, HTTPException, Request

from models import EventQueryRequest, StreamRequest

router = APIRouter(tags=["events"])


@router.post("/npp/events/query")
async def query_events(req: EventQueryRequest, request: Request):
    svc = request.app.state.event_service
    result = await svc.query_events(req)
    return result.model_dump()


@router.get("/npp/events/{event_id}")
async def get_event(event_id: str, request: Request):
    svc = request.app.state.event_service
    event = await svc.get_event_by_id(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "event not found"})
    return event.model_dump()


@router.post("/npp/events/stream")
async def stream_events(req: StreamRequest, request: Request):
    svc = request.app.state.event_service
    result = await svc.stream(req)
    return result.model_dump()
