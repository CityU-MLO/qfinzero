"""
UPQ Client — Python client for the Unified Price Query REST API.

Usage:
    from qfinzero.clients.upq import UPQClient

    with UPQClient() as upq:
        bars = upq.stock_daily(["AAPL", "MSFT"], "2025-01-06", "2025-01-31")
        for bar in bars:
            print(bar["ticker"], bar["date"], bar["close"])

        chain = upq.option_chain("NVDA", "2025-01-06", type="C",
                                  strike_min=130, strike_max=150)
"""

import requests
from datetime import datetime, timezone
from typing import Optional


class UPQError(Exception):
    """Error from UPQ API."""

    def __init__(self, message: str, status_code: int = None, code: str = None):
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class UPQClient:
    """Synchronous client for the Unified Price Query REST API."""

    DEFAULT_URL = "http://127.0.0.1:19350"

    def __init__(self, base_url: str = None, timeout: int = 30):
        self.base_url = (base_url or self.DEFAULT_URL).rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._session.close()

    # ── HTTP helpers ──────────────────────────────────────────────

    def _get(self, path: str, params: dict = None) -> any:
        resp = self._session.get(
            f"{self.base_url}{path}",
            params=params,
            timeout=self.timeout,
        )
        return self._handle(resp)

    def _handle(self, resp: requests.Response):
        try:
            data = resp.json()
        except Exception:
            raise UPQError(f"Non-JSON response: {resp.status_code}", resp.status_code)
        if resp.status_code >= 400:
            msg = data.get("message", str(data))
            code = data.get("code", "unknown")
            raise UPQError(msg, resp.status_code, code)
        return data

    # ── Health ────────────────────────────────────────────────────

    def health(self) -> dict:
        return self._get("/health")

    def freshness(self) -> dict:
        """Data freshness — latest timestamps, record counts, and partition info per data source."""
        return self._get("/health/freshness")

    # ── Stock ─────────────────────────────────────────────────────

    def stock_minute(
        self,
        tickers: list[str],
        start: str,
        end: str,
        fields: str = None,
        limit: int = None,
    ) -> list[dict]:
        """Query stock minute bars.

        Args:
            tickers: List of symbols, e.g. ["AAPL", "MSFT"]
            start: ISO datetime, e.g. "2025-01-06T09:30:00"
            end: ISO datetime, e.g. "2025-01-06T16:00:00"
            fields: Comma-separated fields to return (default: all)
            limit: Max rows (1-100000, default 10000)

        Returns:
            List of dicts with ticker, window_start, open, high, low, close, volume, transactions.
            window_start is nanoseconds since epoch.
        """
        params = {
            "tickers": ",".join(tickers),
            "start": start,
            "end": end,
        }
        if fields:
            params["fields"] = fields
        if limit is not None:
            params["limit"] = limit
        return self._get("/stock", params)

    def stock_daily(
        self,
        tickers: list[str],
        start: str,
        end: str,
        fields: str = None,
        indicators: str = None,
    ) -> list[dict]:
        """Query stock daily bars with optional technical indicators.

        Args:
            tickers: List of symbols, e.g. ["AAPL", "MSFT"]
            start: Date string, e.g. "2025-01-06"
            end: Date string, e.g. "2025-01-31"
            fields: Comma-separated fields to return (default: all)
            indicators: Comma-separated indicators, e.g. "ma_5,ema_12,macd"
                        Supported: ma_N (SMA), ema_N (EMA), macd (MACD 12/26/9).

        Returns:
            List of dicts with ticker, date, OHLCV fields, plus indicator columns when requested.
        """
        params = {
            "tickers": ",".join(tickers),
            "start": start,
            "end": end,
        }
        if fields:
            params["fields"] = fields
        if indicators:
            params["indicators"] = indicators
        return self._get("/stock/daily", params)

    # ── Options ───────────────────────────────────────────────────

    def option_contract(
        self,
        contract: str,
        start: str,
        end: str,
        resolution: str = "day",
        fields: str = None,
        include_greeks: bool = False,
        greek_model: str = None,
        greek_price_field: str = None,
    ) -> list[dict]:
        """Query price data for a specific option contract.

        Args:
            contract: OPRA contract ID, e.g. "O:NVDA250117C00136000"
            start: Date or datetime string
            end: Date or datetime string
            resolution: "day" or "minute"
            fields: Comma-separated fields to return
            include_greeks: When True, append BSM-European Greeks (iv, delta,
                gamma, theta, vega, rho, greek_status, greek_meta) to each row
            greek_model: Pricing model — only "bsm" supported in V1
            greek_price_field: Price field for IV inversion — only "close" in V1

        Returns:
            List of dicts with contract, window_start, open, high, low, close, volume, etc.
            Day resolution also includes underlying, expiry, strike, type.
            When include_greeks=True, rows also include iv, delta, gamma, theta,
            vega, rho, greek_status, and greek_meta.
        """
        params = {
            "contract": contract,
            "start": start,
            "end": end,
            "resolution": resolution,
        }
        if fields:
            params["fields"] = fields
        if include_greeks:
            params["include_greeks"] = "true"
        if greek_model:
            params["greek_model"] = greek_model
        if greek_price_field:
            params["greek_price_field"] = greek_price_field
        return self._get("/option/ticker_query", params)

    def option_chain(
        self,
        underlying: str,
        date: str,
        expiry_min: str = None,
        expiry_max: str = None,
        strike_min: float = None,
        strike_max: float = None,
        type: str = None,
        fields: str = None,
        include_greeks: bool = False,
        greek_model: str = None,
        greek_price_field: str = None,
    ) -> list[dict]:
        """Query option chain for an underlying on a given date.

        Args:
            underlying: Ticker symbol, e.g. "NVDA"
            date: Trade date, e.g. "2025-01-06"
            expiry_min: Min expiration filter
            expiry_max: Max expiration filter
            strike_min: Min strike price filter
            strike_max: Max strike price filter
            type: "C" for calls, "P" for puts
            fields: Comma-separated fields to return
            include_greeks: When True, append BSM-European Greeks (iv, delta,
                gamma, theta, vega, rho, greek_status, greek_meta) to each row
            greek_model: Pricing model — only "bsm" supported in V1
            greek_price_field: Price field for IV inversion — only "close" in V1

        Returns:
            List of dicts with ticker, underlying, expiry, strike, type, close, volume, etc.
            When include_greeks=True, rows also include iv, delta, gamma, theta,
            vega, rho, greek_status, and greek_meta.
            If expiry_min == expiry_max and exact expiry has no rows, server may
            fallback to the nearest available expiry (±7 days, then same month).
        """
        params = {"underlying": underlying, "date": date}
        if expiry_min:
            params["expiry_min"] = expiry_min
        if expiry_max:
            params["expiry_max"] = expiry_max
        if strike_min is not None:
            params["strike_min"] = strike_min
        if strike_max is not None:
            params["strike_max"] = strike_max
        if type:
            params["type"] = type
        if fields:
            params["fields"] = fields
        if include_greeks:
            params["include_greeks"] = "true"
        if greek_model:
            params["greek_model"] = greek_model
        if greek_price_field:
            params["greek_price_field"] = greek_price_field
        return self._get("/option/chain_query", params)

    # ── Dividends ──────────────────────────────────────────────────

    def dividends(
        self,
        tickers: list[str],
        start: str,
        end: str,
    ) -> list[dict]:
        """Query dividend data for stocks/ETFs.

        Args:
            tickers: List of symbols, e.g. ["JEPQ", "AAPL"]
            start: Date string, e.g. "2024-01-01"
            end: Date string, e.g. "2024-12-31"

        Returns:
            List of dicts with ticker, ex_dividend_date, amount.
        """
        params = {
            "tickers": ",".join(tickers),
            "start": start,
            "end": end,
        }
        return self._get("/dividends/query", params)

    # ── Rates ─────────────────────────────────────────────────────

    def rates(
        self,
        start: str,
        end: str,
        tenors: str = None,
    ) -> list[dict]:
        """Query treasury yield rates.

        Args:
            start: Date string, e.g. "2025-01-02"
            end: Date string, e.g. "2025-01-31"
            tenors: Comma-separated tenors, e.g. "1M,10Y" (default: all)

        Returns:
            List of dicts with date, yield_1_month, yield_10_year, etc.
        """
        params = {"start": start, "end": end}
        if tenors:
            params["tenors"] = tenors
        return self._get("/rates/query", params)

    # ── Utilities ─────────────────────────────────────────────────

    @staticmethod
    def make_opra(underlying: str, expiry: str, right: str, strike: float) -> str:
        """Build an OPRA contract ID.

        Args:
            underlying: e.g. "NVDA"
            expiry: e.g. "2025-01-17"
            right: "C" or "P"
            strike: e.g. 136.0

        Returns:
            OPRA string, e.g. "O:NVDA250117C00136000"
        """
        yy, mm, dd = expiry[2:4], expiry[5:7], expiry[8:10]
        strike_int = int(round(strike * 1000))
        return f"O:{underlying}{yy}{mm}{dd}{right}{strike_int:08d}"

    @staticmethod
    def ns_to_datetime(ns: int) -> datetime:
        """Convert nanosecond timestamp to datetime (UTC)."""
        return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
