"""
Unified event query service.

Orchestrates fan-out to data sources, merges results, applies filters,
handles cursor-based pagination, and dispatches by query mode.
"""

import asyncio
import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from models import (
    Event,
    EventType,
    Importance,
    QueryMode,
    ViewMode,
    EventQueryRequest,
    StreamRequest,
    TriggerNextRequest,
    TriggerItem,
    TriggerResponse,
    TimelineRequest,
    TimelineBucket,
    TimelineResponse,
    EconCalendarRequest,
    EarningsCalendarRequest,
    PaginatedResponse,
)
from services.data_sources import DataSourceManager

logger = logging.getLogger("npp.event_service")

IMP_ORDER = {Importance.LOW: 0, Importance.MEDIUM: 1, Importance.HIGH: 2}


# ── Cursor helpers ───────────────────────────────────────────────

def _encode_cursor(time_utc: str, event_id: str) -> str:
    return base64.urlsafe_b64encode(
        json.dumps([time_utc, event_id]).encode()
    ).decode()


def _decode_cursor(cursor: Optional[str]) -> Optional[tuple[str, str]]:
    if not cursor:
        return None
    raw = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    return (raw[0], raw[1])


def _parse_now(now_utc: Optional[str]) -> datetime:
    if now_utc:
        s = now_utc.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return datetime.now(timezone.utc)


def _server_time() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Source selection ─────────────────────────────────────────────

_TYPE_TO_SOURCE = {
    EventType.MACRO_CALENDAR: "econ",
    EventType.EARNINGS: "earnings",
    EventType.BREAKING_NEWS: "news",
    EventType.DAILY_NEWS: "news",
}


def _select_sources(event_types: Optional[list[EventType]]) -> set[str]:
    if not event_types:
        return {"econ", "earnings", "news"}
    sources = set()
    for et in event_types:
        sources.add(_TYPE_TO_SOURCE[et])
    return sources


# =====================================================================

