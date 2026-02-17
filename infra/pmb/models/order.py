from pydantic import BaseModel
from typing import Optional

from .enums import Side, OrderType, TimeInForce, OrderStatus
from .instrument import Instrument


class OrderSpec(BaseModel):
    instrument: Instrument
    side: Side
    order_type: OrderType
    qty: int
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    expire_ts: Optional[str] = None


class CreateOrderRequest(BaseModel):
    session_id: str
    account_id: str
    client_order_id: Optional[str] = None
    order: OrderSpec


class Order(BaseModel):
    order_id: str
    client_order_id: Optional[str] = None
    session_id: str
    account_id: str
    instrument_id: str
    side: Side
    order_type: OrderType
    qty: int
    filled_qty: int = 0
    remaining_qty: int = 0
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    avg_fill_price: Optional[float] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    status: OrderStatus = OrderStatus.NEW
    created_ts: str = ""
    last_update_ts: str = ""
    reject_reason: Optional[str] = None

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )


class CancelOrderRequest(BaseModel):
    session_id: str
    account_id: str


class ModifyOrderRequest(BaseModel):
    session_id: str
    account_id: str
    updates: dict
