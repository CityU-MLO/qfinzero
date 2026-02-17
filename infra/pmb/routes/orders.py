from fastapi import APIRouter, HTTPException, Request

from models.order import CreateOrderRequest, CancelOrderRequest, ModifyOrderRequest

router = APIRouter(tags=["orders"])


@router.post("/v1/orders")
async def place_order(req: CreateOrderRequest, request: Request):
    order_svc = request.app.state.order_service
    result = order_svc.place_order(req)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_argument", "message": result.get("error", "unknown error")},
        )
    return result


@router.get("/v1/orders/{order_id}")
async def get_order(order_id: str, request: Request, session_id: str | None = None):
    session_svc = request.app.state.session_service

    # Search all sessions for this order
    if session_id:
        result = request.app.state.order_service.get_order(order_id, session_id)
        if result:
            return result

    for sid, state in session_svc._sessions.items():
        order = state.order_manager.get_order(order_id)
        if order is not None:
            return {"order": order.model_dump()}

    raise HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": "order_id not found"},
    )


@router.post("/v1/orders/{order_id}/cancel")
async def cancel_order(order_id: str, req: CancelOrderRequest, request: Request):
    order_svc = request.app.state.order_service
    result = order_svc.cancel_order(order_id, req.session_id)
    if not result.get("ok"):
        error = result.get("error", "unknown error")
        if "not found" in error:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": error},
            )
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_argument", "message": error},
        )
    return result


@router.post("/v1/orders/{order_id}/modify")
async def modify_order(order_id: str, req: ModifyOrderRequest, request: Request):
    order_svc = request.app.state.order_service
    result = order_svc.modify_order(order_id, req.session_id, req.updates)
    if not result.get("ok"):
        error = result.get("error", "unknown error")
        if "not found" in error:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": error},
            )
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_argument", "message": error},
        )
    return result
