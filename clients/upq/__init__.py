"""
UPQ Client — Python client for the Unified Price Query service.

Usage:
    from clients.upq import UPQClient

    with UPQClient() as upq:
        bars = upq.stock_daily(["AAPL"], "2025-01-06", "2025-01-31")
        chain = upq.option_chain("NVDA", "2025-01-06", type="C")
        yields = upq.rates("2025-01-02", "2025-01-31", tenors="10Y")
"""

from .client import UPQClient, UPQError

__all__ = ["UPQClient", "UPQError"]
