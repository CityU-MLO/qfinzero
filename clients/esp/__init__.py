"""
ESP Client -- Python client for the News Pushing Pipeline.

Usage:
    from qfinzero.clients.esp import ESPClient

    with ESPClient() as esp:
        events = esp.query_events(mode="upcoming", horizon_minutes=60)
        earnings = esp.earnings_calendar(tickers=["AAPL"])
        econ = esp.econ_calendar(start_date="2025-01-01", end_date="2025-01-31")
"""

from .client import ESPClient, ESPError

__all__ = ["ESPClient", "ESPError"]
