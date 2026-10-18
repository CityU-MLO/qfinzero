from typing import Optional

from pydantic import BaseModel

from .enums import InstrumentType


class Position(BaseModel):
    instrument_id: str
    type: InstrumentType
    qty: int
    avg_price: float
    mark_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    # futures: contract multiplier, and the price variation margin has been
    # paid up to (the last settlement, or the trade price before the first one)
    multiplier: Optional[float] = None
    basis_price: Optional[float] = None
    last_settle_date: Optional[str] = None
