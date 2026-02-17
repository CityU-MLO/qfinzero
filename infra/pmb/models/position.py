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
