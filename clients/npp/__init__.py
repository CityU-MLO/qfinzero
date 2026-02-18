"""
NPP Client -- Python client for the News Pushing Pipeline.

Usage:
    from qfinzero.clients.npp import NPPClient

    with NPPClient() as npp:
        events = npp.query_events(mode="upcoming", horizon_minutes=60)
        earnings = npp.earnings_calendar(tickers=["AAPL"])
        econ = npp.econ_calendar(start_date="2025-01-01", end_date="2025-01-31")
"""

from .client import NPPClient, NPPError

__all__ = ["NPPClient", "NPPError"]
