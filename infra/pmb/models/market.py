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
    # BSM Greeks (populated when UPQ returns include_greeks data)
    iv: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    rho: Optional[float] = None
    greek_status: Optional[str] = None
