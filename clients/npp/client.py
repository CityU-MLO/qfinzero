"""
NPP Client — Python client for the News Pushing Pipeline REST API.

Usage:
    from qfinzero.clients.npp import NPPClient

    with NPPClient() as npp:
        health = npp.health()
        events = npp.query_events(mode="upcoming", horizon_minutes=120)
        body = npp.news_body("some_article_id")
"""

import requests
from typing import Optional


class NPPError(Exception):
    """Error from NPP API."""

    def __init__(self, message: str, status_code: int = None, code: str = None):
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class NPPClient:
    """Synchronous client for the News Pushing Pipeline REST API."""

    DEFAULT_URL = "http://127.0.0.1:19340"

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

    def _post(self, path: str, json: dict = None) -> any:
        resp = self._session.post(
            f"{self.base_url}{path}",
            json=json,
            timeout=self.timeout,
        )
        return self._handle(resp)

    def _handle(self, resp: requests.Response):
        try:
            data = resp.json()
        except Exception:
            raise NPPError(f"Non-JSON response: {resp.status_code}", resp.status_code)
        if resp.status_code >= 400:
            msg = data.get("message", str(data))
            code = data.get("code", "unknown")
            raise NPPError(msg, resp.status_code, code)
        return data

    # ── Health ────────────────────────────────────────────────────

    def health(self) -> dict:
        """Health check — returns version, status, data freshness."""
        return self._get("/npp/health")

    # ── Events ────────────────────────────────────────────────────

    def query_events(
        self,
        mode: str = "upcoming",
        start_utc: str = None,
        end_utc: str = None,
        horizon_minutes: int = 60,
        event_types: list[str] = None,
        tickers: list[str] = None,
        min_importance: str = None,
        limit: int = 50,
        cursor: str = None,
        view: str = "compact",
        now_utc: str = None,
    ) -> dict:
        """Unified event query — upcoming / just_happened / window modes.

        Args:
            mode: "upcoming", "just_happened", or "window"
            start_utc: Window start (required for window mode)
            end_utc: Window end (required for window mode)
            horizon_minutes: Lookahead/lookback for upcoming/just_happened
            event_types: Filter by ["macro_calendar","earnings","breaking_news","daily_news"]
            tickers: Filter by ticker symbols
            min_importance: "low", "medium", or "high"
            limit: Max events per page
            cursor: Pagination cursor from previous response
            view: "compact" (no payload) or "full" (with payload)
            now_utc: Override current time for replay mode

        Returns:
            dict with server_time_utc, events, next_cursor
        """
        body = {"mode": mode, "horizon_minutes": horizon_minutes, "limit": limit, "view": view}
        if start_utc:
            body["start_utc"] = start_utc
        if end_utc:
            body["end_utc"] = end_utc
        if event_types:
            body["event_types"] = event_types
        if tickers:
            body["tickers"] = tickers
        if min_importance:
            body["min_importance"] = min_importance
        if cursor:
            body["cursor"] = cursor
        if now_utc:
            body["now_utc"] = now_utc
        return self._post("/npp/events/query", body)

    def get_event(self, event_id: str) -> dict:
        """Get a single event by its event_id."""
        return self._get(f"/npp/events/{event_id}")

    def stream(
        self,
        cursor: str = None,
        event_types: list[str] = None,
        tickers: list[str] = None,
        limit: int = 50,
        now_utc: str = None,
    ) -> dict:
        """Incremental polling — returns events since the cursor position.

        Args:
            cursor: Cursor from previous stream/query response
            event_types: Filter by event types
            tickers: Filter by ticker symbols
            limit: Max events per batch
            now_utc: Override current time for replay mode

        Returns:
            dict with server_time_utc, events, next_cursor
        """
        body = {"limit": limit}
        if cursor:
            body["cursor"] = cursor
        if event_types:
            body["event_types"] = event_types
        if tickers:
            body["tickers"] = tickers
        if now_utc:
            body["now_utc"] = now_utc
        return self._post("/npp/events/stream", body)

    # ── Triggers ──────────────────────────────────────────────────

    def next_triggers(
        self,
        tickers: list[str] = None,
        min_importance: str = "medium",
        horizon_minutes: int = 1440,
        limit: int = 5,
        now_utc: str = None,
    ) -> dict:
        """Get upcoming high-importance events for agent wakeup decisions.

        Args:
            tickers: Watchlist tickers to match
            min_importance: Minimum importance threshold
            horizon_minutes: How far ahead to look
            limit: Max trigger events
            now_utc: Override current time for replay mode

        Returns:
            dict with server_time_utc, triggers (each has trigger_time_utc, event_id, event, reason_codes)
        """
        body = {"min_importance": min_importance, "horizon_minutes": horizon_minutes, "limit": limit}
        if tickers:
            body["tickers"] = tickers
        if now_utc:
            body["now_utc"] = now_utc
        return self._post("/npp/triggers/next", body)

    # ── Calendar ──────────────────────────────────────────────────

    def econ_calendar(
        self,
        start_date: str = None,
        end_date: str = None,
        min_importance: str = None,
        limit: int = 100,
        cursor: str = None,
        now_utc: str = None,
    ) -> dict:
        """Query US economic calendar events.

        Args:
            start_date: "YYYY-MM-DD" (default: today)
            end_date: "YYYY-MM-DD" (default: +7 days)
            min_importance: "low", "medium", or "high"
            limit: Max events per page
            cursor: Pagination cursor
            now_utc: Override current time for replay mode

        Returns:
            dict with server_time_utc, events, next_cursor
        """
        body = {"limit": limit}
        if start_date:
            body["start_date"] = start_date
        if end_date:
            body["end_date"] = end_date
        if min_importance:
            body["min_importance"] = min_importance
        if cursor:
            body["cursor"] = cursor
        if now_utc:
            body["now_utc"] = now_utc
        return self._post("/npp/calendar/econ", body)

    def earnings_calendar(
        self,
        start_date: str = None,
        end_date: str = None,
        tickers: list[str] = None,
        min_importance: int = 0,
        limit: int = 100,
        cursor: str = None,
        now_utc: str = None,
    ) -> dict:
        """Query earnings calendar.

        Args:
            start_date: "YYYY-MM-DD" (default: today)
            end_date: "YYYY-MM-DD" (default: +7 days)
            tickers: Filter by ticker symbols
            min_importance: Minimum importance (0-5)
            limit: Max events per page
            cursor: Pagination cursor
            now_utc: Override current time for replay mode

        Returns:
            dict with server_time_utc, events, next_cursor
        """
        body = {"limit": limit, "min_importance": min_importance}
        if start_date:
            body["start_date"] = start_date
        if end_date:
            body["end_date"] = end_date
        if tickers:
            body["tickers"] = tickers
        if cursor:
            body["cursor"] = cursor
        if now_utc:
            body["now_utc"] = now_utc
        return self._post("/npp/calendar/earnings", body)

    # ── News ──────────────────────────────────────────────────────

    def news_body(self, news_id: str) -> dict:
        """Fetch full news article body by ID.

        Returns:
            dict with news_id, title, description, article_url, published_utc,
            tickers, author, keywords, image_url, publisher, insights
        """
        return self._get(f"/npp/news/{news_id}/body")

    # ── Timeline ──────────────────────────────────────────────────

    def timeline(
        self,
        tickers: list[str] = None,
        start_utc: str = None,
        end_utc: str = None,
        bucket_minutes: int = 60,
        now_utc: str = None,
    ) -> dict:
        """Build a compact timeline of events bucketed by time.

        Args:
            tickers: Filter by ticker symbols
            start_utc: Window start (default: now - 6h)
            end_utc: Window end (default: now + 6h)
            bucket_minutes: Bucket size in minutes (default: 60)
            now_utc: Override current time for replay mode

        Returns:
            dict with server_time_utc, buckets (each has bucket_start_utc, bucket_end_utc, count, events)
        """
        body = {"bucket_minutes": bucket_minutes}
        if tickers:
            body["tickers"] = tickers
        if start_utc:
            body["start_utc"] = start_utc
        if end_utc:
            body["end_utc"] = end_utc
        if now_utc:
            body["now_utc"] = now_utc
        return self._post("/npp/timeline", body)
