from fastapi import APIRouter, Request

from models import EconCalendarRequest, EarningsCalendarRequest

router = APIRouter(tags=["calendar"])


@router.post("/npp/calendar/econ")
async def econ_calendar(req: EconCalendarRequest, request: Request):
    svc = request.app.state.event_service
    result = await svc.query_econ_calendar(req)
    return result.model_dump()


@router.post("/npp/calendar/earnings")
async def earnings_calendar(req: EarningsCalendarRequest, request: Request):
    svc = request.app.state.event_service
    result = await svc.query_earnings_calendar(req)
    return result.model_dump()
