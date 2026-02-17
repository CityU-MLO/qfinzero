import uuid

from models.enums import OrderStatus, OrderType
from models.order import Order, OrderSpec, CreateOrderRequest


class OrderManager:
    """Order state machine with idempotency via client_order_id."""

    def __init__(self):
        self._orders: dict[str, Order] = {}  # order_id -> Order
        self._client_id_map: dict[str, str] = {}  # client_order_id -> order_id

    def submit(
        self,
        req: CreateOrderRequest,
        ts: str,
    ) -> tuple[Order, bool]:
        """Create an order. Returns (order, is_new).
        If client_order_id already exists, returns existing order with is_new=False.
        """
        coid = req.client_order_id
        if coid and coid in self._client_id_map:
            existing_id = self._client_id_map[coid]
            return self._orders[existing_id], False

        spec = req.order

        order_id = f"ord_{uuid.uuid4().hex[:8]}"
        instrument_id = spec.instrument.instrument_id()

        order = Order(
            order_id=order_id,
            client_order_id=coid,
            session_id=req.session_id,
            account_id=req.account_id,
            instrument_id=instrument_id,
            side=spec.side,
            order_type=spec.order_type,
            qty=spec.qty,
            remaining_qty=spec.qty,
            limit_price=spec.limit_price,
            stop_price=spec.stop_price,
            time_in_force=spec.time_in_force,
            status=OrderStatus.NEW,
            created_ts=ts,
            last_update_ts=ts,
        )

        self._orders[order_id] = order
        if coid:
            self._client_id_map[coid] = order_id

        return order, True

    def accept(self, order_id: str, ts: str) -> Order:
        order = self._orders[order_id]
        order.status = OrderStatus.ACCEPTED
        order.last_update_ts = ts
        return order

    def reject(self, order_id: str, reason: str, ts: str) -> Order:
        order = self._orders[order_id]
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason
        order.last_update_ts = ts
        return order

    def record_fill(
        self, order_id: str, fill_qty: int, fill_price: float, ts: str
    ) -> Order:
        order = self._orders[order_id]
        prev_filled = order.filled_qty
        order.filled_qty += fill_qty
        order.remaining_qty = order.qty - order.filled_qty

        # Weighted average fill price
        if order.avg_fill_price is None:
            order.avg_fill_price = fill_price
        else:
            total_val = order.avg_fill_price * prev_filled + fill_price * fill_qty
            order.avg_fill_price = total_val / order.filled_qty

        if order.remaining_qty <= 0:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIALLY_FILLED

        order.last_update_ts = ts
        return order

    def cancel(self, order_id: str, ts: str) -> Order | None:
        order = self._orders.get(order_id)
        if order is None:
            return None
        if order.is_terminal:
            return None
        order.status = OrderStatus.CANCELLED
        order.last_update_ts = ts
        return order

    def expire_day_orders(self, ts: str) -> list[Order]:
        expired = []
        for order in self._orders.values():
            if order.is_terminal:
                continue
            if order.time_in_force.value == "DAY":
                order.status = OrderStatus.EXPIRED
                order.last_update_ts = ts
                expired.append(order)
        return expired

    def get_open_orders(self) -> list[Order]:
        return [
            o
            for o in self._orders.values()
            if o.status in (OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED)
        ]

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def get_all_orders(self) -> list[Order]:
        return list(self._orders.values())

    def get_orders_filtered(
        self,
        session_id: str | None = None,
        status_in: list[str] | None = None,
    ) -> list[Order]:
        result = list(self._orders.values())
        if session_id:
            result = [o for o in result if o.session_id == session_id]
        if status_in:
            result = [o for o in result if o.status.value in status_in]
        return result

    def validate_order(self, spec: OrderSpec) -> str | None:
        """Validate order spec. Returns error message or None."""
        if spec.qty <= 0:
            return "qty must be positive"
        if spec.order_type == OrderType.LIMIT and spec.limit_price is None:
            return "limit_price required for LIMIT order"
        if spec.order_type == OrderType.STOP and spec.stop_price is None:
            return "stop_price required for STOP order"
        if spec.order_type == OrderType.STOP_LIMIT:
            if spec.stop_price is None:
                return "stop_price required for STOP_LIMIT order"
            if spec.limit_price is None:
                return "limit_price required for STOP_LIMIT order"
        return None
