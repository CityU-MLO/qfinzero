from models.order import CreateOrderRequest
from services.session_service import SessionService


class OrderService:
    """Thin wrapper for order operations, delegates to session state."""

    def __init__(self, session_service: SessionService):
        self._session_service = session_service

    def place_order(self, req: CreateOrderRequest) -> dict:
        state = self._session_service.get_session(req.session_id)
        if state is None:
            return {"ok": False, "error": "session not found"}

        # Validate order
        error = state.order_manager.validate_order(req.order)
        if error:
            return {"ok": False, "error": error}

        ts = state.clock.current_ts

        order, is_new = state.order_manager.submit(req, ts)

        if is_new:
            state.order_manager.accept(order.order_id, ts)
            state.history.record_order(order)

        result = {
            "ok": True,
            "order_id": order.order_id,
            "client_order_id": order.client_order_id,
            "status": order.status.value,
        }
        if not is_new:
            result["idempotent"] = True

        return result

    def cancel_order(self, order_id: str, session_id: str) -> dict:
        state = self._session_service.get_session(session_id)
        if state is None:
            return {"ok": False, "error": "session not found"}

        ts = state.clock.current_ts
        order = state.order_manager.cancel(order_id, ts)
        if order is None:
            return {"ok": False, "error": "order not found or already terminal"}

        state.history.update_order(order)
        return {"ok": True, "order_id": order_id, "status": order.status.value}

    def get_order(self, order_id: str, session_id: str) -> dict | None:
        state = self._session_service.get_session(session_id)
        if state is None:
            return None
        order = state.order_manager.get_order(order_id)
        if order is None:
            return None
        return {"order": order.model_dump()}

    def modify_order(self, order_id: str, session_id: str, updates: dict) -> dict:
        state = self._session_service.get_session(session_id)
        if state is None:
            return {"ok": False, "error": "session not found"}

        old_order = state.order_manager.get_order(order_id)
        if old_order is None:
            return {"ok": False, "error": "order not found"}
        if old_order.is_terminal:
            return {"ok": False, "error": "cannot modify terminal order"}

        ts = state.clock.current_ts

        # Cancel old order
        state.order_manager.cancel(order_id, ts)

        # Create new order with updates
        from models.order import OrderSpec, CreateOrderRequest as COR
        from models.instrument import Instrument
        from models.enums import InstrumentType

        iid = old_order.instrument_id
        if iid.startswith("STOCK:"):
            instrument = Instrument(type=InstrumentType.STOCK, symbol=iid.split(":", 1)[1])
        else:
            instrument = Instrument(type=InstrumentType.OPTION, contract=iid.split(":", 1)[1])

        new_spec = OrderSpec(
            instrument=instrument,
            side=old_order.side,
            order_type=old_order.order_type,
            qty=updates.get("qty", old_order.qty),
            limit_price=updates.get("limit_price", old_order.limit_price),
            stop_price=updates.get("stop_price", old_order.stop_price),
            time_in_force=old_order.time_in_force,
        )

        new_req = COR(
            session_id=old_order.session_id,
            account_id=old_order.account_id,
            order=new_spec,
        )

        new_order, _ = state.order_manager.submit(new_req, ts)
        state.order_manager.accept(new_order.order_id, ts)
        state.history.record_order(new_order)

        return {
            "ok": True,
            "old_order_id": order_id,
            "new_order_id": new_order.order_id,
            "status": new_order.status.value,
        }
