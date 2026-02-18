from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────

class EventType(str, Enum):
    MACRO_CALENDAR = "macro_calendar"
    EARNINGS = "earnings"
    BREAKING_NEWS = "breaking_news"
    DAILY_NEWS = "daily_news"


class Importance(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EventStatus(str, Enum):
    SCHEDULED = "scheduled"
    OCCURRED = "occurred"
    UPDATED = "updated"


class QueryMode(str, Enum):
    UPCOMING = "upcoming"
    JUST_HAPPENED = "just_happened"
    WINDOW = "window"


class ViewMode(str, Enum):
    COMPACT = "compact"
    FULL = "full"


# ── Canonical Event ──────────────────────────────────────────────

class Event(BaseModel):
    event_id: str
    event_type: EventType
    title: str
    time_utc: str
    importance: Importance
    status: EventStatus
    tickers: list[str] = []
    country: str = "US"
    snippet: str = ""
    payload: dict = {}
    source: str
    source_id: str


# ── Request Models ───────────────────────────────────────────────

class EventQueryRequest(BaseModel):
    mode: QueryMode = QueryMode.UPCOMING
    start_utc: Optional[str] = None
    end_utc: Optional[str] = None
    horizon_minutes: int = 60
    event_types: Optional[list[EventType]] = None
    tickers: Optional[list[str]] = None
    min_importance: Optional[Importance] = None
    limit: int = 50
    cursor: Optional[str] = None
    view: ViewMode = ViewMode.COMPACT
    now_utc: Optional[str] = None


class StreamRequest(BaseModel):
    cursor: Optional[str] = None
    event_types: Optional[list[EventType]] = None
    tickers: Optional[list[str]] = None
    limit: int = 50
    now_utc: Optional[str] = None


class TriggerNextRequest(BaseModel):
    tickers: Optional[list[str]] = None
    min_importance: Importance = Importance.MEDIUM
    horizon_minutes: int = 1440
    limit: int = 5
    now_utc: Optional[str] = None


class TimelineRequest(BaseModel):
    tickers: Optional[list[str]] = None
    start_utc: Optional[str] = None
    end_utc: Optional[str] = None
    bucket_minutes: int = 60
    now_utc: Optional[str] = None


class EconCalendarRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    min_importance: Optional[Importance] = None
    limit: int = 100
    cursor: Optional[str] = None
    now_utc: Optional[str] = None


class EarningsCalendarRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    tickers: Optional[list[str]] = None
    min_importance: int = 0
    limit: int = 100
    cursor: Optional[str] = None
    now_utc: Optional[str] = None


class NewsSearchRequest(BaseModel):
    tickers: Optional[list[str]] = None
    start_utc: Optional[str] = None
    end_utc: Optional[str] = None
    keyword: Optional[str] = None
    publisher: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: Optional[str] = None
    now_utc: Optional[str] = None


# ── Response Models ──────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    server_time_utc: str
    events: list[Event]
    next_cursor: Optional[str] = None


class TriggerItem(BaseModel):
    trigger_time_utc: str
    event_id: str
    event: Event
    reason_codes: list[str] = []


class TriggerResponse(BaseModel):
    server_time_utc: str
    triggers: list[TriggerItem]


class TimelineBucket(BaseModel):
    bucket_start_utc: str
    bucket_end_utc: str
    count: int
    events: list[Event] = []


class TimelineResponse(BaseModel):
    server_time_utc: str
    buckets: list[TimelineBucket]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    data_freshness: dict