class EventService:
    def __init__(self, data_sources: DataSourceManager):
        self._ds = data_sources

    # ── Main unified query ───────────────────────────────────────

    async def query_events(self, req: EventQueryRequest) -> PaginatedResponse:
        now = _parse_now(req.now_utc)
        start, end = self._resolve_window(req.mode, now, req)
        cursor = _decode_cursor(req.cursor)
        fetch_limit = req.limit + 1  # overfetch to detect more pages

        sources = _select_sources(req.event_types)

        tasks = []
        task_names = []

        if "earnings" in sources:
            tasks.append(
                self._ds.earnings.query_window(start, end, req.tickers, fetch_limit * 2, cursor)
            )
            task_names.append("earnings")

        if "econ" in sources:
            tasks.append(
                self._ds.econ.query_window(start, end, fetch_limit * 2, cursor)
            )
            task_names.append("econ")

        if "news" in sources:
            tasks.append(
                self._ds.news.query_window(start, end, req.tickers, fetch_limit * 2, cursor, now)
            )
            task_names.append("news")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_events: list[Event] = []
        for name, r in zip(task_names, results):
            if isinstance(r, Exception):
                logger.warning("Data source '%s' error: %s", name, r)
                continue
            all_events.extend(r)

        # Filter by event_types if specified
        if req.event_types:
            allowed = set(req.event_types)
            all_events = [e for e in all_events if e.event_type in allowed]

        # Filter by importance
        if req.min_importance:
            min_val = IMP_ORDER[req.min_importance]
            all_events = [e for e in all_events if IMP_ORDER.get(e.importance, 0) >= min_val]

        # Sort by time_utc, then event_id for stable ordering
        all_events.sort(key=lambda e: (e.time_utc, e.event_id))

        # Pagination
        has_more = len(all_events) > req.limit
        page = all_events[: req.limit]
        next_cursor = (
            _encode_cursor(page[-1].time_utc, page[-1].event_id)
            if has_more and page
            else None
        )

        # Compact view
        if req.view == ViewMode.COMPACT:
            for e in page:
                e.payload = {}

        return PaginatedResponse(
            server_time_utc=_server_time(),
            events=page,
            next_cursor=next_cursor,
        )

    # ── Single event by ID ───────────────────────────────────────

    async def get_event_by_id(self, event_id: str) -> Optional[Event]:
        if event_id.startswith("earn_"):
            return await self._ds.earnings.get_by_id(event_id.removeprefix("earn_"))
        elif event_id.startswith("econ_"):
            return await self._ds.econ.get_by_id(event_id.removeprefix("econ_"))
        elif event_id.startswith("news_"):
            raw_id = event_id.removeprefix("news_")
            doc = await self._ds.news.get_by_id(raw_id)
            if doc:
                now = datetime.now(timezone.utc)
                return self._ds.news._to_event(doc, now)
        return None

    # ── Stream (incremental polling) ─────────────────────────────

    async def stream(self, req: StreamRequest) -> PaginatedResponse:
        now = _parse_now(req.now_utc)

        # Handle special "HEAD" cursor - means stream from latest position
        if req.cursor == "HEAD":
            cursor = None
        else:
            cursor = _decode_cursor(req.cursor)

        # Stream from cursor position to now
        if cursor:
            start = datetime.fromisoformat(cursor[0].replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
        else:
            # Default: last 5 minutes
            start = now - timedelta(minutes=5)

        sources = _select_sources(req.event_types)
        fetch_limit = req.limit + 1
        tasks = []
        task_names = []

        if "earnings" in sources:
            tasks.append(self._ds.earnings.query_window(start, now, req.tickers, fetch_limit * 2, cursor))
            task_names.append("earnings")
        if "econ" in sources:
            tasks.append(self._ds.econ.query_window(start, now, fetch_limit * 2, cursor))
            task_names.append("econ")
        if "news" in sources:
            tasks.append(self._ds.news.query_window(start, now, req.tickers, fetch_limit * 2, cursor, now))
            task_names.append("news")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_events: list[Event] = []
        for name, r in zip(task_names, results):
            if isinstance(r, Exception):
                logger.warning("Stream source '%s' error: %s", name, r)
                continue
            all_events.extend(r)

        if req.event_types:
            allowed = set(req.event_types)
            all_events = [e for e in all_events if e.event_type in allowed]

        all_events.sort(key=lambda e: (e.time_utc, e.event_id))

        has_more = len(all_events) > req.limit
        page = all_events[: req.limit]
        next_cursor = (
            _encode_cursor(page[-1].time_utc, page[-1].event_id)
            if page
            else req.cursor
        )

        return PaginatedResponse(
            server_time_utc=_server_time(),
            events=page,
            next_cursor=next_cursor,
        )

    # ── Triggers ─────────────────────────────────────────────────

    async def get_next_triggers(self, req: TriggerNextRequest) -> TriggerResponse:
        now = _parse_now(req.now_utc)
        end = now + timedelta(minutes=req.horizon_minutes)

        tasks = [
            self._ds.earnings.query_window(now, end, req.tickers, req.limit * 3, None),
            self._ds.econ.query_window(now, end, req.limit * 3, None),
        ]
        if self._ds.news.available:
            tasks.append(self._ds.news.query_window(now, end, req.tickers, req.limit * 3, None, now))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_events: list[Event] = []
        for r in results:
            if isinstance(r, Exception):
                continue
            all_events.extend(r)

        # Filter by importance
        min_val = IMP_ORDER[req.min_importance]
        all_events = [e for e in all_events if IMP_ORDER.get(e.importance, 0) >= min_val]

        all_events.sort(key=lambda e: (e.time_utc, e.event_id))
        page = all_events[: req.limit]

        triggers = []
        for ev in page:
            reason_codes = []
            if IMP_ORDER.get(ev.importance, 0) >= 2:
                reason_codes.append("HIGH_IMPORTANCE")
            ev_time = datetime.fromisoformat(ev.time_utc.replace("Z", "+00:00"))
            if ev_time.tzinfo is None:
                ev_time = ev_time.replace(tzinfo=timezone.utc)
            if (ev_time - now).total_seconds() < 1800:
                reason_codes.append("TIME_IMMINENT")
            if req.tickers and any(t in (req.tickers or []) for t in ev.tickers):
                reason_codes.append("MATCH_WATCHLIST")

            triggers.append(TriggerItem(
                trigger_time_utc=ev.time_utc,
                event_id=ev.event_id,
                event=ev,
                reason_codes=reason_codes,
            ))

        return TriggerResponse(
            server_time_utc=_server_time(),
            triggers=triggers,
        )

    # ── Calendar: Econ ───────────────────────────────────────────

    async def query_econ_calendar(self, req: EconCalendarRequest) -> PaginatedResponse:
        now = _parse_now(req.now_utc)
        start_date = req.start_date or now.strftime("%Y-%m-%d")
        end_date = req.end_date or (now + timedelta(days=7)).strftime("%Y-%m-%d")
        cursor = _decode_cursor(req.cursor)
        fetch_limit = req.limit + 1

        events = await self._ds.econ.query_by_dates(
            start_date, end_date, req.min_importance, fetch_limit, cursor,
        )

        has_more = len(events) > req.limit
        page = events[: req.limit]
        next_cursor = (
            _encode_cursor(page[-1].time_utc, page[-1].event_id)
            if has_more and page
            else None
        )

        return PaginatedResponse(
            server_time_utc=_server_time(),
            events=page,
            next_cursor=next_cursor,
        )

    # ── Calendar: Earnings ───────────────────────────────────────

    async def query_earnings_calendar(self, req: EarningsCalendarRequest) -> PaginatedResponse:
        now = _parse_now(req.now_utc)
        start_date = req.start_date or now.strftime("%Y-%m-%d")
        end_date = req.end_date or (now + timedelta(days=7)).strftime("%Y-%m-%d")
        cursor = _decode_cursor(req.cursor)
        fetch_limit = req.limit + 1

        events = await self._ds.earnings.query_by_dates(
            start_date, end_date, req.tickers, req.min_importance, fetch_limit, cursor,
        )

        has_more = len(events) > req.limit
        page = events[: req.limit]
        next_cursor = (
            _encode_cursor(page[-1].time_utc, page[-1].event_id)
            if has_more and page
            else None
        )

        return PaginatedResponse(
            server_time_utc=_server_time(),
            events=page,
            next_cursor=next_cursor,
        )

    # ── Timeline ─────────────────────────────────────────────────

    async def build_timeline(self, req: TimelineRequest) -> TimelineResponse:
        now = _parse_now(req.now_utc)
        start = datetime.fromisoformat(req.start_utc.replace("Z", "+00:00")) if req.start_utc else now - timedelta(hours=6)
        end = datetime.fromisoformat(req.end_utc.replace("Z", "+00:00")) if req.end_utc else now + timedelta(hours=6)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        # Fetch all events in the window
        tasks = [
            self._ds.earnings.query_window(start, end, req.tickers, 500, None),
            self._ds.econ.query_window(start, end, 500, None),
        ]
        if self._ds.news.available:
            tasks.append(self._ds.news.query_window(start, end, req.tickers, 500, None, now))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_events: list[Event] = []
        for r in results:
            if isinstance(r, Exception):
                continue
            all_events.extend(r)

        all_events.sort(key=lambda e: (e.time_utc, e.event_id))

        # Strip to compact (no payload)
        for e in all_events:
            e.payload = {}

        # Build buckets
        bucket_delta = timedelta(minutes=req.bucket_minutes)
        buckets: list[TimelineBucket] = []
        bucket_start = start

        while bucket_start < end:
            bucket_end = min(bucket_start + bucket_delta, end)
            bs_iso = bucket_start.isoformat()
            be_iso = bucket_end.isoformat()

            bucket_events = [
                e for e in all_events
                if bs_iso <= e.time_utc < be_iso
            ]

            buckets.append(TimelineBucket(
                bucket_start_utc=bs_iso,
                bucket_end_utc=be_iso,
                count=len(bucket_events),
                events=bucket_events,
            ))
            bucket_start = bucket_end

        return TimelineResponse(
            server_time_utc=_server_time(),
            buckets=buckets,
        )

    # ── Internals ────────────────────────────────────────────────

    def _resolve_window(
        self,
        mode: QueryMode,
        now: datetime,
        req: EventQueryRequest,
    ) -> tuple[datetime, datetime]:
        if mode == QueryMode.WINDOW:
            s = datetime.fromisoformat((req.start_utc or now.isoformat()).replace("Z", "+00:00"))
            e = datetime.fromisoformat((req.end_utc or now.isoformat()).replace("Z", "+00:00"))
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if e.tzinfo is None:
                e = e.replace(tzinfo=timezone.utc)
            return s, e
        elif mode == QueryMode.UPCOMING:
            return now, now + timedelta(minutes=req.horizon_minutes)
        else:  # JUST_HAPPENED
            return now - timedelta(minutes=req.horizon_minutes), now
