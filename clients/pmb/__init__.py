"""
PMB Client — Python client for the Paper Money Broker.

Usage:
    from qfinzero.clients.pmb import PMBClient, StepResult, PMBError

    with PMBClient() as pmb:
        acct = pmb.create_account(initial_cash=50000.0, start_date="2025-01-06")
        sess = pmb.create_session(
            account_id=acct["account_id"],
            frequency="1d", start_ts="2025-01-06", end_ts="2025-01-31",
            universe={"stocks": ["AAPL"]},
        )
        result = pmb.step(sess["session_id"])
        price = result.get_stock_price("AAPL")
"""

from .client import PMBClient, StepResult, PMBError

__all__ = ["PMBClient", "StepResult", "PMBError"]
