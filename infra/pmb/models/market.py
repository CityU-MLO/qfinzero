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


class FutureBar(BaseModel):
    symbol: str
    window_start_ns: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    root: Optional[str] = None
    settle: Optional[float] = None       # daily bars
    session_date: Optional[str] = None   # CME trade date


class Quote(BaseModel):
    """Top of book at the end of the minute ``[window_start, window_start+60s)``."""
    window_start_ns: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_size: int = 0
    ask_size: int = 0

    @property
    def valid_bid(self) -> Optional[float]:
        return self.bid if self.bid is not None and self.bid > 0 else None

    @property
    def valid_ask(self) -> Optional[float]:
        return self.ask if self.ask is not None and self.ask > 0 else None

    @property
    def mid(self) -> Optional[float]:
        b, a = self.valid_bid, self.valid_ask
        if b is None or a is None or a < b:
            return None
        return (a + b) / 2
