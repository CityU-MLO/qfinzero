from pydantic import BaseModel
from typing import Optional


class StockBar(BaseModel):
    symbol: str
    window_start_ns: int
    open: float
    high: float
    low: float
    close: float
    volume: int


class OptionBar(BaseModel):
    contract: str
    window_start_ns: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    underlying: Optional[str] = None
    expiry: Optional[str] = None
    strike: Optional[float] = None
    right: Optional[str] = None
