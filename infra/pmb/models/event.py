from pydantic import BaseModel
from typing import Optional, Any

from .enums import EventType


class EventEnvelope(BaseModel):
    event_id: str
    ts: str
    type: EventType
    payload: Any


class MarketTickPayload(BaseModel):
    frequency: str
    stocks: list = []
    options: list = []


class OrderEventPayload(BaseModel):
    order_id: str
    client_order_id: Optional[str] = None
    status: str
    filled_qty: int = 0
    remaining_qty: int = 0
    avg_fill_price: Optional[float] = None
    reason_code: Optional[str] = None


class TradeEventPayload(BaseModel):
    trade_id: str
    order_id: str
    instrument_id: str
    side: str
    qty: int
    price: float
    fees: float


class AccountSnapshotPayload(BaseModel):
    cash_available: float
    cash_locked: float = 0.0
    loan: float = 0.0
    equity: float
    initial_margin_req: float = 0.0
    maintenance_margin_req: float = 0.0
    margin_excess: float = 0.0
    buying_power: float = 0.0
    margin_status: str = "NORMAL"
    positions: list = []
    open_orders: list = []


class RiskEventPayload(BaseModel):
    level: str
    reason_code: str
    equity: float
    maintenance_margin_req: float
    action: str


class ErrorEventPayload(BaseModel):
    request_id: Optional[str] = None
    error_code: str
    message: str
    details: dict = {}


class AssignmentPayload(BaseModel):
    underlying: str
    side: str   # "BUY" or "SELL"
    qty: int
    strike: float


class OptionExpiryEventPayload(BaseModel):
    contract: str
    is_itm: bool
    intrinsic_value: float
    option_qty: int  # signed position qty: negative = short, positive = long
    realized_pnl: float
    assignment: Optional[AssignmentPayload] = None
