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


class SpreadOrderSpec(BaseModel):
    """Multi-leg order specification for spreads."""
    legs: list[OrderSpec]
    spread_type: str  # PUT_DEBIT_SPREAD, PUT_CREDIT_SPREAD, etc.

    def max_loss_per_unit(self) -> float:
        """Max loss per spread unit = width between strikes."""
        strikes = []
        for leg in self.legs:
            contract = leg.instrument.contract or ""
            # Extract strike from OPRA: last 8 digits / 1000
            if len(contract) >= 8:
                try:
                    strikes.append(int(contract[-8:]) / 1000.0)
                except ValueError:
                    pass
        if len(strikes) == 2:
            return abs(strikes[0] - strikes[1])
        return 0.0

    def validate_spread(self) -> str | None:
        """Validate spread legs. Returns error message or None."""
        if len(self.legs) != 2:
            return "Spread must have exactly 2 legs"
        # Check same underlying
        underlyings = set()
        for leg in self.legs:
            contract = leg.instrument.contract or ""
            # O:QQQ240119P00390000 → underlying = QQQ
            if contract.startswith("O:"):
                parts = contract[2:]
                underlying = ""
                for ch in parts:
                    if ch.isalpha():
                        underlying += ch
                    else:
                        break
                underlyings.add(underlying)
        if len(underlyings) > 1:
            return f"Spread legs must have same underlying, got {underlyings}"
        return None


class CreateOrderRequest(BaseModel):
    session_id: str
    account_id: str
    client_order_id: Optional[str] = None
    order: OrderSpec
    spread_id: Optional[str] = None


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
    spread_id: Optional[str] = None

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
