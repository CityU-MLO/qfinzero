from pydantic import BaseModel

from .enums import Side


class Trade(BaseModel):
    trade_id: str
    order_id: str
    instrument_id: str
    side: Side
    qty: int
    price: float
    fees: float
    ts: str = ""
